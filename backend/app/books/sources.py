"""Where reconciliation reads its outside records from (spec §9, three-way reconciliation).

Three independent records of a settled hedge, each with its own system of record:
  venue  - what the exchange says it paid (Kalshi demo/live portfolio settlements, else the
           simulated settlement derived from the real market result, R11)
  ledger - what we booked (Beancount, `app.books.ledger`; QuickBooks mirrors it)
  bank   - what cash actually arrived (Increase sandbox/live, else the simulated CSV)

`reconcile.py` reads venue and bank through these protocols so a real source can replace a
simulated one without touching the matching logic. Every row says where it came from, and
anything not from a live system is labeled simulated (I6).
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict
from sqlalchemy.engine import Engine

from app.config import FIXTURES_DIR

CENT = Decimal("0.01")

BankOrigin = Literal["csv_simulated", "increase_sandbox", "increase_live"]
VenueOrigin = Literal["simulated", "kalshi_demo", "kalshi_live"]


class BankRow(BaseModel):
    """One posted bank transaction. Positive = money into the operating account."""

    model_config = ConfigDict(frozen=True)

    date: date
    amount: Decimal
    description: str
    reference: str | None = None  # hedge id, "opening_deposit", or None when the bank dropped it
    external_id: str | None = None  # the bank's transaction id (Increase `transaction_...`)
    origin: BankOrigin
    # "pending": the bank has seen it but not posted it (an Increase inbound ACH awaiting
    # settlement). Reconciliation treats a pending deposit as in transit, not as cash received.
    status: Literal["posted", "pending"] = "posted"

    @property
    def simulated(self) -> bool:
        return self.origin != "increase_live"


class VenueSettlement(BaseModel):
    """What the venue reports it paid out for one hedge's position."""

    model_config = ConfigDict(frozen=True)

    hedge_id: str | None  # None when the venue position can't be tied to a hedge
    ticker: str
    settled_on: date
    revenue: Decimal  # gross paid by the venue, >= 0
    fee: Decimal = Decimal("0.00")
    external_id: str | None = None  # the venue's settlement / order id
    origin: VenueOrigin

    @property
    def simulated(self) -> bool:
        return self.origin != "kalshi_live"


class SourceUnavailable(RuntimeError):
    """A live source couldn't be read (network, auth, offline). Reconcile falls back to the
    simulated source for that leg and says so in `ReconResult.sources.notes`."""


class BankSource(Protocol):
    origin: BankOrigin

    def rows(self, business_id: str) -> list[BankRow]: ...


class VenueSource(Protocol):
    origin: VenueOrigin

    def settlements(self, business_id: str) -> list[VenueSettlement]: ...


# --- Simulated sources ---------------------------------------------------------------
# The default legs until a live venue/bank is configured. Both are labeled simulated (I6).


class CsvBankSource:
    """The simulated bank statement CSV written by `settlement.generate_bank_statement`
    (`fixtures/bank_statement*.csv`). Its rows carry our hedge id as `reference`, which a real
    bank wouldn't; reconcile still falls back to amount/date matching when a reference is unknown.
    An optional `status` column marks a row `pending` (the benchmark uses it); the default is posted."""

    origin: BankOrigin = "csv_simulated"

    def __init__(self, path: Path | None = None):
        self.path = path

    def rows(self, business_id: str) -> list[BankRow]:
        from app.books.settlement import read_bank_statement

        path = self.path or statement_path(business_id)
        if not path.exists():
            return []
        return [
            BankRow(
                date=date.fromisoformat(r["date"]),
                amount=Decimal(r["amount"]).quantize(CENT),
                description=r["description"],
                reference=(r.get("reference") or None),
                origin=self.origin,
                status="pending" if (r.get("status") or "").strip() == "pending" else "posted",
            )
            for r in read_bank_statement(path)
        ]


class SimulatedVenueSource:
    """What the venue paid, derived from the simulated settlement log events (R11: the hedge wins
    iff the real market `result` equals its side; payout = n_filled x $1.00). `overrides` lets the
    benchmark plant a venue record that disagrees with our books: {hedge_id: {"revenue"|"fee": Decimal}}."""

    origin: VenueOrigin = "simulated"

    def __init__(self, engine: Engine | None = None, overrides: dict[str, dict[str, Decimal]] | None = None):
        self.engine = engine
        self.overrides = overrides or {}

    def settlements(self, business_id: str) -> list[VenueSettlement]:
        from app import db

        out: dict[str, VenueSettlement] = {}
        for log in db.list_log(business_id, engine=self.engine):
            if log.kind not in ("settlement", "expired") or not log.hedge_id:
                continue
            n = log.numbers
            won = n.get("result") == n.get("side")
            revenue = Decimal(str(n.get("n_filled", 0))).quantize(CENT) if won else Decimal("0.00")
            o = self.overrides.get(log.hedge_id, {})
            out[log.hedge_id] = VenueSettlement(
                hedge_id=log.hedge_id,
                ticker=str(n.get("ticker", "")),
                settled_on=date.fromisoformat(str(n.get("settled_on"))[:10]),
                revenue=Decimal(o.get("revenue", revenue)).quantize(CENT),
                fee=Decimal(o.get("fee", Decimal(str(n.get("fee", "0"))))).quantize(CENT),
                external_id=f"sim_settle_{log.hedge_id}",
                origin=self.origin,
            )
        return [out[h] for h in sorted(out)]


def statement_path(business_id: str) -> Path:
    """Taxi carries the planted mismatch in `fixtures/bank_statement.csv`; others are clean."""
    if business_id == "taxi":
        return FIXTURES_DIR / "bank_statement.csv"
    return FIXTURES_DIR / f"bank_statement_{business_id}.csv"


class KalshiDemoVenueSource:
    """Kalshi's demo portfolio for hedges the owner's approval actually ordered there
    (`Hedge.venue_order` with an order id), the simulated settlement for every other hedge.
    A hedge with a demo order is never back-filled from the simulation: if Kalshi has no
    settlement for it, reconciliation reports the venue record missing. Each row keeps its own
    origin, so the UI labels demo and simulated rows separately (I6)."""

    origin: VenueOrigin = "kalshi_demo"

    def __init__(self, engine: Engine | None = None):
        self.engine = engine

    def settlements(self, business_id: str) -> list[VenueSettlement]:
        from app import db
        from app.markets.trading import KalshiVenueSource, TradingError

        try:
            demo = KalshiVenueSource().settlements(business_id)
        except TradingError as e:
            raise SourceUnavailable(str(e)) from e
        ordered = {h.id for h in db.list_hedges(business_id, engine=self.engine)
                   if h.venue_order is not None and h.venue_order.order_id}
        simulated = [s for s in SimulatedVenueSource(self.engine).settlements(business_id) if s.hedge_id not in ordered]
        return demo + simulated


def get_venue_source(business_id: str, engine: Engine | None = None) -> VenueSource:
    """The venue leg for `business_id`: Kalshi's demo portfolio when demo trading is on (see
    `markets/trading.trading_off_reason`), else the simulated settlement."""
    from app.markets.trading import trading_off_reason

    if trading_off_reason() is None:
        return KalshiDemoVenueSource(engine)
    return SimulatedVenueSource(engine)
