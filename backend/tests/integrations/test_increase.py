"""Increase bank integration against a mocked Increase API (no network): client, bank rows,
source selection, the status route, three-way reconciliation on a sandbox bank, and the
idempotent sandbox staging script."""

from __future__ import annotations

import json
from datetime import UTC, datetime
from decimal import Decimal

import httpx
import pytest

from app import clock
from app.books.reconcile import reconcile
from app.books.seed import seed_books
from app.books.sources import CsvBankSource
from app.config import Settings
from app.integrations import increase as inc

NOW = datetime(2026, 10, 24, 19, 0, tzinfo=UTC)
D = Decimal


class FakeIncrease:
    """A tiny in-memory Increase: list endpoints with cursor pagination, POSTs with idempotency."""

    def __init__(self, transactions=(), pending=(), page_size=2):
        self.transactions = list(transactions)
        self.pending = list(pending)
        self.page_size = page_size
        self.accounts: list[dict] = []
        self.numbers: list[dict] = []
        self.keys: dict[str, tuple[str, dict]] = {}  # idempotency key -> (body json, response)
        self.calls: list[httpx.Request] = []
        self.inbound: list[dict] = []
        self.ach: list[dict] = []
        self.transport = httpx.MockTransport(self._handle)

    def _page(self, request: httpx.Request, items: list[dict]) -> httpx.Response:
        start = int(request.url.params.get("cursor") or 0)
        end = start + self.page_size
        return httpx.Response(200, json={"data": items[start:end],
                                         "next_cursor": str(end) if end < len(items) else None})

    def _create(self, request: httpx.Request, make) -> httpx.Response:
        key = request.headers.get("Idempotency-Key")
        body = json.loads(request.content or b"{}")
        if key in self.keys:
            prev_body, prev = self.keys[key]
            if prev_body != body:
                return httpx.Response(409, json={"type": "idempotency_key_already_used_error",
                                                 "title": "Key already used", "resource_id": prev["id"]})
            return httpx.Response(200, json=prev, headers={"Idempotent-Replayed": "true"})
        obj = make(body)
        if key:
            self.keys[key] = (body, obj)
        return httpx.Response(200, json=obj)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        if request.headers.get("Authorization") != "Bearer test_key":
            return httpx.Response(401, json={"type": "invalid_api_key_error", "title": "Invalid API key"})
        p, m = request.url.path, request.method
        if m == "GET" and p == "/transactions":
            return self._page(request, self.transactions)
        if m == "GET" and p == "/inbound_ach_transfers":
            return self._page(request, self.pending)
        if m == "GET" and p == "/accounts":
            return self._page(request, self.accounts)
        if m == "GET" and p == "/account_numbers":
            acct = request.url.params.get("account_id")
            return self._page(request, [n for n in self.numbers if n["account_id"] == acct])
        if m == "POST" and p == "/accounts":
            def make(b):
                a = {"id": f"account_{len(self.accounts) + 1}", "name": b["name"], "status": "open"}
                self.accounts.append(a)
                return a
            return self._create(request, make)
        if m == "POST" and p == "/account_numbers":
            def make(b):
                n = {"id": f"account_number_{len(self.numbers) + 1}", "account_id": b["account_id"],
                     "status": "active"}
                self.numbers.append(n)
                return n
            return self._create(request, make)
        if m == "POST" and p == "/ach_transfers":
            def make(b):
                t = {"id": f"ach_transfer_{len(self.ach) + 1}", "status": "pending_submission", **b}
                self.ach.append(t)
                return t
            return self._create(request, make)
        if m == "POST" and p.startswith("/simulations/ach_transfers/"):
            return httpx.Response(200, json={"id": p.split("/")[3], "status": "submitted"})
        if m == "POST" and p == "/simulations/inbound_ach_transfers":
            def make(b):
                t = {"id": f"inbound_ach_transfer_{len(self.inbound) + 1}", **b}
                self.inbound.append(t)
                return t
            return self._create(request, make)
        return httpx.Response(404, json={"type": "not_found_error", "title": "Not found"})


def tx(id, amount, created, description, category="inbound_ach_transfer", **detail):
    return {"id": id, "type": "transaction", "account_id": "account_1", "amount": amount, "currency": "USD",
            "created_at": created, "description": description,
            "source": {"category": category, category: detail}}


def deposit(id, amount, created, *, addenda=None):
    add = ({"category": "freeform", "freeform": {"entries": [{"payment_related_information": addenda}]}}
           if addenda else None)
    return tx(id, amount, created, "KALSHI WITHDRAWAL", originator_company_name="KALSHI",
              originator_company_entry_description="WITHDRAWAL", addenda=add, trace_number="021000038461022")


