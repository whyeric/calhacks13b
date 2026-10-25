"""Three-way reconciliation: venue vs ledger vs bank on the seeded demo books, each mismatch naming
the source of record; timing (in transit) vs error (missing); origin labels (I6)."""

from datetime import date
from decimal import Decimal

import pytest

from app.books.reconcile import _paid_twice, reconcile
from app.books.seed import seed_books
from app.books.sources import BankRow, CsvBankSource, SimulatedVenueSource, VenueSettlement

D = Decimal


@pytest.fixture
def seeded(engine, ledger_dir, tmp_path):
    out = tmp_path / "out"
    out.mkdir()
    seed_books(engine, ledger_dir=ledger_dir, out_dir=out)
    return out


def run(engine, seeded, *, csv="bank_statement_clean.csv", venue=None, bank=None):
    return reconcile("taxi", engine=engine, log=False, venue=venue,
                     bank=bank or CsvBankSource(seeded / csv))


def test_clean_three_way_match_carries_every_leg(engine, seeded):
    r = run(engine, seeded)
    assert r.mismatches == [] and r.in_transit == []
    s03 = next(m for m in r.matches if m.hedge_id == "hdg_s03")
    assert (s03.venue, s03.kalshi_ledger, s03.bank) == (D("45.00"),) * 3
    assert (s03.venue_origin, s03.bank_origin) == ("simulated", "csv_simulated")
    assert r.simulated is True and r.sources.live is False


def test_venue_paid_less_than_we_booked(engine, seeded):
    venue = SimulatedVenueSource(engine, {"hdg_s03": {"revenue": D("43.00")}})
    [m] = run(engine, seeded, venue=venue).mismatches
    assert (m.hedge_id, m.likely_cause, m.source_pair) == ("hdg_s03", "venue_paid_differs_from_booked", "venue_vs_kalshi_ledger")
    assert m.difference == D("2.00") and m.system_of_record == "venue"
    assert "Kalshi paid $43.00" in m.explanation and "we booked $45.00" in m.explanation
    assert m.record_reason.startswith("The venue is the record for what was paid")


def test_venue_fee_differs_from_booked_fee(engine, seeded):
    venue = SimulatedVenueSource(engine, {"hdg_s03": {"fee": D("1.50")}})
    [m] = run(engine, seeded, venue=venue).mismatches
    assert (m.likely_cause, m.source_pair, m.system_of_record) == ("fee_differs_from_venue", "ledger_fee_vs_venue_fee", "venue")
    assert m.difference == m.venue_fee - m.ledger_fee == D("1.50") - m.ledger_fee


def test_venue_has_no_record_and_venue_record_we_never_booked(engine, seeded):
    class Venue:
        origin = "kalshi_demo"

        def settlements(self, business_id):
            real = SimulatedVenueSource(engine).settlements(business_id)
            keep = [v.model_copy(update={"origin": "kalshi_demo"}) for v in real if v.hedge_id != "hdg_s03"]
            stray = VenueSettlement(hedge_id=None, ticker="KXHIGHNY-26OCT30-T60", settled_on=date(2026, 10, 30),
                                    revenue=D("12.00"), external_id="kalshi_settle_99", origin="kalshi_demo")
            return keep + [stray]

    r = run(engine, seeded, venue=Venue())
    causes = {m.hedge_id: m.likely_cause for m in r.mismatches}
    assert causes == {"hdg_s03": "venue_record_missing", "kalshi_settle_99": "unbooked_venue_settlement"}
    assert all(m.system_of_record == "venue" for m in r.mismatches)
    assert r.sources.venue_origin == "kalshi_demo" and r.simulated is True


def test_deposit_in_transit_then_missing(engine, seeded, tmp_path):
    text = (seeded / "bank_statement_clean.csv").read_text()
    lines = [ln for ln in text.splitlines() if ",hdg_s03," not in ln]
    csv = tmp_path / "no_s03.csv"
    csv.write_text("\n".join(lines) + "\n")
    r = reconcile("taxi", engine=engine, log=False, bank=CsvBankSource(csv))
    [t] = r.in_transit
    assert t.hedge_id == "hdg_s03" and t.days_outstanding <= t.window_days and r.mismatches == []
    assert "timing difference, not an error" in t.explanation.lower()

    # The statement runs on to Oct 30 and the deposit still isn't there: now it's missing.
    csv.write_text(csv.read_text() + "2026-10-30,SIMULATED card refund,3.10,USD,REF-1,true\n")
    r = reconcile("taxi", engine=engine, log=False, bank=CsvBankSource(csv))
    assert r.in_transit == []
    causes = {m.hedge_id: m.likely_cause for m in r.mismatches}
    assert causes == {"hdg_s03": "missing_deposit", "REF-1": "unexplained_bank_row"}


def test_pending_deposit_is_in_transit_however_old(engine, seeded):
    rows = CsvBankSource(seeded / "bank_statement_clean.csv").rows("taxi")
    rows = [r.model_copy(update={"status": "pending"}) if r.reference == "hdg_s03" else r for r in rows]
    rows.append(BankRow(date=date(2026, 11, 20), amount=D("1.00"), description="interest", reference="opening_balance",
                        origin="csv_simulated"))

    class Bank:
        origin = "csv_simulated"

        def rows(self, business_id):
            return rows

    r = run(engine, seeded, bank=Bank())
    [t] = r.in_transit
    assert t.hedge_id == "hdg_s03" and t.bank_pending == D("45.00") and t.days_outstanding > t.window_days


def test_unreferenced_deposit_net_of_fee_is_matched_and_explained(engine, seeded, tmp_path):
    text = (seeded / "bank_statement.csv").read_text().replace(",hdg_s01,", ",ACH-778,")
    csv = tmp_path / "noref_fee.csv"
    csv.write_text(text)
    [m] = reconcile("taxi", engine=engine, log=False, bank=CsvBankSource(csv)).mismatches
    assert (m.hedge_id, m.likely_cause, m.difference) == ("hdg_s01", "fee_deducted_from_deposit", D("-0.89"))
    assert "The bank is the record for cash, so the $0.89 is real" in m.explanation


def test_simulated_unless_every_leg_is_live(engine, seeded):
    class LiveVenue:
        origin = "kalshi_live"

        def settlements(self, business_id):
            return [v.model_copy(update={"origin": "kalshi_live"}) for v in SimulatedVenueSource(engine).settlements(business_id)]

    class LiveBank:
        origin = "increase_live"

        def rows(self, business_id):
            return [r.model_copy(update={"origin": "increase_live"})
                    for r in CsvBankSource(seeded / "bank_statement_clean.csv").rows(business_id)]

    r = run(engine, seeded, venue=LiveVenue(), bank=LiveBank())
    # Venue and bank are live, but the settlement entries in our books are still simulated.
    assert r.sources.ledger_origin == "beancount_simulated" and r.simulated is True and not r.sources.live


def test_paid_twice():
    assert _paid_twice(D("64"), [D("64"), D("30"), D("34")])
    assert _paid_twice(D("40"), [D("40"), D("40")])
    assert not _paid_twice(D("64"), [D("30"), D("34")])  # a split deposit, paid once
    assert not _paid_twice(D("64"), [D("100"), D("28")])  # sums to 2x but no part is the payout
