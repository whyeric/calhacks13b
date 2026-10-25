"""QuickBooks write-back: ledger entries mirrored as balanced JournalEntries (demo store or a fake
live company), idempotent, never blocking a booking, logged (I5), and the drift check that catches
a bookkeeper's edit or delete. No network."""

from datetime import date
from decimal import Decimal

import pytest

from app import config, db
from app.books import ledger
from app.books.settlement import book_settlement, book_withdrawal
from app.integrations import quickbooks as qbo
from app.integrations import quickbooks_sync as sync
from app.models import LedgerEntry, LedgerMeta, Posting, QboSyncReport
from tests.api.conftest import app_env, client  # noqa: F401  (fixtures)

from .fake_qbo import FakeQbo
from .conftest import connect_live

META = LedgerMeta(hedge_id="hdg_01", ticker="KXHIGHNY-26OCT28-T65", decision_id="dec_01", approved_by="owner")


def entry(kind: str, postings: dict[str, str], *, simulated=False, eid=None) -> LedgerEntry:
    return LedgerEntry(id=eid or f"le_hdg_taxi_2026-10-26_rain_{kind}", business_id="taxi", date=date(2026, 10, 26),
                       kind=kind, narration=f"{kind} narration",
                       postings=[Posting(account=a, amount=Decimal(v)) for a, v in postings.items()],
                       meta=META if kind in ("premium", "payout") else None, simulated=simulated)


IDS = {ledger.PREMIUMS: "1", ledger.FEES: "2", ledger.CASH: "3", ledger.BANK: "4", ledger.PAYOUTS: "5"}


def sides(je) -> dict[str, Decimal]:
    out = {"Debit": Decimal("0"), "Credit": Decimal("0")}
    for ln in je["Line"]:
        out[ln["JournalEntryLineDetail"]["PostingType"]] += ln["Amount"]
    return out


@pytest.fixture(autouse=True)
def _reset():
    qbo.reset()
    sync._account_cache.clear()
    yield
    qbo.reset()
    sync._account_cache.clear()


# --- Mapping -------------------------------------------------------------------------


@pytest.mark.parametrize("kind,postings,debits", [
    ("premium", {ledger.PREMIUMS: "63.90", ledger.FEES: "2.57", ledger.CASH: "-66.47"},
     {("Debit", "1"): "63.90", ("Debit", "2"): "2.57", ("Credit", "3"): "66.47"}),
    ("payout", {ledger.CASH: "150.00", ledger.PAYOUTS: "-150.00"},
     {("Debit", "3"): "150.00", ("Credit", "5"): "150.00"}),
    ("withdrawal", {ledger.BANK: "148.95", ledger.CASH: "-148.95"},
     {("Debit", "4"): "148.95", ("Credit", "3"): "148.95"}),
    ("opening_deposit", {ledger.CASH: "500.00", ledger.BANK: "-500.00"},
     {("Debit", "3"): "500.00", ("Credit", "4"): "500.00"}),
])
def test_journal_entry_balances_to_the_cent(kind, postings, debits):
    e = entry(kind, postings, simulated=kind != "premium")
    je = sync.journal_entry(e, IDS)
    got = {(ln["JournalEntryLineDetail"]["PostingType"], ln["JournalEntryLineDetail"]["AccountRef"]["value"]):
           str(ln["Amount"]) for ln in je["Line"]}
    assert got == debits
    s = sides(je)
    assert s["Debit"] == s["Credit"] == sum(Decimal(v) for v in postings.values() if Decimal(v) > 0)
    assert all(isinstance(ln["Amount"], Decimal) and ln["Amount"] > 0 for ln in je["Line"])
    assert je["TxnDate"] == "2026-10-26" and len(je["DocNumber"]) <= 21
    assert e.id in je["PrivateNote"] and ("[SIMULATED]" in je["PrivateNote"]) == e.simulated
    if kind == "premium":
        assert "hdg_01" in je["PrivateNote"] and "dec_01" in je["PrivateNote"]
        assert "Posted by Hedge Desk on owner approval" in je["PrivateNote"]


def test_zero_fee_line_is_dropped_and_unmapped_account_refused():
    je = sync.journal_entry(entry("premium", {ledger.PREMIUMS: "10.00", ledger.FEES: "0.00", ledger.CASH: "-10.00"}),
                            IDS)
    assert len(je["Line"]) == 2
    with pytest.raises(sync.UnmappedAccount):
        sync.journal_entry(entry("premium", {"Expenses:Other": "1.00", ledger.CASH: "-1.00"}), IDS)


