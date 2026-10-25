"""Regenerate the demo books offline and deterministically (C5, `make seed`).

Stand-in hedges (`fixtures/books/sim_hedges.json`) on recent, REAL settled Kalshi markets
(`fixtures/books/settled_markets.json`, pulled from the public API) are approved by the
owner, booked, settled (simulated) and withdrawn to the bank (simulated). Then the
simulated bank statements are written:

    fixtures/bank_statement.csv             taxi, with the ONE planted mismatch
    fixtures/bank_statement_clean.csv       taxi, no plant (test-only)
    fixtures/bank_statement_restaurant.csv  restaurant, clean

ANSWER KEY: on taxi, hdg_s01 (KXHIGHNY-26OCT20-T72, NO x 60) pays $60.00 but the bank
deposit is $59.11, short by exactly its $0.89 entry fee. `reconcile("taxi")` must flag
that one row with difference -0.89 and likely_cause fee_deducted_from_deposit.

CLI: `python -m app.books.seed` (from backend/).
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime, timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from sqlalchemy.engine import Engine

from app import db
from app.books import ledger
from app.books.settlement import SettlementRecord, book_settlement, book_withdrawal, generate_bank_statement
from app.books.settlement import simulate_settlement
from app.config import FIXTURES_DIR
from app.models import Hedge

BOOKS_FIXTURES = FIXTURES_DIR / "books"
OPENING_DATE = date(2026, 10, 12)
PLANT = {"taxi": "hdg_s01"}  # the answer key; restaurant stays clean (ACCEPTANCE gap 8)


def build_hedge(spec: dict[str, Any]) -> Hedge:
    """A proposed Hedge from a compact stand-in spec; fee by the Kalshi formula."""
    data = json.loads((FIXTURES_DIR / "examples" / "hedge_proposed.json").read_text())
    n, price = int(spec["n"]), Decimal(spec["price"])
    cost = (price * n).quantize(ledger.CENT)
    fee = ledger.taker_fee(n, price)
    approved_at = datetime.fromisoformat(spec["approved_at"].replace("Z", "+00:00"))
    day = ledger.ny_date(approved_at)
    data.update(
        id=spec["id"], business_id=spec["business_id"], exposure_id=f"exp_{spec['business_id']}_sim",
        week_of=(day - timedelta(days=day.weekday())).isoformat(), status="proposed",
        ticker=spec["ticker"], market_title=None, market_url=None, close_time=None, side=spec["side"],
        match_reason="Simulated stand-in on a settled market (books demo).",
        n_target=n, n_filled=n, n_unfilled=0, partial=False, resized=False,
        fills=[{"price": spec["price"], "count": n}], avg_price=spec["price"],
        cost=str(cost), fee=str(fee), premium=str(cost + fee), fair=None, expected_cost=None,
        payoff=None, headline=None, alternative=None, created_at=spec["approved_at"],
    )
    data["decision"] = {
        "id": f"dec_{spec['id'][4:]}", "status": "proposed", "checks": [], "reasons": [],
        "summary": "Simulated stand-in hedge for the books demo.",
    }
    return Hedge.model_validate(data)


def seed_books(
    engine: Engine | None = None,
    *,
    ledger_dir: Path | None = None,
    out_dir: Path = FIXTURES_DIR,
    fixtures: Path = BOOKS_FIXTURES,
) -> dict[str, list[SettlementRecord]]:
    db.create_schema(engine)
    markets = {m["ticker"]: m for m in json.loads((fixtures / "settled_markets.json").read_text())}
    specs = json.loads((fixtures / "sim_hedges.json").read_text())
    by_business: dict[str, list[SettlementRecord]] = {}
    for spec in specs:
        ledger.ensure_opening_deposit(spec["business_id"], OPENING_DATE, engine)
    for spec in specs:
        hedge = build_hedge(spec)
        existing = db.get_hedge(hedge.id, engine)
        if existing is not None and existing.status in ("approved", "settled"):
            approved = existing
        else:
            at = datetime.fromisoformat(spec["approved_at"].replace("Z", "+00:00"))
            approved, _ = ledger.approve_hedge(
                hedge, "owner", at=at, engine=engine, ledger_dir=ledger_dir, simulated=True
            )
        market = markets[hedge.ticker]
        entries = book_settlement(approved, market, engine=engine, ledger_dir=ledger_dir)
        rec = simulate_settlement(approved, market)
        if rec.won:
            book_withdrawal(approved.business_id, rec.payout, rec.settled_on, [approved.id],
                            engine=engine, ledger_dir=ledger_dir)
        ids = [ledger.premium_entry_id(approved.id)] + [e.id for e in entries]
        db.put_hedge(approved.model_copy(update={"status": "settled", "ledger_entry_ids": ids}), engine)
        by_business.setdefault(approved.business_id, []).append(rec)

    for business_id, recs in sorted(by_business.items()):
        plant = PLANT.get(business_id)
        name = "bank_statement.csv" if business_id == "taxi" else f"bank_statement_{business_id}.csv"
        _write(out_dir / name, generate_bank_statement(business_id, recs, plant_hedge_id=plant, engine=engine))
        if plant:
            _write(out_dir / "bank_statement_clean.csv", generate_bank_statement(business_id, recs, engine=engine))
        ledger.write_ledger(business_id, engine=engine, ledger_dir=ledger_dir)
    return by_business


def _write(path: Path, text: str) -> None:
    if not path.exists() or path.read_text() != text:
        path.write_text(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="python -m app.books.seed")
    parser.add_argument("--url", help="database URL (default: DATABASE_URL)")
    args = parser.parse_args(argv)
    engine = db.make_engine(args.url) if args.url else db.get_engine()
    out = seed_books(engine)
    print("books seeded: " + ", ".join(f"{b}={len(r)} settlements" for b, r in out.items()))
    return 0


if __name__ == "__main__":
    sys.exit(main())