@pytest.fixture(autouse=True)
def _clock(monkeypatch):
    monkeypatch.setattr(clock, "now", lambda: NOW)
    inc.LAST_SYNC.clear()


def client(fake: FakeIncrease, env="sandbox", **kw) -> inc.IncreaseClient:
    return inc.IncreaseClient("test_key", env, transport=fake.transport, **kw)


# --- Client ------------------------------------------------------------------------------


def test_paginates_with_cursor_and_bearer_auth():
    fake = FakeIncrease(transactions=[deposit(f"transaction_{i}", 100 * i, "2026-10-21T15:00:00Z") for i in range(5)])
    rows = client(fake).list_transactions("account_1")
    assert [r["id"] for r in rows] == [f"transaction_{i}" for i in range(5)]
    assert len(fake.calls) == 3  # pages of 2: 0-1, 2-3, 4
    assert fake.calls[0].url.host == "sandbox.increase.com"
    assert fake.calls[0].url.params["account_id"] == "account_1" and fake.calls[0].url.params["limit"] == "100"
    assert [c.url.params.get("cursor") for c in fake.calls] == [None, "2", "4"]


def test_production_uses_the_live_host():
    fake = FakeIncrease()
    client(fake, "production").list_transactions("account_1")
    assert fake.calls[0].url.host == "api.increase.com"


def test_errors_are_increase_errors():
    fake = FakeIncrease()
    bad = inc.IncreaseClient("wrong", "sandbox", transport=fake.transport)
    with pytest.raises(inc.IncreaseError) as e:
        bad.list_transactions("account_1")
    assert e.value.status == 401 and e.value.type == "invalid_api_key_error"

    def boom(request):
        raise httpx.ConnectError("down", request=request)

    down = inc.IncreaseClient("test_key", transport=httpx.MockTransport(boom))
    with pytest.raises(inc.IncreaseError, match="Couldn't reach Increase"):
        down.list_transactions("account_1")


def test_offline_makes_no_request():
    fake = FakeIncrease()
    with pytest.raises(inc.Offline):
        client(fake, offline=True).list_transactions("account_1")
    assert fake.calls == []


def test_simulations_are_sandbox_only():
    with pytest.raises(inc.IncreaseError, match="sandbox"):
        client(FakeIncrease(), "production").simulate_inbound_ach_transfer("account_number_1", 100, idempotency_key="k")


def test_amounts_are_integer_cents():
    assert inc.cents_to_usd(5911) == D("59.11") and inc.cents_to_usd(-50000) == D("-500.00")
    for bad in (59.11, "5911", True):
        with pytest.raises(inc.IncreaseError):
            inc.cents_to_usd(bad)
    assert inc.usd_to_cents(D("59.11")) == 5911
    with pytest.raises(ValueError):
        inc.usd_to_cents(D("1.005"))


# --- Bank rows -----------------------------------------------------------------------------


def test_reference_only_when_the_transfer_carries_it():
    with_ref = inc.transaction_row(deposit("transaction_1", 5911, "2026-10-21T15:00:00Z",
                                           addenda="Kalshi withdrawal hdg_s01"), "increase_sandbox")
    assert (with_ref.reference, with_ref.amount, with_ref.external_id) == ("hdg_s01", D("59.11"), "transaction_1")
    assert with_ref.date.isoformat() == "2026-10-21" and with_ref.status == "posted" and with_ref.simulated
    bare = inc.transaction_row(deposit("transaction_2", 4500, "2026-10-24T02:00:00Z"), "increase_live")
    assert bare.reference is None and not bare.simulated
    assert bare.date.isoformat() == "2026-10-23"  # 02:00 UTC is the evening before in New York
    out = inc.transaction_row(tx("transaction_3", -50000, "2026-10-12T15:00:00Z", "ACH transfer",
                                 "ach_transfer_intention", statement_descriptor="opening_deposit to Kalshi"),
                              "increase_sandbox")
    assert out.reference == "opening_deposit" and out.amount == D("-500.00")


