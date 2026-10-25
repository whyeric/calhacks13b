"""QuickBooks Online: pull revenue and forward-looking commitments from the books.

"Integrations, not uploads": instead of a CSV export, the desk reads the business's books.
Transaction history (SalesReceipt + Invoice) is the bootstrap for the research protocol; the
forward-looking side (open purchase orders, unpaid bills, pending estimates, inventory) is what the
business is already committed to, which is what a hedge is about. The desk also writes its own
bookings back as JournalEntries (`quickbooks_sync.py`).

Two sources, one interface (`QboSource.query(entity) -> list[dict]`), one parser:

- **live**: Intuit's OAuth2 authorization-code flow and the v3 API (`LiveSource`), used iff
  `QBO_CLIENT_ID` and `QBO_CLIENT_SECRET` are set and `DEMO_OFFLINE` is off.
- **demo**: the SYNTHETIC company Hudson Bike Co., read from `fixtures/quickbooks_demo/` (files
  shaped exactly like QBO query responses; `scripts/gen_quickbooks_demo.py` writes them).

The connection (realm id, environment, OAuth tokens and their expiries) is stored in the app DB
(`db.QboConnectionRow`), so it survives a restart. Access tokens (~1 h) are refreshed before they
expire; Intuit rotates the refresh token (~100 days), and every new one is saved. Tokens are never
logged. Disconnect revokes the grant at Intuit and deletes the row. One app holds one connected
company. The OAuth `state` values of pending connects stay in process memory (15 minutes).

QBO sends amounts as JSON numbers; every response is parsed with `parse_float=Decimal` and every
request body is written by `dumps`, so money never passes through a float.
"""

from __future__ import annotations

import base64
import csv
import io
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from typing import Any, Protocol
from urllib.parse import urlencode

import httpx
from sqlalchemy.engine import Engine

from app import clock, db
from app.config import FIXTURES_DIR, Settings, get_settings
from app.models import (
    CommitmentLine,
    Commitments,
    InventoryLine,
    QuickBooksConnect,
    QuickBooksResearch,
    QuickBooksStatus,
)

log = logging.getLogger("hedge_desk.quickbooks")

AUTHORIZE_URL = "https://appcenter.intuit.com/connect/oauth2"
TOKEN_URL = "https://oauth.platform.intuit.com/oauth2/v1/tokens/bearer"
REVOKE_URL = "https://developer.api.intuit.com/v2/oauth2/tokens/revoke"
SCOPE = "com.intuit.quickbooks.accounting"
API_BASE = {
    "sandbox": "https://sandbox-quickbooks.api.intuit.com",
    "production": "https://quickbooks.api.intuit.com",
}
MINOR_VERSION = "75"
PAGE_SIZE = 1000  # QBO's MAXRESULTS cap
BATCH_LIMIT = 30  # QBO's cap on items per /batch request
STATE_TTL = timedelta(minutes=15)
REFRESH_MARGIN = timedelta(seconds=60)
HTTP_TIMEOUT = 20.0
MAX_THROTTLE_RETRIES = 5  # 429s backed off before giving up
MAX_BACKOFF_S = 60.0

DEMO_DIR = FIXTURES_DIR / "quickbooks_demo"
DEMO_REALM = "demo-hudson-bike-co"
DEMO_NOTES = [
    "Pulled from QuickBooks: Hudson Bike Co. is a SYNTHETIC demo company (fixtures/quickbooks_demo/).",
    "Its sales were generated to match the sample revenue file, whose weather effects were planted: "
    "about -20% on rain days, -28% below 40F, +10% above 80F, on real NOAA Central Park days.",
]
# The sandbox seeder (qbo_seed.py) appends this to the PrivateNote of every document it creates,
# so re-runs can recognize them; the parser strips it so seeded and demo text read the same.
SEED_TAG = "[hedge-desk-seed]"

CENT = Decimal("0.01")
ZERO = Decimal("0")
OPEN_ESTIMATE = ("Pending", "Accepted")