def test_doc_number_is_stable_and_fits():
    short, long_ = "le_hdg_01_premium", "le_hdg_taxi_2026-10-26_rain_premium"
    assert sync.doc_number(short) == short
    d = sync.doc_number(long_)
    assert len(d) == 21 and d == sync.doc_number(long_) and d.startswith("le_hdg_taxi_")
    assert d != sync.doc_number(long_.replace("premium", "payout"))


def test_account_mapping_types():
    m = sync.account_map()
    assert (m[ledger.CASH].account_type, m[ledger.CASH].sub_type) == ("Other Current Asset", "OtherCurrentAssets")
    assert m[ledger.PREMIUMS].account_type == m[ledger.FEES].account_type == "Other Expense"
    assert (m[ledger.PAYOUTS].account_type, m[ledger.PAYOUTS].sub_type) == ("Other Income", "OtherMiscellaneousIncome")
    assert (m[ledger.BANK].name, m[ledger.BANK].account_type) == ("Checking", "Bank")
    assert set(m) >= set(ledger.ACCOUNTS)  # every account the desk books has a home in QuickBooks


# --- Demo mode, through the API ----------------------------------------------------------


def approve(client, hid="hdg_01"):  # noqa: F811
    r = client.post(f"/hedges/{hid}/approve", json={"actor": "owner"})
    assert r.status_code == 200, r.text
    return r.json()


def test_not_connected_mirrors_nothing(client):  # noqa: F811
    approve(client)
    assert db.list_qbo_demo_objects("JournalEntry") == []
    assert not [e for e in db.list_log("taxi") if e.kind.startswith("qbo_")]
    r = client.get("/integrations/quickbooks/sync", params={"business_id": "taxi"})
    assert r.status_code == 409 and r.json()["error"]["code"] == "not_connected"


def test_demo_approval_posts_journal_entries(client):  # noqa: F811
    client.post("/integrations/quickbooks/connect")
    h = approve(client)
    jes = db.list_qbo_demo_objects("JournalEntry")
    entries = db.list_ledger_entries("taxi")
    assert {e.kind for e in entries} == {"opening_deposit", "premium"}
    assert len(jes) == 2 and all(je["synthetic"] for je in jes)  # opening deposit first, then the premium
    premium = next(je for je in jes if je["DocNumber"] == sync.doc_number(ledger.premium_entry_id(h["id"])))
    assert premium["TotalAmt"] == h["premium"]
    assert {a["Name"] for a in db.list_qbo_demo_objects("Account")} == {
        "Hedging Premiums", "Hedging Fees", "Kalshi Cash", "Checking"}

    logs = [e for e in db.list_log("taxi") if e.kind == "qbo_posted"]
    assert len(logs) == 2 and all("SYNTHETIC demo QuickBooks store" in e.summary for e in logs)
    trail = [e.kind for e in db.list_log("taxi", hedge_id=h["id"])]
    assert trail[-1] == "qbo_posted" and trail.index("booking") < trail.index("qbo_posted")  # logged after it
    assert "qbo_posted" in [e["kind"] for e in client.get("/businesses/taxi/decisions").json()]

    r = client.get("/integrations/quickbooks/sync", params={"business_id": "taxi"})
    assert r.status_code == 200, r.text
    rep = QboSyncReport.model_validate(r.json())
    assert rep.synthetic and rep.mode == "demo" and rep.system_of_record == "beancount"
    assert [ln.status for ln in rep.lines] == ["posted", "posted"]
    assert rep.counts["posted"] == 2 and isinstance(r.json()["lines"][0]["amount"], str)
    assert all(ln.qbo_amount == ln.amount for ln in rep.lines)


def test_drift_missing_and_amount_differs(client):  # noqa: F811
    client.post("/integrations/quickbooks/connect")
    h = approve(client)
    books = sync.DemoBooks()
    jes = {je["DocNumber"]: je for je in db.list_qbo_demo_objects("JournalEntry")}
    prem = jes[sync.doc_number(ledger.premium_entry_id(h["id"]))]
    opening = jes[sync.doc_number(ledger.opening_entry_id("taxi"))]

    # A bookkeeper "fixes" the premium down by $1 on both sides, and deletes the opening deposit.
    for ln in prem["Line"]:
        ln["Amount"] = str(Decimal(ln["Amount"]) - Decimal("1.00")) if ln["JournalEntryLineDetail"]["PostingType"] \
            == "Credit" else ln["Amount"]
    first_debit = next(ln for ln in prem["Line"] if ln["JournalEntryLineDetail"]["PostingType"] == "Debit")
    first_debit["Amount"] = str(Decimal(first_debit["Amount"]) - Decimal("1.00"))
    books.edit("JournalEntry", prem["Id"], prem)
    books.delete("JournalEntry", opening["Id"])

    rep = QboSyncReport.model_validate(client.get("/integrations/quickbooks/sync",
                                                  params={"business_id": "taxi"}).json())
    by_kind = {ln.kind: ln for ln in rep.lines}
    assert by_kind["opening_deposit"].status == "missing" and by_kind["opening_deposit"].qbo_amount is None
    p = by_kind["premium"]
    assert p.status == "amount_differs" and p.qbo_amount == p.amount - Decimal("1.00")
    assert f"ledger ${p.amount}" in p.detail and "The ledger is right" in p.detail
    assert rep.counts == {"posted": 0, "missing": 1, "amount_differs": 1, "failed": 0, "not_posted": 0}
    assert "system of record" in rep.explanation
    # read-only: the ledger is untouched and nothing was re-posted
    assert len(db.list_qbo_demo_objects("JournalEntry")) == 1
    assert {e.kind for e in db.list_ledger_entries("taxi")} == {"opening_deposit", "premium"}