def test_bank_source_reads_posted_and_pending():
    fake = FakeIncrease(
        transactions=[deposit("transaction_1", 5911, "2026-10-21T15:00:00Z", addenda="hdg_s01")],
        pending=[{"id": "inbound_ach_transfer_9", "amount": 4500, "direction": "credit", "status": "pending",
                  "created_at": "2026-10-23T15:00:00Z", "originator_company_name": "KALSHI",
                  "originator_company_entry_description": "WITHDRAWAL", "originator_company_discretionary_data": None,
                  "addenda": None}],
    )
    src = inc.IncreaseBankSource(client(fake), "account_1")
    rows = src.rows("taxi")
    assert src.origin == "increase_sandbox"
    assert [(r.external_id, r.status, r.amount) for r in rows] == [
        ("transaction_1", "posted", D("59.11")), ("inbound_ach_transfer_9", "pending", D("45.00"))]
    pend_call = next(c for c in fake.calls if c.url.path == "/inbound_ach_transfers")
    assert pend_call.url.params["status.in"] == "pending"
    assert inc.LAST_SYNC["account_1"] == {"at": NOW, "n_rows": 2, "error": None}


# --- Selection and status --------------------------------------------------------------------


def test_selector():
    def s(**kw):
        return Settings(_env_file=None, **kw)

    assert isinstance(inc.get_bank_source("taxi", s()), CsvBankSource)
    assert isinstance(inc.get_bank_source("taxi", s(increase_api_key="k")), CsvBankSource)  # no account
    offline = s(increase_api_key="k", increase_account_id="account_1", demo_offline=True)
    assert isinstance(inc.get_bank_source("taxi", offline), CsvBankSource)
    live = inc.get_bank_source("taxi", s(increase_api_key="k", increase_account_id="account_1"))
    assert isinstance(live, inc.IncreaseBankSource) and live.account_id == "account_1"
    mapped = s(increase_api_key="k", increase_account_id="taxi=account_1, restaurant=account_2")
    assert inc.get_bank_source("restaurant", mapped).account_id == "account_2"
    assert isinstance(inc.get_bank_source("other", mapped), CsvBankSource)
    assert inc.mode(s(increase_api_key="k", increase_account_id="a", increase_environment="production")) == "live"


def test_status(monkeypatch):
    st = inc.status(Settings(_env_file=None))
    assert (st.mode, st.bank_origin, st.simulated, st.accounts, st.last_sync) == ("demo", "csv_simulated", True, {}, None)
    inc.LAST_SYNC["account_1"] = {"at": NOW, "n_rows": 3, "error": None}
    st = inc.status(Settings(_env_file=None, increase_api_key="k", increase_account_id="taxi=account_1"))
    assert (st.mode, st.bank_origin, st.accounts, st.last_rows) == ("sandbox", "increase_sandbox", {"taxi": "account_1"}, 3)


# --- Three-way reconciliation on a sandbox bank -----------------------------------------------


@pytest.fixture
def books(tmp_path):
    from app import db

    engine = db.make_engine(f"sqlite:///{tmp_path / 'books.db'}")
    db.create_schema(engine)
    (tmp_path / "l").mkdir()
    (tmp_path / "o").mkdir()
    seed_books(engine, ledger_dir=tmp_path / "l", out_dir=tmp_path / "o")
    yield engine
    engine.dispose()


def staged_bank(*, s03_pending=True) -> FakeIncrease:
    """What the staging script leaves in the sandbox for taxi."""
    pending = []
    txs = [
        tx("transaction_0", 100000, "2026-10-12T14:00:00Z", "OWNER CAPITAL", addenda={
            "category": "freeform", "freeform": {"entries": [{"payment_related_information": "OWNER CAPITAL opening_balance"}]}}),
        tx("transaction_1", -50000, "2026-10-12T15:00:00Z", "ACH transfer", "ach_transfer_intention",
           statement_descriptor="opening_deposit to Kalshi"),
        deposit("transaction_2", 5911, "2026-10-21T15:00:00Z", addenda="Kalshi withdrawal hdg_s01"),
    ]
    s03 = {"id": "inbound_ach_transfer_3", "amount": 4500, "direction": "credit", "status": "pending",
           "created_at": "2026-10-23T16:00:00Z", "originator_company_name": "KALSHI",
           "originator_company_entry_description": "WITHDRAWAL", "originator_company_discretionary_data": None,
           "addenda": {"category": "freeform", "freeform": {"entries": [{"payment_related_information": "Kalshi withdrawal hdg_s03"}]}}}
    if s03_pending:
        pending.append(s03)
    else:  # posted, with no reference: matched on amount and date
        txs.append(deposit("transaction_3", 4500, "2026-10-24T15:00:00Z"))
    return FakeIncrease(transactions=txs, pending=pending)


