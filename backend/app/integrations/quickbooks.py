"""QuickBooks Online: pull revenue and forward-looking commitments from the books.

"Integrations, not uploads": instead of a CSV export, the desk reads the business's books.
Transaction history (SalesReceipt + Invoice) is the bootstrap for the research protocol; the
forward-looking side (open purchase orders, unpaid bills, pending estimates, inventory) is what the
business is already committed to, which is what a hedge is about.

Two sources, one interface (`QboSource.query(entity) -> list[dict]`), one parser:

- **live**: Intuit's OAuth2 authorization-code flow and the v3 query API (`LiveSource`), used iff
  `QBO_CLIENT_ID` and `QBO_CLIENT_SECRET` are set and `DEMO_OFFLINE` is off.
- **demo**: the SYNTHETIC company Hudson Bike Co., read from `fixtures/quickbooks_demo/` (files
  shaped exactly like QBO query responses; `scripts/gen_quickbooks_demo.py` writes them).

The connection (OAuth tokens, realm id, pending `state` values) lives **in process memory only**:
a restart disconnects, and one API process serves one connected company. Fine for a demo; a real
deployment would store encrypted tokens per business.

QBO sends amounts as JSON numbers; every response is parsed with `parse_float=Decimal` so money
never passes through a float.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import secrets
import threading
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx

from app import clock
from app.config import FIXTURES_DIR, Settings, get_settings
from app.models import (
    CommitmentLine,
    Commitments,
    InventoryLine,
    QuickBooksConnect,
    QuickBooksResearch,
    QuickBooksStatus,
)

AUTHORIZE_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
SCOPE = "com.intuit.quickbooks.accounting"
API_BASE = {
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
    "production": "https://quickbooks.api.intuit.com",
}
MINOR_VERSION = "75"
PAGE_SIZE = 1000  # QBO's MAXRESULTS cap
STATE_TTL = timedelta(minutes=15)
REFRESH_MARGIN = timedelta(seconds=60)
HTTP_TIMEOUT = 20.0

DEMO_DIR = FIXTURES_DIR / "quickbooks_demo"
DEMO_REALM = "demo-hudson-bike-co"
DEMO_NOTES = [
    "Pulled from QuickBooks: Hudson Bike Co. is a SYNTHETIC demo company (fixtures/quickbooks_demo/).",
    "Its sales were generated to match the sample revenue file, whose weather effects were planted: "
    "about -20% on rain days, -28% below 40F, +10% above 80F, on real NOAA Central Park days.",
]

CENT = Decimal("0.01")
ZERO = Decimal("0")
OPEN_ESTIMATE = ("Pending", "Accepted")

# Tests swap in an httpx.MockTransport; None means the real network.
TRANSPORT: httpx.BaseTransport | None = None


# --- Errors ----------------------------------------------------------------------


class QuickBooksError(Exception):
    status = 502
    code = "quickbooks_unavailable"

    def __init__(self, message: str, detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.message = message
        self.detail = detail


class NotConnected(QuickBooksError):
    status = 409
    code = "not_connected"


class Unavailable(QuickBooksError):
    status = 502
    code = "quickbooks_unavailable"


class BadState(QuickBooksError):
    status = 400
    code = "bad_state"


# --- Sources ---------------------------------------------------------------------


class QboSource(Protocol):
    synthetic: bool

    def query(self, entity: str) -> list[dict]:
        """Every row of one QBO entity (`SalesReceipt`, `Bill`, ...), as QBO's JSON objects."""
        ...


def _loads(text: str) -> Any:
    return json.loads(text, parse_float=Decimal)


def _rows(payload: dict, entity: str) -> list[dict]:
    """The rows of one query response page (`QueryResponse` is `{}` when nothing matched)."""
    return list((payload.get("QueryResponse") or {}).get(entity) or [])


class DemoSource:
    """The SYNTHETIC Hudson Bike Co. company, read from files shaped like QBO query responses."""

    synthetic = True

    def __init__(self, folder=DEMO_DIR):
        self.folder = folder

    def query(self, entity: str) -> list[dict]:
        path = self.folder / f"{entity.lower()}.json"
        if not path.exists():
            return []
        return _rows(_loads(path.read_text()), entity)


@dataclass
class Tokens:
    access_token: str
    refresh_token: str
    expires_at: datetime


def _http() -> httpx.Client:
    return httpx.Client(transport=TRANSPORT, timeout=HTTP_TIMEOUT)