# Tests swap in an httpx.MockTransport; None means the real network.
TRANSPORT: httpx.BaseTransport | None = None
SLEEP = time.sleep  # tests patch this to skip real backoff waits


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
    """OAuth tokens for one company. `repr` hides the secrets so a stray log line can't leak them."""

    access_token: str = field(repr=False)
    refresh_token: str = field(repr=False)
    expires_at: datetime
    refresh_expires_at: datetime | None = None


class TokenStore(Protocol):
    """Where a LiveSource reads and saves rotated tokens (the app DB; see `QuickBooks`)."""

    def load_tokens(self) -> Tokens | None: ...

    def save_tokens(self, tokens: Tokens) -> None: ...


def _http() -> httpx.Client:
    return httpx.Client(transport=TRANSPORT, timeout=HTTP_TIMEOUT)


def _basic(settings: Settings) -> str:
    return "Basic " + base64.b64encode(f"{settings.qbo_client_id}:{settings.qbo_client_secret}".encode()).decode()


def _token_request(settings: Settings, data: dict[str, str]) -> Tokens:
    try:
        with _http() as http:
            r = http.post(TOKEN_URL, data=data, headers={"Authorization": _basic(settings),
                                                         "Accept": "application/json"})
    except httpx.HTTPError as e:
        raise Unavailable("Couldn't reach Intuit's token endpoint.", {"reason": type(e).__name__})
    if r.status_code != 200:
        raise Unavailable("Intuit refused the token request; reconnect QuickBooks.",
                          {"status": r.status_code, "grant_type": data.get("grant_type")})
    body = r.json()
    try:
        now = clock.now()
        refresh_ttl = body.get("x_refresh_token_expires_in")
        return Tokens(body["access_token"], body["refresh_token"],
                      now + timedelta(seconds=int(body.get("expires_in", 3600))),
                      now + timedelta(seconds=int(refresh_ttl)) if refresh_ttl is not None else None)
    except (KeyError, TypeError, ValueError):
        raise Unavailable("Intuit's token response was missing fields.", {"grant_type": data.get("grant_type")})


def exchange_code(settings: Settings, code: str) -> Tokens:
    return _token_request(settings, {"grant_type": "authorization_code", "code": code,
                                     "redirect_uri": settings.qbo_redirect_uri})


def refresh_tokens(settings: Settings, refresh_token: str) -> Tokens:
    return _token_request(settings, {"grant_type": "refresh_token", "refresh_token": refresh_token})


def revoke_token(settings: Settings, token: str) -> bool:
    """Intuit's revoke endpoint (revoking the refresh token ends the whole grant). True on 200."""
    try:
        with _http() as http:
            r = http.post(REVOKE_URL, content=json.dumps({"token": token}),
                          headers={"Authorization": _basic(settings), "Accept": "application/json",
                                   "Content-Type": "application/json"})
    except httpx.HTTPError:
        return False
    return r.status_code == 200


def dumps(obj: Any) -> str:
    """JSON with Decimal written as a bare number (Decimal("12.50") -> 12.50), so money never
    becomes a float on its way to QuickBooks. Floats are refused."""
    if isinstance(obj, Decimal):
        return format(obj, "f")
    if isinstance(obj, dict):
        return "{" + ",".join(f"{json.dumps(str(k))}:{dumps(v)}" for k, v in obj.items()) + "}"
    if isinstance(obj, (list, tuple)):
        return "[" + ",".join(dumps(v) for v in obj) + "]"
    if isinstance(obj, float):
        raise TypeError("money must be Decimal, never float")
    return json.dumps(obj)


def _fault(r: httpx.Response) -> list[str]:
    """Intuit's error messages from a Fault body (both `Fault` and `fault` spellings occur)."""
    try:
        body = r.json()
    except ValueError:
        return []
    fault = (body.get("Fault") or body.get("fault") or {}) if isinstance(body, dict) else {}
    errs = fault.get("Error") or fault.get("error") or []
    return [str(e.get("Message") or e.get("message") or "") + (f": {e['Detail']}" if e.get("Detail") else "")
            for e in errs][:5]


