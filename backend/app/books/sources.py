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
from typing import Literal, Protocol

from pydantic import BaseModel, ConfigDict

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


class BankSource(Protocol):
    origin: BankOrigin

    def rows(self, business_id: str) -> list[BankRow]: ...


class VenueSource(Protocol):
    origin: VenueOrigin

    def settlements(self, business_id: str) -> list[VenueSettlement]: ...
