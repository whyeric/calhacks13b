"""Increase: a real bank as the bank leg of three-way reconciliation (docs/INCREASE.md).

The bank is the system of record for cash received. With `INCREASE_API_KEY` and
`INCREASE_ACCOUNT_ID` set (and `DEMO_OFFLINE` off), reconciliation reads the operating account's
posted Transactions and its still-pending inbound ACH transfers from Increase
(`IncreaseBankSource`, origin `increase_sandbox` or `increase_live`). Otherwise it reads the
simulated bank CSV (`CsvBankSource`, origin `csv_simulated`). Sandbox money is not real money, so
a sandbox row is still labeled simulated (I6); only `increase_live` counts as live.

A bank does not know our hedge ids. A row's `reference` is set only when the transfer really
carries one (an `hdg_...` id in the ACH addenda, discretionary data or descriptor); otherwise it
is `None` and reconcile matches the row on amount and date.

API shapes (https://increase.com/documentation): `Authorization: Bearer <key>`; lists return
`{"data": [...], "next_cursor": str | null}` and take `cursor`, `limit` (max 100) and filters such
as `account_id`, `status.in`; amounts are integer cents (inbound positive, outbound negative);
POSTs accept an `Idempotency-Key` header (same key + same body replays the first result).
Sandbox-only `/simulations/...` endpoints create inbound ACH transfers and move outbound ones along.
"""

from __future__ import annotations

import re
import threading
from collections.abc import Iterator
from datetime import date, datetime
from decimal import Decimal
from typing import Any

import httpx

from app import clock
from app.books.ledger import ny_date
from app.books.sources import BankOrigin, BankRow, BankSource, CsvBankSource, SourceUnavailable
from app.config import Settings, get_settings
from app.models import IncreaseStatus

BASE_URL = {"sandbox": "https://sandbox.increase.com", "production": "https://api.increase.com"}
PAGE_LIMIT = 100
HTTP_TIMEOUT = 20.0
CENT = Decimal("0.01")

# Tests swap in an httpx.MockTransport; None means the real network.
TRANSPORT: httpx.BaseTransport | None = None

HEDGE_ID = re.compile(r"\b(hdg_[A-Za-z0-9_]+)\b")
OPENING = re.compile(r"\bopening[_ ]deposit\b", re.IGNORECASE)  # our transfer out to fund the venue
OPENING_BALANCE = re.compile(r"\bopening[_ ]balance\b", re.IGNORECASE)  # owner money in before hedging


# --- Errors ----------------------------------------------------------------------


class IncreaseError(SourceUnavailable):
    """Increase refused or couldn't be reached. `type` is Increase's error type when it sent one."""

    def __init__(self, message: str, *, status: int | None = None, type: str | None = None,
                 detail: dict[str, Any] | None = None):
        super().__init__(message)
        self.message, self.status, self.type, self.detail = message, status, type, detail or {}


class Offline(IncreaseError):
    """DEMO_OFFLINE is on: no request is made."""


# --- Client ----------------------------------------------------------------------


def cents_to_usd(amount: Any) -> Decimal:
    """Increase amounts are integer cents; never accept a float or a fractional value."""
    if isinstance(amount, bool) or not isinstance(amount, int):
        raise IncreaseError("Increase amount is not an integer number of cents.", detail={"amount": repr(amount)})
    return (Decimal(amount) / 100).quantize(CENT)


def usd_to_cents(amount: Decimal) -> int:
    q = Decimal(amount).quantize(CENT)
    if q != Decimal(amount):
        raise ValueError(f"{amount} is not a whole number of cents")
    return int(q * 100)