def _retry_after(r: httpx.Response, attempt: int) -> float:
    try:
        return min(float(r.headers["Retry-After"]), MAX_BACKOFF_S)
    except (KeyError, ValueError):
        return min(2.0 ** (attempt - 1), MAX_BACKOFF_S)


def _quote(value: str) -> str:
    """Escape a value for a QBO query string literal (backslash-escaped quotes)."""
    return str(value).replace("\\", "\\\\").replace("'", "\\'")


_refresh_lock = threading.Lock()


class LiveSource:
    """Intuit's v3 API for one company (realm): paged queries, lookups, creates and `/batch`.

    The access token is refreshed when it is about to expire, and once more on a 401. Each refresh
    saves the rotated tokens to `store`, under a lock and after re-reading the store, so two callers
    never spend the same refresh token. A 429 backs off (Retry-After, else 1, 2, 4 ... seconds) up
    to MAX_THROTTLE_RETRIES times."""

    synthetic = False

    def __init__(self, settings: Settings, tokens: Tokens, realm_id: str, *, store: TokenStore | None = None,
                 environment: str | None = None):
        self.settings, self.tokens, self.realm_id, self.store = settings, tokens, realm_id, store
        self.environment = environment or settings.qbo_environment
        self.base = API_BASE[self.environment]

    def _refresh(self) -> None:
        with _refresh_lock:
            current = self.store.load_tokens() if self.store is not None else None
            if (current is not None and current.access_token != self.tokens.access_token
                    and current.expires_at - REFRESH_MARGIN > clock.now()):
                new = current  # another caller already refreshed; use its tokens
            else:
                new = refresh_tokens(self.settings, (current or self.tokens).refresh_token)
                if self.store is not None:
                    self.store.save_tokens(new)
            # In place: callers holding this object keep working with the new tokens.
            self.tokens.access_token, self.tokens.refresh_token = new.access_token, new.refresh_token
            self.tokens.expires_at, self.tokens.refresh_expires_at = new.expires_at, new.refresh_expires_at

    def request(self, method: str, path: str, *, params: dict[str, str] | None = None, body: Any = None) -> dict:
        """One call under `/v3/company/{realm}/`; returns the parsed body (Decimal numbers)."""
        if self.tokens.expires_at - REFRESH_MARGIN <= clock.now():
            self._refresh()
        url = f"{self.base}/v3/company/{self.realm_id}/{path}"
        params = {**(params or {}), "minorversion": MINOR_VERSION}
        content = dumps(body) if body is not None else None
        refreshed, throttled = False, 0
        while True:
            headers = {"Authorization": f"Bearer {self.tokens.access_token}", "Accept": "application/json"}
            if content is not None:
                headers["Content-Type"] = "application/json"
            try:
                with _http() as http:
                    r = http.request(method, url, params=params, content=content, headers=headers)
            except httpx.HTTPError as e:
                raise Unavailable("Couldn't reach QuickBooks.", {"reason": type(e).__name__, "path": path})
            if r.status_code == 401:
                if refreshed:
                    raise Unavailable("QuickBooks still refused the refreshed token; reconnect.", {"path": path})
                refreshed = True
                self._refresh()
                continue
            if r.status_code == 429 and throttled < MAX_THROTTLE_RETRIES:
                throttled += 1
                wait = _retry_after(r, throttled)
                log.info("QuickBooks throttled %s (429); retry %d in %.1fs", path, throttled, wait)
                SLEEP(wait)
                continue
            if r.status_code != 200:
                detail: dict[str, Any] = {"status": r.status_code, "path": path, "errors": _fault(r)}
                if "query" in params:
                    detail["query"] = params["query"]
                raise Unavailable("QuickBooks returned an error.", detail)
            return _loads(r.text)

    def _get(self, sql: str) -> dict:
        return self.request("GET", "query", params={"query": sql})

    def query(self, entity: str) -> list[dict]:
        out: list[dict] = []
        start = 1
        while True:
            page = _rows(self._get(f"SELECT * FROM {entity} STARTPOSITION {start} MAXRESULTS {PAGE_SIZE}"), entity)
            out += page
            if len(page) < PAGE_SIZE:
                return out
            start += PAGE_SIZE

    # Lookups and writes, for the JournalEntry mirror (quickbooks_sync.py) and the seeder (qbo_seed.py).

    def find(self, entity: str, field_name: str, value: str) -> list[dict]:
        """Rows where `field_name = value` (one page: names, DocNumbers and Ids are near-unique)."""
        return _rows(self._get(f"SELECT * FROM {entity} WHERE {field_name} = '{_quote(value)}'"), entity)

    def get(self, entity: str, obj_id: str) -> dict | None:
        rows = self.find(entity, "Id", obj_id)
        return rows[0] if rows else None

    def create(self, entity: str, obj: dict) -> dict:
        return self.request("POST", entity.lower(), body=obj)[entity]

    def batch(self, items: list[dict]) -> list[dict]:
        """POST /batch with at most BATCH_LIMIT items (`{"bId", "operation", <Entity>: {...}}` or
        `{"bId", "Query"}`). Returns `BatchItemResponse`: each item has its `bId` and the entity,
        a `QueryResponse`, or a `Fault`."""
        if len(items) > BATCH_LIMIT:
            raise ValueError(f"a QuickBooks batch takes at most {BATCH_LIMIT} items, got {len(items)}")
        return list(self.request("POST", "batch", body={"BatchItemRequest": items}).get("BatchItemResponse") or [])


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