def test_entries_booked_before_connecting_are_not_posted_then_caught_up(client):  # noqa: F811
    approve(client)
    client.post("/integrations/quickbooks/connect")
    rep = client.get("/integrations/quickbooks/sync", params={"business_id": "taxi"}).json()
    assert [ln["status"] for ln in rep["lines"]] == ["not_posted", "not_posted"]
    assert client.post("/hedges/hdg_02/cosign", json={"actor": "controller"}).status_code == 200
    approve(client, "hdg_02")  # the next booking mirrors the backlog too
    rep = client.get("/integrations/quickbooks/sync", params={"business_id": "taxi"}).json()
    assert [ln["status"] for ln in rep["lines"]] == ["posted"] * 3


def test_sync_unknown_business_404(client):  # noqa: F811
    r = client.get("/integrations/quickbooks/sync", params={"business_id": "nope"})
    assert r.status_code == 404 and r.json()["error"]["code"] == "business_not_found"


def test_mirror_is_idempotent(client):  # noqa: F811
    client.post("/integrations/quickbooks/connect")
    approve(client)
    entries = db.list_ledger_entries("taxi")
    again = sync.mirror_entries("taxi", entries)
    assert [r.detail for r in again] == ["already posted"] * 2
    assert len(db.list_qbo_demo_objects("JournalEntry")) == 2
    # Lost our record (e.g. a restored DB)? The DocNumber finds the existing JE: still no duplicate.
    with db.session() as s:
        for row in s.exec(db.select(db.QboMirrorRow)).all():
            s.delete(row)
    again = sync.mirror_entries("taxi", entries)
    assert [r.detail for r in again] == ["found the existing"] * 2
    assert len(db.list_qbo_demo_objects("JournalEntry")) == 2


def test_settlement_and_withdrawal_are_mirrored(client):  # noqa: F811
    client.post("/integrations/quickbooks/connect")
    h = approve(client)
    hedge = db.get_hedge(h["id"])
    market = {"ticker": hedge.ticker, "result": hedge.side, "settlement_ts": "2026-10-29T11:00:00Z"}
    book_settlement(hedge, market)
    book_withdrawal("taxi", Decimal(hedge.n_filled), date(2026, 10, 30), [hedge.id])
    jes = db.list_qbo_demo_objects("JournalEntry")
    assert len(jes) == 4
    payout = next(je for je in jes if je["DocNumber"] == sync.doc_number(ledger.payout_entry_id(hedge.id)))
    assert "[SIMULATED]" in payout["PrivateNote"] and "on settlement" in payout["PrivateNote"]
    assert Decimal(payout["TotalAmt"]) == Decimal(hedge.n_filled)
    assert {a["Name"] for a in db.list_qbo_demo_objects("Account")} >= {"Hedging Payouts", "Checking"}
    rep = client.get("/integrations/quickbooks/sync", params={"business_id": "taxi"}).json()
    assert rep["counts"]["posted"] == 4


# --- Live mode (FakeQbo) ---------------------------------------------------------------


@pytest.fixture
def live(client, monkeypatch):  # noqa: F811
    for k, v in {"QBO_CLIENT_ID": "cid", "QBO_CLIENT_SECRET": "csecret", "DEMO_OFFLINE": "0",
                 "QBO_ENVIRONMENT": "sandbox"}.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()
    qbo.reset()
    fake = FakeQbo()
    connect_live(fake, monkeypatch, config.get_settings())
    return fake