def _token_request(settings: Settings, data: dict[str, str]) -> Tokens:
    basic = base64.b64encode(f"{settings.qbo_client_id}:{settings.qbo_client_secret}".encode()).decode()
    try:
        with _http() as http:
            r = http.post(TOKEN_URL, data=data, headers={"Authorization": f"Basic {basic}",
                                                         "Accept": "application/json"})
    except httpx.HTTPError as e:
        raise Unavailable("Couldn't reach Intuit's token endpoint.", {"reason": type(e).__name__})
    if r.status_code != 200:
        raise Unavailable("Intuit refused the token request; reconnect QuickBooks.",
                          {"status": r.status_code, "grant_type": data.get("grant_type")})
    body = r.json()
    try:
        return Tokens(body["access_token"], body["refresh_token"],
                      clock.now() + timedelta(seconds=int(body.get("expires_in", 3600))))
    except (KeyError, TypeError, ValueError):
        raise Unavailable("Intuit's token response was missing fields.", {"grant_type": data.get("grant_type")})


def exchange_code(settings: Settings, code: str) -> Tokens:
    return _token_request(settings, {"grant_type": "authorization_code", "code": code,
                                     "redirect_uri": settings.qbo_redirect_uri})


def refresh_tokens(settings: Settings, refresh_token: str) -> Tokens:
    return _token_request(settings, {"grant_type": "refresh_token", "refresh_token": refresh_token})


class LiveSource:
    """Intuit's v3 query API for one company (realm), paged 1,000 rows at a time. Refreshes the
    access token when it is about to expire, and once more on a 401."""

    synthetic = False

    def __init__(self, settings: Settings, tokens: Tokens, realm_id: str):
        self.settings, self.tokens, self.realm_id = settings, tokens, realm_id
        self.base = API_BASE[settings.qbo_environment]

    def _refresh(self) -> None:
        new = refresh_tokens(self.settings, self.tokens.refresh_token)
        # In place: the connection holds this same object, so the new tokens outlive this call.
        self.tokens.access_token, self.tokens.refresh_token = new.access_token, new.refresh_token
        self.tokens.expires_at = new.expires_at

    def _get(self, sql: str) -> dict:
        if self.tokens.expires_at - REFRESH_MARGIN <= clock.now():
            self._refresh()
        url = f"{self.base}/v3/company/{self.realm_id}/query"
        params = {"query": sql, "minorversion": MINOR_VERSION}
        for attempt in (1, 2):
            try:
                with _http() as http:
                    r = http.get(url, params=params, headers={"Authorization": f"Bearer {self.tokens.access_token}",
                                                              "Accept": "application/json"})
            except httpx.HTTPError as e:
                raise Unavailable("Couldn't reach QuickBooks.", {"reason": type(e).__name__})
            if r.status_code == 401 and attempt == 1:
                self._refresh()
                continue
            if r.status_code != 200:
                raise Unavailable("QuickBooks returned an error.", {"status": r.status_code, "query": sql})
            return _loads(r.text)
        raise Unavailable("QuickBooks still refused the refreshed token; reconnect.", {"query": sql})

    def query(self, entity: str) -> list[dict]:
        out: list[dict] = []
        start = 1
        while True:
            page = _rows(self._get(f"SELECT * FROM {entity} STARTPOSITION {start} MAXRESULTS {PAGE_SIZE}"), entity)
            out += page
            if len(page) < PAGE_SIZE:
                return out
            start += PAGE_SIZE


# --- Parsing (same code for demo and live) -----------------------------------------


def _dec(v: Any) -> Decimal:
    return ZERO if v is None or v == "" else Decimal(str(v))


def _money(v: Any) -> Decimal:
    return _dec(v).quantize(CENT, ROUND_HALF_UP)


def _date(v: Any) -> date | None:
    try:
        return date.fromisoformat(str(v)[:10]) if v else None
    except ValueError:
        return None


def _ref(obj: dict, key: str) -> str:
    return str((obj.get(key) or {}).get("name") or "")


def _first_line_desc(obj: dict) -> str:
    return next((str(ln["Description"]) for ln in obj.get("Line") or [] if ln.get("Description")), "")


def daily_revenue(receipts: list[dict], invoices: list[dict]) -> dict[date, Decimal]:
    """Accrual basis: SalesReceipt + Invoice `TotalAmt` summed by `TxnDate`."""
    days: dict[date, Decimal] = {}
    for t in [*receipts, *invoices]:
        d = _date(t.get("TxnDate"))
        if d is not None:
            days[d] = days.get(d, ZERO) + _money(t.get("TotalAmt"))
    return dict(sorted(days.items()))