def _note(obj: dict) -> str:
    """PrivateNote without the sandbox seeder's tag."""
    return str(obj.get("PrivateNote") or "").replace(SEED_TAG, "").strip()


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
        description=str(p.get("Memo") or _note(p) or _first_line_desc(p)),
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
            description=str(_note(b) or _first_line_desc(b)), amount=bal,
            due_date=_date(b.get("DueDate")),
            status="Unpaid" if bal >= _money(b.get("TotalAmt")) else "Partially paid",
        ))

    ests = [CommitmentLine(
        id=str(e.get("DocNumber") or e.get("Id")), kind="estimate", counterparty=_ref(e, "CustomerRef"),
        description=str((e.get("CustomerMemo") or {}).get("value") or _first_line_desc(e) or _note(e)),
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


# --- Connection (stored in the app DB) -------------------------------------------------


def _iso(ts: datetime | None) -> str | None:
    return ts.isoformat() if ts is not None else None


def _ts(v: str | None) -> datetime | None:
    return datetime.fromisoformat(v) if v else None


class QuickBooks:
    """The app's one QBO connection, stored in the DB (`db.get_qbo_connection`). Every call reads
    the stored row, so a restart, a second worker or a settings reload sees the same connection.
    The row's `environment` is "demo", "sandbox" or "production"; it only counts as connected in
    the mode it was made in (a demo connection isn't a live one, nor sandbox a production one)."""

    def __init__(self, settings: Settings, engine: Engine | None = None):
        self.settings = settings
        self.engine = engine
        self._lock = threading.Lock()
        self._states: dict[str, datetime] = {}

    @property
    def mode(self) -> str:
        s = self.settings
        return "live" if (s.qbo_client_id and s.qbo_client_secret and not s.demo_offline) else "demo"

    @property
    def environment(self) -> str:
        """The environment a connection must have been made in to count now."""
        return "demo" if self.mode == "demo" else self.settings.qbo_environment

    def _row(self) -> dict[str, Any] | None:
        row = db.get_qbo_connection(self.engine)
        return row if row is not None and row.get("environment") == self.environment else None

    @property
    def connected(self) -> bool:
        return self._row() is not None

    @property
    def realm_id(self) -> str | None:
        row = self._row()
        return row["realm_id"] if row else None

    @property
    def company_name(self) -> str | None:
        row = self._row()
        return row.get("company_name") if row else None

    def status(self) -> QuickBooksStatus:
        row = self._row()
        return QuickBooksStatus(mode=self.mode, connected=row is not None,
                                company_name=row.get("company_name") if row else None,
                                realm_id=row["realm_id"] if row else None,
                                connected_at=_ts(row.get("connected_at")) if row else None,
                                synthetic=self.mode == "demo")

    # Token store (LiveSource saves rotated tokens here).

    def load_tokens(self) -> Tokens | None:
        row = self._row()
        if not row or not row.get("access_token"):
            return None
        return Tokens(row["access_token"], row["refresh_token"], _ts(row["access_expires_at"]),
                      _ts(row.get("refresh_expires_at")))

    def save_tokens(self, tokens: Tokens) -> None:
        row = db.get_qbo_connection(self.engine)
        if row is None:  # disconnected meanwhile: don't resurrect the connection
            return
        row.update(access_token=tokens.access_token, refresh_token=tokens.refresh_token,
                   access_expires_at=_iso(tokens.expires_at), refresh_expires_at=_iso(tokens.refresh_expires_at),
                   updated_at=_iso(clock.now()))
        db.put_qbo_connection(row, self.engine)

    def _save(self, environment: str, realm_id: str, company_name: str | None, tokens: Tokens | None) -> None:
        now = _iso(clock.now())
        db.put_qbo_connection({
            "environment": environment, "realm_id": realm_id, "company_name": company_name,
            "access_token": tokens.access_token if tokens else None,
            "refresh_token": tokens.refresh_token if tokens else None,
            "access_expires_at": _iso(tokens.expires_at) if tokens else None,
            "refresh_expires_at": _iso(tokens.refresh_expires_at) if tokens else None,
            "connected_at": now, "updated_at": now,
        }, self.engine)

    # OAuth flow.

    def connect(self) -> QuickBooksConnect:
        if self.mode == "demo":
            self._save("demo", DEMO_REALM, _company_name(DemoSource()), None)
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
        self._save(self.settings.qbo_environment, realm_id, name, tokens)
        return self.status()

    def disconnect(self) -> QuickBooksStatus:
        """Revoke the grant at Intuit (best effort: a failed revoke still forgets the tokens here,
        and Intuit expires them anyway), then delete the stored connection."""
        row = db.get_qbo_connection(self.engine)
        token = (row or {}).get("refresh_token") or (row or {}).get("access_token")
        if token and self.settings.qbo_client_id and self.settings.qbo_client_secret:
            if not revoke_token(self.settings, token):
                log.warning("QuickBooks token revoke failed for realm %s; deleted locally anyway", row.get("realm_id"))
        db.delete_qbo_connection(self.engine)
        return self.status()

    # Reading and writing the books.

    def source(self) -> QboSource:
        row = self._row()
        if row is None:
            raise NotConnected("QuickBooks isn't connected; connect it first.", {"mode": self.mode})
        if self.mode == "demo":
            return DemoSource()
        return self.live()

    def live(self) -> LiveSource:
        """The live client for the stored connection (NotConnected in demo mode or when disconnected)."""
        tokens = self.load_tokens() if self.mode == "live" else None
        if tokens is None:
            raise NotConnected("QuickBooks isn't connected; connect it first.", {"mode": self.mode})
        if tokens.refresh_expires_at is not None and tokens.refresh_expires_at <= clock.now():
            raise NotConnected("The QuickBooks authorization expired (refresh tokens last about 100 days); "
                               "reconnect.", {"mode": self.mode})
        return LiveSource(self.settings, tokens, self.realm_id or "", store=self, environment=self.environment)

    def commitments(self) -> Commitments:
        return build_commitments(self.source(), clock.now().date())

    def research(self, name: str | None = None) -> QuickBooksResearch:
        """Daily revenue from the books -> the same `date,revenue` CSV the upload takes -> the same
        protocol. Raises `research.ResearchInputError` (422) exactly like POST /research."""
        from app.stats import research as protocol

        src = self.source()
        company = self.company_name
        daily = daily_revenue(src.query("SalesReceipt"), src.query("Invoice"))
        notes = DEMO_NOTES if src.synthetic else [
            f"Pulled from QuickBooks Online (company {company or self.realm_id}): "
            "SalesReceipt + Invoice totals by transaction date."]
        label = (name or company or "")[:60] or None
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
    """The app's connection object; rebuilt when settings are reloaded (the connection itself is
    in the DB, so rebuilding doesn't disconnect)."""
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