class IncreaseClient:
    """A small sync client for the endpoints the desk uses. `transport` is injectable for tests."""

    def __init__(
        self,
        api_key: str,
        environment: str = "sandbox",
        *,
        base_url: str | None = None,
        transport: httpx.BaseTransport | None = None,
        offline: bool = False,
        timeout: float = HTTP_TIMEOUT,
    ):
        if not api_key:
            raise IncreaseError("No Increase API key.")
        self.environment = environment
        self.offline = offline
        self.base_url = base_url or BASE_URL[environment]
        self._http = httpx.Client(
            base_url=self.base_url,
            transport=transport if transport is not None else TRANSPORT,
            timeout=timeout,
            headers={"Authorization": f"Bearer {api_key}", "Accept": "application/json"},
        )

    @classmethod
    def from_settings(cls, settings: Settings | None = None, **kw: Any) -> IncreaseClient:
        s = settings or get_settings()
        return cls(s.increase_api_key or "", s.increase_environment, offline=s.demo_offline, **kw)

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> IncreaseClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # -- transport --

    def request(self, method: str, path: str, *, params: dict[str, Any] | None = None,
                json: dict[str, Any] | None = None, idempotency_key: str | None = None) -> dict[str, Any]:
        if self.offline:
            raise Offline("DEMO_OFFLINE is set; Increase is not called.", detail={"path": path})
        headers = {"Idempotency-Key": idempotency_key} if idempotency_key else None
        try:
            r = self._http.request(method, path, params=params, json=json, headers=headers)
        except httpx.HTTPError as e:
            raise IncreaseError("Couldn't reach Increase.", detail={"path": path, "reason": type(e).__name__})
        if r.status_code >= 400:
            try:
                body = r.json()
            except ValueError:
                body = {}
            raise IncreaseError(
                str(body.get("title") or body.get("detail") or f"Increase returned HTTP {r.status_code}."),
                status=r.status_code, type=body.get("type"),
                detail={"path": path, "status": r.status_code, "resource_id": body.get("resource_id")},
            )
        try:
            return r.json()
        except ValueError:
            raise IncreaseError("Increase sent a response that isn't JSON.", detail={"path": path})

    def paginate(self, path: str, params: dict[str, Any] | None = None) -> Iterator[dict[str, Any]]:
        """Every object of a list endpoint, following `next_cursor`."""
        q = {**(params or {}), "limit": PAGE_LIMIT}
        seen: set[str] = set()
        while True:
            page = self.request("GET", path, params=q)
            yield from page.get("data") or []
            cursor = page.get("next_cursor")
            if not cursor or cursor in seen:  # a repeated cursor would loop forever
                return
            seen.add(cursor)
            q = {**q, "cursor": cursor}

    # -- accounts and account numbers --

    def get_account(self, account_id: str) -> dict[str, Any]:
        return self.request("GET", f"/accounts/{account_id}")

    def list_accounts(self, *, status: str = "open") -> list[dict[str, Any]]:
        return list(self.paginate("/accounts", {"status.in": status}))

    def create_account(self, name: str, *, idempotency_key: str, program_id: str | None = None,
                       entity_id: str | None = None) -> dict[str, Any]:
        body: dict[str, Any] = {"name": name}
        if program_id:
            body["program_id"] = program_id
        if entity_id:
            body["entity_id"] = entity_id
        return self.request("POST", "/accounts", json=body, idempotency_key=idempotency_key)

    def list_account_numbers(self, account_id: str) -> list[dict[str, Any]]:
        return list(self.paginate("/account_numbers", {"account_id": account_id, "status.in": "active"}))

    def create_account_number(self, account_id: str, name: str, *, idempotency_key: str) -> dict[str, Any]:
        return self.request("POST", "/account_numbers", json={"account_id": account_id, "name": name},
                            idempotency_key=idempotency_key)

    # -- money movement --

    def list_transactions(self, account_id: str) -> list[dict[str, Any]]:
        return list(self.paginate("/transactions", {"account_id": account_id}))

    def list_inbound_ach_transfers(self, account_id: str, *, status: str = "pending") -> list[dict[str, Any]]:
        return list(self.paginate("/inbound_ach_transfers", {"account_id": account_id, "status.in": status}))

    def list_ach_transfers(self, account_id: str) -> list[dict[str, Any]]:
        return list(self.paginate("/ach_transfers", {"account_id": account_id}))

    def create_ach_transfer(self, account_id: str, amount_cents: int, *, statement_descriptor: str,
                            account_number: str, routing_number: str, individual_name: str | None = None,
                            idempotency_key: str) -> dict[str, Any]:
        body: dict[str, Any] = {
            "account_id": account_id, "amount": amount_cents, "statement_descriptor": statement_descriptor,
            "account_number": account_number, "routing_number": routing_number,
        }
        if individual_name:
            body["individual_name"] = individual_name[:22]
        return self.request("POST", "/ach_transfers", json=body, idempotency_key=idempotency_key)

    # -- sandbox simulations (sandbox only) --

    def _sandbox_only(self) -> None:
        if self.environment != "sandbox":
            raise IncreaseError("Simulation endpoints exist only in the Increase sandbox.")

    def simulate_ach_transfer_submit(self, ach_transfer_id: str) -> dict[str, Any]:
        self._sandbox_only()
        return self.request("POST", f"/simulations/ach_transfers/{ach_transfer_id}/submit")

    def simulate_inbound_ach_transfer(
        self,
        account_number_id: str,
        amount_cents: int,
        *,
        company_name: str | None = None,
        company_entry_description: str | None = None,
        company_discretionary_data: str | None = None,
        addenda: str | None = None,
        resolve_at: datetime | None = None,
        idempotency_key: str,
    ) -> dict[str, Any]:
        """An inbound ACH credit into `account_number_id`. With `resolve_at` it stays `pending`
        until then (a deposit in transit); without it, it resolves at once into a Transaction."""
        self._sandbox_only()
        body: dict[str, Any] = {"account_number_id": account_number_id, "amount": amount_cents}
        if company_name:
            body["company_name"] = company_name[:16]
        if company_entry_description:
            body["company_entry_description"] = company_entry_description[:10]
        if company_discretionary_data:
            body["company_discretionary_data"] = company_discretionary_data[:20]
        if addenda:
            body["addenda"] = {"category": "freeform",
                               "freeform": {"entries": [{"payment_related_information": addenda[:80]}]}}
        if resolve_at is not None:
            body["resolve_at"] = resolve_at.isoformat().replace("+00:00", "Z")
        return self.request("POST", "/simulations/inbound_ach_transfers", json=body,
                            idempotency_key=idempotency_key)