def revenue_csv(daily: dict[date, Decimal], notes: list[str]) -> bytes:
    buf = io.StringIO()
    for n in notes:
        buf.write(f"# {n}\n")
    w = csv.writer(buf, lineterminator="\n")
    w.writerow(["date", "revenue"])
    for d, v in daily.items():
        w.writerow([d.isoformat(), str(v)])
    return buf.getvalue().encode()


def _sort(lines: list[CommitmentLine]) -> list[CommitmentLine]:
    return sorted(lines, key=lambda x: (x.due_date is None, x.due_date or date.max, x.id))


def build_commitments(source: QboSource, as_of: date) -> Commitments:
    pos = [CommitmentLine(
        id=str(p.get("DocNumber") or p.get("Id")), kind="purchase_order", counterparty=_ref(p, "VendorRef"),
        description=str(p.get("Memo") or p.get("PrivateNote") or _first_line_desc(p)),
        amount=_money(p.get("TotalAmt")), due_date=_date(p.get("DueDate") or p.get("ShipDate")),
        status=str(p.get("POStatus")),
    ) for p in source.query("PurchaseOrder") if p.get("POStatus") == "Open"]

    bills = []
    for b in source.query("Bill"):
        bal = _money(b.get("Balance"))
        if bal <= 0:
            continue
        bills.append(CommitmentLine(
            id=str(b.get("DocNumber") or b.get("Id")), kind="bill", counterparty=_ref(b, "VendorRef"),
            description=str(b.get("PrivateNote") or _first_line_desc(b)), amount=bal,
            due_date=_date(b.get("DueDate")),
            status="Unpaid" if bal >= _money(b.get("TotalAmt")) else "Partially paid",
        ))

    ests = [CommitmentLine(
        id=str(e.get("DocNumber") or e.get("Id")), kind="estimate", counterparty=_ref(e, "CustomerRef"),
        description=str((e.get("CustomerMemo") or {}).get("value") or _first_line_desc(e) or e.get("PrivateNote") or ""),
        amount=_money(e.get("TotalAmt")),
        # When the booked sale happens: the delivery (ship) date, else expiry, else the estimate's date.
        due_date=_date(e.get("ShipDate") or e.get("ExpirationDate") or e.get("TxnDate")),
        status=str(e.get("TxnStatus")),
    ) for e in source.query("Estimate") if e.get("TxnStatus") in OPEN_ESTIMATE]

    inventory = []
    for i in source.query("Item"):
        if i.get("Type") != "Inventory" or i.get("Active") is False:
            continue
        qty, cost = _dec(i.get("QtyOnHand")), _money(i.get("PurchaseCost"))
        qty = qty.quantize(Decimal(1)) if qty == qty.to_integral_value() else qty.quantize(Decimal("0.0001")).normalize()
        inventory.append(InventoryLine(id=str(i.get("Id")), name=str(i.get("Name") or ""), sku=i.get("Sku") or None,
                                       qty_on_hand=qty, unit_cost=cost,
                                       value=(qty * cost).quantize(CENT, ROUND_HALF_UP)))
    inventory.sort(key=lambda x: (-x.value, x.name))

    pos, bills, ests = _sort(pos), _sort(bills), _sort(ests)
    return Commitments(
        as_of=as_of, synthetic=source.synthetic, purchase_orders=pos, bills=bills, estimates=ests,
        inventory=inventory,
        committed_spend=sum((x.amount for x in pos + bills), ZERO).quantize(CENT),
        expected_revenue=sum((x.amount for x in ests), ZERO).quantize(CENT),
        inventory_value=sum((x.value for x in inventory), ZERO).quantize(CENT),
    )


def _company_name(source: QboSource) -> str | None:
    rows = source.query("CompanyInfo")
    return str(rows[0].get("CompanyName")) if rows and rows[0].get("CompanyName") else None


# --- Connection (process memory) ------------------------------------------------------