def test_reconcile_against_sandbox_bank(books):
    bank = inc.IncreaseBankSource(client(staged_bank()), "account_1")
    r = reconcile("taxi", engine=books, log=False, bank=bank)
    assert r.simulated is True and r.sources.bank_origin == "increase_sandbox" and not r.sources.live
    assert any("opening balance" in n for n in r.sources.notes)
    [m] = r.mismatches
    assert (m.hedge_id, m.likely_cause, m.difference) == ("hdg_s01", "fee_deducted_from_deposit", D("-0.89"))
    assert m.system_of_record == "bank" and m.bank_origin == "increase_sandbox" and m.venue_origin == "simulated"
    assert "Kalshi paid $60.00 and we booked $60.00" in m.explanation and "the bank received $59.11" in m.explanation
    [t] = r.in_transit
    assert (t.hedge_id, t.bank_pending, t.bank_origin) == ("hdg_s03", D("45.00"), "increase_sandbox")
    assert [x.hedge_id for x in r.matches] == ["hdg_s02"]  # expired: nothing owed, nothing deposited
    assert r.summary.n_in_transit == 1


def test_unreferenced_sandbox_deposit_matches_on_amount_and_date(books):
    bank = inc.IncreaseBankSource(client(staged_bank(s03_pending=False)), "account_1")
    r = reconcile("taxi", engine=books, log=False, bank=bank)
    assert [x.hedge_id for x in r.matches] == ["hdg_s02", "hdg_s03"]
    assert r.in_transit == [] and [m.hedge_id for m in r.mismatches] == ["hdg_s01"]


def test_unreachable_bank_falls_back_to_the_csv_and_says_so(books, tmp_path):
    bad = inc.IncreaseBankSource(inc.IncreaseClient("wrong", transport=FakeIncrease().transport), "account_1")
    r = reconcile("taxi", engine=books, log=False, bank=bad, statement=tmp_path / "o" / "bank_statement.csv")
    assert r.sources.bank_origin == "csv_simulated"
    assert any("increase_sandbox could not be read" in n for n in r.sources.notes)
    assert inc.LAST_SYNC["account_1"]["error"]
    assert [m.likely_cause for m in r.mismatches] == ["fee_deducted_from_deposit"]


# --- Staging script --------------------------------------------------------------------------


def test_stage_script_is_idempotent(capsys):
    from scripts import stage_increase_sandbox as stage

    plans = {p.business_id: p for p in stage.plans()}
    taxi = plans["taxi"]
    assert [(d.hedge_id, d.amount, d.pending) for d in taxi.deposits] == [
        ("hdg_s01", D("59.11"), False), ("hdg_s03", D("45.00"), True)]
    assert [(d.hedge_id, d.pending) for d in plans["restaurant"].deposits] == [("hdg_r01", False)]

    fake = FakeIncrease()
    c = client(fake)
    first = stage.stage(c, taxi, now=NOW)
    n_inbound, n_ach = len(fake.inbound), len(fake.ach)
    assert (n_inbound, n_ach) == (3, 1)  # owner capital + two deposits; the opening transfer out
    fee_short = next(t for t in fake.inbound if t["amount"] == 5911)
    assert fee_short["addenda"]["freeform"]["entries"][0]["payment_related_information"] == "Kalshi withdrawal hdg_s01"
    pending = next(t for t in fake.inbound if t["amount"] == 4500)
    assert pending["resolve_at"] == "2026-10-26T19:00:00Z"  # T+2: in transit
    assert fake.ach[0]["amount"] == 50000 and "opening_deposit" in fake.ach[0]["statement_descriptor"]
    assert all(c.headers.get("Idempotency-Key", "").startswith("hedge-desk-demo-v1-taxi")
               for c in fake.calls if c.method == "POST" and "/simulations/ach_transfers/" not in c.url.path)

    later = datetime(2026, 10, 25, 9, 0, tzinfo=UTC)  # re-run a day later: resolve_at differs -> 409, skipped
    second = stage.stage(c, taxi, now=later)
    assert second == first and len(fake.accounts) == 1 and len(fake.numbers) == 1
    assert (len(fake.inbound), len(fake.ach)) == (n_inbound, n_ach)  # nothing moved twice
    assert "exists" in capsys.readouterr().out


def test_stage_script_without_references():
    from scripts import stage_increase_sandbox as stage

    fake = FakeIncrease()
    stage.stage(client(fake), stage.plans(["taxi"])[0], references=False, now=NOW)
    deposits = [t for t in fake.inbound if t.get("company_name") == "KALSHI"]
    assert deposits and all("addenda" not in t for t in deposits)