# --- Bank rows ---------------------------------------------------------------------


def _texts(obj: Any) -> Iterator[str]:
    """Every string inside a (nested) Increase object: descriptors, addenda entries, names."""
    if isinstance(obj, str):
        yield obj
    elif isinstance(obj, dict):
        for v in obj.values():
            yield from _texts(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _texts(v)


def find_reference(*parts: Any) -> str | None:
    """A hedge id (or `opening_deposit`) only if one of the transfer's own fields really carries it."""
    texts = [t for p in parts for t in _texts(p)]
    for t in texts:
        m = HEDGE_ID.search(t)
        if m:
            return m.group(1)
    if any(OPENING.search(t) for t in texts):
        return "opening_deposit"
    return "opening_balance" if any(OPENING_BALANCE.search(t) for t in texts) else None


def _on(ts: str) -> date:
    return ny_date(datetime.fromisoformat(ts.replace("Z", "+00:00")))


def transaction_row(tx: dict[str, Any], origin: BankOrigin) -> BankRow:
    """A posted Increase Transaction as a BankRow (date in New York time, like the ledger)."""
    source = tx.get("source") or {}
    detail = source.get(source.get("category") or "") or {}
    return BankRow(
        date=_on(tx["created_at"]),
        amount=cents_to_usd(tx["amount"]),
        description=str(tx.get("description") or source.get("category") or "Increase transaction"),
        reference=find_reference(tx.get("description"), detail),
        external_id=tx.get("id"),
        origin=origin,
        status="posted",
    )


def pending_inbound_row(t: dict[str, Any], origin: BankOrigin) -> BankRow:
    """A still-pending inbound ACH transfer: seen by the bank, not yet cash (in transit)."""
    desc = " ".join(str(t.get(k) or "") for k in ("originator_company_name", "originator_company_entry_description"))
    return BankRow(
        date=_on(t["created_at"]),
        amount=cents_to_usd(t["amount"]) * (-1 if t.get("direction") == "debit" else 1),
        description=f"PENDING ACH {desc.strip()}".strip(),
        reference=find_reference(t.get("addenda"), t.get("originator_company_discretionary_data"),
                                 t.get("originator_company_entry_description")),
        external_id=t.get("id"),
        origin=origin,
        status="pending",
    )


_sync_lock = threading.Lock()
LAST_SYNC: dict[str, dict[str, Any]] = {}  # account id -> {"at", "n_rows", "error"}; for the status route


class IncreaseBankSource:
    """One Increase account's posted transactions plus its pending inbound ACH transfers."""

    def __init__(self, client: IncreaseClient, account_id: str):
        self.client, self.account_id = client, account_id
        self.origin: BankOrigin = "increase_sandbox" if client.environment == "sandbox" else "increase_live"

    def rows(self, business_id: str) -> list[BankRow]:
        try:
            posted = [transaction_row(t, self.origin) for t in self.client.list_transactions(self.account_id)]
            pending = [pending_inbound_row(t, self.origin)
                       for t in self.client.list_inbound_ach_transfers(self.account_id, status="pending")]
        except IncreaseError as e:
            with _sync_lock:
                LAST_SYNC[self.account_id] = {"at": clock.now(), "n_rows": None, "error": e.message}
            raise
        rows = sorted(posted + pending, key=lambda r: (r.date, r.external_id or ""))
        with _sync_lock:
            LAST_SYNC[self.account_id] = {"at": clock.now(), "n_rows": len(rows), "error": None}
        return rows


# --- Selection ---------------------------------------------------------------------


def account_ids(settings: Settings | None = None) -> dict[str, str]:
    """`INCREASE_ACCOUNT_ID` is one account id for every business, or a per-business map
    `taxi=account_1,restaurant=account_2`. Returns {business_id or "*": account_id}."""
    raw = ((settings or get_settings()).increase_account_id or "").strip()
    if not raw:
        return {}
    if "=" not in raw:
        return {"*": raw}
    out: dict[str, str] = {}
    for part in raw.split(","):
        if "=" in part:
            k, v = part.split("=", 1)
            if k.strip() and v.strip():
                out[k.strip()] = v.strip()
    return out


def account_for(business_id: str, settings: Settings | None = None) -> str | None:
    ids = account_ids(settings)
    return ids.get(business_id) or ids.get("*")


def mode(settings: Settings | None = None) -> str:
    """demo (the simulated CSV), sandbox or live."""
    s = settings or get_settings()
    if s.demo_offline or not s.increase_api_key or not account_ids(s):
        return "demo"
    return "sandbox" if s.increase_environment == "sandbox" else "live"


def get_bank_source(business_id: str, settings: Settings | None = None,
                    transport: httpx.BaseTransport | None = None) -> BankSource:
    """Increase when a key and an account for this business are set and we're not offline;
    otherwise the simulated bank CSV."""
    s = settings or get_settings()
    account = account_for(business_id, s)
    if mode(s) == "demo" or account is None:
        return CsvBankSource()
    return IncreaseBankSource(IncreaseClient.from_settings(s, transport=transport), account)


def status(settings: Settings | None = None) -> IncreaseStatus:
    """Mode, accounts and the last bank read in this process. Makes no network call."""
    s = settings or get_settings()
    m = mode(s)
    ids = account_ids(s) if m != "demo" else {}
    with _sync_lock:
        syncs = [LAST_SYNC[a] for a in ids.values() if a in LAST_SYNC]
    last = max(syncs, key=lambda x: x["at"]) if syncs else None
    return IncreaseStatus(
        mode=m,
        environment=s.increase_environment,
        accounts=ids,
        bank_origin={"demo": "csv_simulated", "sandbox": "increase_sandbox", "live": "increase_live"}[m],
        simulated=m != "live",
        last_sync=last["at"] if last else None,
        last_rows=last["n_rows"] if last else None,
        last_error=last["error"] if last else None,
    )
