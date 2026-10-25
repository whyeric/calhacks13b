"""Which venue leg reconciliation reads: Kalshi demo when demo trading is on, else simulated.
With demo trading on, hedges that were really ordered on demo come from Kalshi only; the rest
keep their simulated settlement, each row labeled by its own origin (I6)."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app import db
from app.books import sources
from app.books.sources import KalshiDemoVenueSource, SimulatedVenueSource, SourceUnavailable, VenueSettlement
from app.markets import trading


def _vs(hid: str | None, origin: str, revenue: str = "60.00") -> VenueSettlement:
    return VenueSettlement(hedge_id=hid, ticker="KXRAINNYC-T", settled_on=date(2026, 10, 20),
                           revenue=Decimal(revenue), origin=origin)


def _hedge(hid: str, order_id: str | None):
    return SimpleNamespace(id=hid, venue_order=SimpleNamespace(order_id=order_id) if order_id else None)


def test_selector_follows_trading_switch(monkeypatch):
    monkeypatch.setattr(trading, "trading_off_reason", lambda s=None: "KALSHI_TRADING_ENABLED is off")
    assert isinstance(sources.get_venue_source("taxi"), SimulatedVenueSource)
    monkeypatch.setattr(trading, "trading_off_reason", lambda s=None: None)
    assert isinstance(sources.get_venue_source("taxi"), KalshiDemoVenueSource)


def test_demo_rows_replace_simulated_only_for_ordered_hedges(monkeypatch):
    monkeypatch.setattr(trading.KalshiVenueSource, "settlements",
                        lambda self, b: [_vs("hdg_a", "kalshi_demo", "58.00"), _vs(None, "kalshi_demo")])
    monkeypatch.setattr(SimulatedVenueSource, "settlements",
                        lambda self, b: [_vs("hdg_a", "simulated"), _vs("hdg_b", "simulated"),
                                         _vs("hdg_c", "simulated")])
    # hdg_a and hdg_c were ordered on demo; Kalshi has settled only hdg_a.
    monkeypatch.setattr(db, "list_hedges", lambda business_id=None, engine=None, **_: [
        _hedge("hdg_a", "ord_1"), _hedge("hdg_b", None), _hedge("hdg_c", "ord_3")])
    rows = KalshiDemoVenueSource().settlements("taxi")
    got = sorted((r.hedge_id or "-", r.origin, str(r.revenue)) for r in rows)
    assert got == [("-", "kalshi_demo", "60.00"), ("hdg_a", "kalshi_demo", "58.00"),
                   ("hdg_b", "simulated", "60.00")]  # hdg_c: never back-filled from the simulation


def test_kalshi_error_becomes_source_unavailable(monkeypatch):
    def boom(self, b):
        raise trading.TradingError("demo API down")

    monkeypatch.setattr(trading.KalshiVenueSource, "settlements", boom)
    with pytest.raises(SourceUnavailable):
        KalshiDemoVenueSource().settlements("taxi")