class QuickBooks:
    """The one QBO connection this process holds. Thread-safe; nothing is persisted."""

    def __init__(self, settings: Settings):
        self.settings = settings
        self._lock = threading.Lock()
        self._states: dict[str, datetime] = {}
        self._tokens: Tokens | None = None
        self.realm_id: str | None = None
        self.company_name: str | None = None
        self.connected_at: datetime | None = None

    @property
    def mode(self) -> str:
        s = self.settings
        return "live" if (s.qbo_client_id and s.qbo_client_secret and not s.demo_offline) else "demo"

    @property
    def connected(self) -> bool:
        return self.connected_at is not None

    def status(self) -> QuickBooksStatus:
        return QuickBooksStatus(mode=self.mode, connected=self.connected, company_name=self.company_name,
                                realm_id=self.realm_id, connected_at=self.connected_at,
                                synthetic=self.mode == "demo")

    def connect(self) -> QuickBooksConnect:
        if self.mode == "demo":
            name = _company_name(DemoSource())
            with self._lock:
                self.realm_id, self.company_name, self.connected_at = DEMO_REALM, name, clock.now()
            return QuickBooksConnect(status=self.status(), authorize_url=None)
        state = secrets.token_urlsafe(24)
        now = clock.now()
        with self._lock:
            self._states = {k: t for k, t in self._states.items() if now - t < STATE_TTL}
            self._states[state] = now
        query = urlencode({"client_id": self.settings.qbo_client_id, "response_type": "code", "scope": SCOPE,
                           "redirect_uri": self.settings.qbo_redirect_uri, "state": state})
        return QuickBooksConnect(status=self.status(), authorize_url=f"{AUTHORIZE_URL}?{query}")

    def callback(self, code: str | None, state: str | None, realm_id: str | None,
                 error: str | None = None) -> QuickBooksStatus:
        """Intuit's redirect. A missing, unknown or expired `state` is BadState (CSRF check, single use)."""
        with self._lock:
            issued = self._states.pop(state, None) if state else None
        if issued is None or clock.now() - issued >= STATE_TTL:
            raise BadState("The QuickBooks callback's state doesn't match a connect request from this desk.",
                           {"state": state})
        if error or not code or not realm_id:
            raise Unavailable("QuickBooks didn't authorize the connection.", {"error": error})
        tokens = exchange_code(self.settings, code)
        name = _company_name(LiveSource(self.settings, tokens, realm_id))
        with self._lock:
            self._tokens, self.realm_id, self.company_name = tokens, realm_id, name
            self.connected_at = clock.now()
        return self.status()

    def disconnect(self) -> QuickBooksStatus:
        with self._lock:
            self._tokens, self.realm_id, self.company_name, self.connected_at = None, None, None, None
        return self.status()

    def source(self) -> QboSource:
        if not self.connected:
            raise NotConnected("QuickBooks isn't connected; connect it first.", {"mode": self.mode})
        if self.mode == "demo":
            return DemoSource()
        if self._tokens is None or self.realm_id is None:  # mode flipped to live after a demo connect
            raise NotConnected("QuickBooks isn't connected; connect it first.", {"mode": self.mode})
        return LiveSource(self.settings, self._tokens, self.realm_id)

    def commitments(self) -> Commitments:
        return build_commitments(self.source(), clock.now().date())

    def research(self, name: str | None = None) -> QuickBooksResearch:
        """Daily revenue from the books -> the same `date,revenue` CSV the upload takes -> the same
        protocol. Raises `research.ResearchInputError` (422) exactly like POST /research."""
        from app.stats import research as protocol

        src = self.source()
        daily = daily_revenue(src.query("SalesReceipt"), src.query("Invoice"))
        notes = DEMO_NOTES if src.synthetic else [
            f"Pulled from QuickBooks Online (company {self.company_name or self.realm_id}): "
            "SalesReceipt + Invoice totals by transaction date."]
        label = (name or self.company_name or "")[:60] or None
        report = protocol.run(revenue_csv(daily, notes), label)
        days = list(daily)
        return QuickBooksResearch(
            report=report,
            revenue_source=("QuickBooks Online: SalesReceipt + Invoice TotalAmt summed by TxnDate "
                            "(accrual basis: an invoice counts on its date, not when it is paid)"),
            days=len(days), first_day=days[0], last_day=days[-1],
            commitments=build_commitments(src, clock.now().date()), synthetic=src.synthetic,
        )


_conn: QuickBooks | None = None
_conn_lock = threading.Lock()


def get() -> QuickBooks:
    """The process's connection; rebuilt (disconnected) when settings are reloaded."""
    global _conn
    s = get_settings()
    with _conn_lock:
        if _conn is None or _conn.settings is not s:
            _conn = QuickBooks(s)
        return _conn


def reset() -> None:
    global _conn
    with _conn_lock:
        _conn = None
