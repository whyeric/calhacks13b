"""C4-A11 (re-prompt on I2 rejection), C4-A14 (tool-call cap), C4-A15 (happy path), C4-A35 (idempotent)."""

import asyncio

from app import config, db
from app.agent import desk, log

from .conftest import (
    HOT, HOT_HID, HOT_TICKER, RAIN, RAIN_HID, RAIN_TICKER, WEEK, MockClaude, happy_script, text, tool_use,
)


def run(client, run_id):
    return asyncio.run(desk.run_week("taxi", WEEK, run_id=run_id, client=client, model="test-model"))


def entries(run_id):
    return [e for e in log.list("taxi") if e.run_id == run_id]


def test_A15_happy_path_order_and_every_hedge_logged():
    client = MockClaude(happy_script(RAIN, RAIN_TICKER, RAIN_HID) + happy_script(HOT, HOT_TICKER, HOT_HID))
    r = run(client, "run_a15")
    names = [t["name"] for t in r.trace]
    step = ["search_markets", "match_market", "size_hedge", "evaluate_hedge", "log_decision"]
    assert names == step + step
    assert r.agent == "claude" and r.summary.startswith("This week:")
    logged = {e.hedge_id for e in entries("run_a15")}
    assert {h.id for h in r.hedges} == logged == {RAIN_HID, HOT_HID}  # I5
    assert all(e.agent == "claude" and e.checks for e in entries("run_a15"))
    # Claude's model id comes from the caller/settings, and the system prompt is ours.
    assert all(c["model"] == "test-model" and c["system"].startswith("Rules:") for c in client.calls)


def test_A11_reprompt_once_then_fixed():
    bad = [tool_use("log_decision", {"hedge_id": RAIN_HID, "summary": "Waiting on you: it costs $500."})]
    good = [tool_use("log_decision", {"hedge_id": RAIN_HID, "summary": "Waiting on you: over this week's budget."})]
    script = happy_script(RAIN, RAIN_TICKER, RAIN_HID)[:4] + [bad, good]
    r = run(MockClaude(script + happy_script(HOT, HOT_TICKER, HOT_HID)), "run_a11")
    rejected = [t for t in r.trace if t["name"] == "log_decision" and t["output"].get("error")]
    assert rejected and rejected[0]["output"] == {"error": "unsupported_numbers", "offending": ["$500"]}
    rain = [e for e in entries("run_a11") if e.hedge_id == RAIN_HID]
    assert len(rain) == 1 and rain[0].summary == "Waiting on you: over this week's budget."
    assert rain[0].agent == "claude"


def test_A11_second_rejection_uses_template():
    bad = [tool_use("log_decision", {"hedge_id": RAIN_HID, "summary": "It costs $500."})]
    script = happy_script(RAIN, RAIN_TICKER, RAIN_HID)[:4] + [bad, bad]
    r = run(MockClaude(script + happy_script(HOT, HOT_TICKER, HOT_HID)), "run_a11b")
    rain = [e for e in entries("run_a11b") if e.hedge_id == RAIN_HID]
    assert len(rain) == 1 and rain[0].agent == "fallback" and "$500" not in rain[0].summary
    assert log.validate_summary(rain[0].summary, rain[0].numbers) == []
    assert r.agent == "fallback"


def test_A14_cap_twelve_calls():
    forever = lambda kw: [tool_use("check_budget", {"business_id": "taxi"}, len(kw["messages"]))]  # noqa: E731
    r = run(MockClaude([forever] * 100), "run_a14")
    cap = config.get_thresholds().max_tool_calls
    per = [t for t in r.trace if t["name"] == "check_budget"]
    assert len(per) == cap * 2  # one bounded turn per exposure, exactly 12 each
    assert r.capped == [RAIN, HOT]
    logged = entries("run_a14")
    assert len(logged) == 2 and all("tool-call limit" in e.summary for e in logged)
    assert all(e.agent == "fallback" for e in logged)


def test_A35_idempotent_same_week():
    r1 = asyncio.run(desk.run_week("taxi", WEEK, run_id="run_i1"))
    r2 = asyncio.run(desk.run_week("taxi", WEEK, run_id="run_i2"))
    assert set(r2.skipped_existing) == {RAIN, HOT} and entries("run_i2") == []
    hedges = db.list_hedges("taxi", WEEK)
    keys = [(h.exposure_id, h.ticker) for h in hedges if h.status in ("proposed", "pending_approval")]
    assert len(keys) == len(set(keys)) == 2
    assert {h.id for h in r1.hedges} == {h.id for h in r2.hedges}


def test_concurrent_run_returns_existing_run_id():
    from app.markets.port import FixtureMarkets

    class Slow(FixtureMarkets):
        async def candidates(self, exposure, now):
            await asyncio.sleep(0.01)
            return await super().candidates(exposure, now)

    async def both():
        a = asyncio.create_task(desk.run_week("taxi", WEEK, run_id="run_c1", markets=Slow()))
        await asyncio.sleep(0)
        b = await desk.run_week("taxi", WEEK, run_id="run_c2")
        return await a, b

    a, b = asyncio.run(both())
    assert b.already_running and b.run_id == "run_c1" and not a.already_running
