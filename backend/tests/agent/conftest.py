"""Agent test env: temp SQLite seeded from fixtures, no Anthropic key, fixture markets, the
example analysis, a pinned clock, and `mock_claude(script)` (scripted model turns)."""

import json
from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace

import pytest

from app import analysis, clock, config, db

NOW = datetime(2026, 10, 31, 19, 0, tzinfo=timezone.utc)  # Saturday; the desk week is Mon 2026-11-02
WEEK = date(2026, 11, 2)
EXAMPLES = Path(__file__).resolve().parents[2] / "fixtures" / "examples"
RAIN, HOT = "exp_rain", "exp_hot"


def example(name: str):
    return json.loads((EXAMPLES / name).read_text())


@pytest.fixture(autouse=True)
def env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'agent.db'}")
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_MODEL", "")
    monkeypatch.setenv("MARKETS_BACKEND", "fixture")
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()
    monkeypatch.setattr(clock, "now", lambda: NOW)
    from app.models import AnalyzeResponse

    res = AnalyzeResponse.model_validate(example("analyze_response.json"))
    monkeypatch.setattr(analysis, "compute", lambda business_id, strike=None: res)
    db.seed()
    from app.agent import desk

    desk._locks.clear()
    yield tmp_path
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()


def tool_use(name: str, args: dict, i: int = 0) -> dict:
    return {"type": "tool_use", "id": f"tu_{name}_{i}", "name": name, "input": args}


def text(t: str) -> dict:
    return {"type": "text", "text": t}


class MockClaude:
    """`messages.create` replays `script`: each item is a list of blocks, an exception to raise,
    or a callable(kwargs) returning either. Records every call's kwargs."""

    def __init__(self, script):
        self.script = list(script)
        self.calls = []
        self.messages = SimpleNamespace(create=self._create)

    def _create(self, **kw):
        self.calls.append(kw)
        item = self.script.pop(0) if self.script else [text("done")]
        if callable(item) and not isinstance(item, BaseException):
            item = item(kw)
        if isinstance(item, BaseException):
            raise item
        return SimpleNamespace(content=item)


@pytest.fixture
def mock_claude():
    return MockClaude


def last_tool_result(kw) -> dict:
    """The JSON output of the most recent tool call in a request's messages."""
    for m in reversed(kw["messages"]):
        if m["role"] == "user" and isinstance(m["content"], list):
            return json.loads(m["content"][-1]["content"])
    raise AssertionError("no tool result yet")


def happy_script(exposure_id: str, ticker: str, hedge_id: str, summary: str = None) -> list:
    """search -> match -> size -> evaluate -> log for one exposure (C4-A15 order)."""
    return [
        [tool_use("search_markets", {"business_id": "taxi", "exposure_id": exposure_id})],
        [text("Matching."), tool_use("match_market", {"exposure_id": exposure_id, "ticker": ticker,
                                                      "reason": "Same city and day as the exposure."})],
        [tool_use("size_hedge", {"exposure_id": exposure_id, "ticker": ticker})],
        [tool_use("evaluate_hedge", {"hedge_id": hedge_id})],
        lambda kw: [tool_use("log_decision", {"hedge_id": hedge_id, "summary": summary or (
            f"{last_tool_result(kw)['status'].replace('_', ' ').capitalize()}: the desk checked this market "
            "and explains it in plain words.")})],
        [text("Logged.")],
    ]


RAIN_TICKER, HOT_TICKER = "KXRAINNYC-26OCT28", "KXHIGHNY-26OCT28-T65"
RAIN_HID, HOT_HID = "hdg_taxi_20261102_rain", "hdg_taxi_20261102_hot"