def test_live_approval_posts_to_quickbooks(client, live):  # noqa: F811
    h = approve(client)
    jes = live.creates("JournalEntry")
    assert len(jes) == 2
    prem = next(je for je in jes if je["DocNumber"] == sync.doc_number(ledger.premium_entry_id(h["id"])))
    assert prem["TotalAmt"] == Decimal(h["premium"])
    accounts = {a["Name"]: a for a in live.creates("Account")}
    assert (accounts["Kalshi Cash"]["AccountType"], accounts["Hedging Premiums"]["AccountType"]) == \
        ("Other Current Asset", "Other Expense")
    rep = client.get("/integrations/quickbooks/sync", params={"business_id": "taxi"}).json()
    assert rep["synthetic"] is False and rep["mode"] == "live" and rep["counts"]["posted"] == 2

    # The bookkeeper deletes the premium JE in QuickBooks: caught.
    live.tables["JournalEntry"] = [je for je in jes if je is not prem]
    rep = client.get("/integrations/quickbooks/sync", params={"business_id": "taxi"}).json()
    assert {ln["kind"]: ln["status"] for ln in rep["lines"]} == {"opening_deposit": "posted", "premium": "missing"}


def test_quickbooks_failure_never_blocks_approval(client, live):  # noqa: F811
    live.fail_create["JournalEntry"] = 503
    h = approve(client)  # 200 all the same
    assert h["status"] == "approved" and h["ledger_entry_ids"]
    assert {e.kind for e in db.list_ledger_entries("taxi")} == {"opening_deposit", "premium"}  # booked
    failed = [e for e in db.list_log("taxi") if e.kind == "qbo_post_failed"]
    assert len(failed) == 2 and "The booking stands" in failed[0].summary and "Service unavailable" in failed[0].summary
    rep = client.get("/integrations/quickbooks/sync", params={"business_id": "taxi"}).json()
    assert [ln["status"] for ln in rep["lines"]] == ["failed", "failed"]

    # QuickBooks is back: the next mirror posts the backlog, once.
    live.fail_create.clear()
    results = sync.mirror_entries("taxi")
    assert [r.status for r in results] == ["posted", "posted"]
    assert len(live.creates("JournalEntry")) == 2
    assert [e.kind for e in db.list_log("taxi") if e.kind.startswith("qbo_")].count("qbo_posted") == 2


def test_mirror_crash_never_blocks_approval(client, monkeypatch):  # noqa: F811
    client.post("/integrations/quickbooks/connect")

    def boom(conn):
        raise RuntimeError("mirror exploded")

    monkeypatch.setattr(sync, "books_for", boom)
    h = approve(client)
    assert h["status"] == "approved" and db.list_ledger_entries("taxi")


def test_unreachable_quickbooks_is_contained(client, live, monkeypatch):  # noqa: F811
    import httpx

    def down(request):
        raise httpx.ConnectError("down")

    monkeypatch.setattr(qbo, "TRANSPORT", httpx.MockTransport(down))
    assert approve(client)["status"] == "approved"
    assert [e.kind for e in db.list_log("taxi") if e.kind.startswith("qbo_")] == ["qbo_post_failed"] * 2
    r = client.get("/integrations/quickbooks/sync", params={"business_id": "taxi"})
    assert r.status_code == 200  # failed entries need no read-back
    assert [ln["status"] for ln in r.json()["lines"]] == ["failed", "failed"]


def test_production_skips_simulated_entries(client, monkeypatch):  # noqa: F811
    for k, v in {"QBO_CLIENT_ID": "cid", "QBO_CLIENT_SECRET": "csecret", "DEMO_OFFLINE": "0",
                 "QBO_ENVIRONMENT": "production"}.items():
        monkeypatch.setenv(k, v)
    config.get_settings.cache_clear()
    qbo.reset()
    fake = FakeQbo(host="quickbooks.api.intuit.com")
    connect_live(fake, monkeypatch, config.get_settings())
    approve(client)
    assert [je["DocNumber"] for je in fake.creates("JournalEntry")] == [sync.doc_number(ledger.premium_entry_id("hdg_01"))]
    rep = client.get("/integrations/quickbooks/sync", params={"business_id": "taxi"}).json()
    lines = {ln["kind"]: ln for ln in rep["lines"]}
    assert lines["premium"]["status"] == "posted"
    assert lines["opening_deposit"]["status"] == "not_posted" and "production" in lines["opening_deposit"]["detail"]


def test_mirror_off_switch(client, monkeypatch):  # noqa: F811
    monkeypatch.setenv("QBO_MIRROR_ENABLED", "0")
    config.get_settings.cache_clear()
    client.post("/integrations/quickbooks/connect")
    approve(client)
    assert db.list_qbo_demo_objects("JournalEntry") == []
