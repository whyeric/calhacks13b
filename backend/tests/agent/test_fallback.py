"""C4-A16 (timeout), C4-A17 (5xx/429, bounded retries, fake clock), C4-A18 (fallback mid-run),
plus the no-key fallback producing the same decisions as Claude."""

import asyncio

import anthropic
import httpx
import pytest

from app import db
from app.agent import desk, log

from .conftest import HOT, HOT_HID, RAIN, RAIN_HID, RAIN_TICKER, WEEK, MockClaude, happy_script

REQ = httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def errors():
    return {
        "httpx_timeout": httpx.TimeoutException("slow", request=REQ),
        "api_timeout": anthropic.APITimeoutError(request=REQ),
        "500": anthropic.InternalServerError("boom", response=httpx.Response(500, request=REQ), body=None),
        "529": anthropic.InternalServerError("overloaded", response=httpx.Response(529, request=REQ), body=None),
        "429": anthropic.RateLimitError("slow down", response=httpx.Response(429, request=REQ), body=None),
    }


class FakeClock:
    def __init__(self):
        self.t = 0.0
        self.sleeps = []

    def monotonic(self):
        return self.t

    async def sleep(self, s):
        self.sleeps.append(s)
        self.t += s


def run(client, run_id, fc=None):
    fc = fc or FakeClock()
    return asyncio.run(desk.run_week("taxi", WEEK, run_id=run_id, client=client, model="test-model",
                                     monotonic=fc.monotonic, sleep=fc.sleep)), fc


def check_fallback_entries(run_id):
    es = [e for e in log.list("taxi") if e.run_id == run_id]
    assert len(es) == 2 and all(e.agent == "fallback" for e in es)
    assert all(log.validate_summary(e.summary, e.numbers) == [] for e in es)  # templates pass I2
    return es


@pytest.mark.parametrize("kind", list(errors()))
def test_A16_A17_errors_fall_back_after_bounded_retries(kind):
    err = errors()[kind]
    client = MockClaude([err] * 10)
    r, fc = run(client, f"run_{kind}")
    assert len(client.calls) == 3  # 1 try + 2 retries, then fallback for the remainder
    assert fc.t < desk.RUN_DEADLINE_S
    assert r.agent == "fallback" and {h.agent for h in r.hedges} == {"fallback"}
    check_fallback_entries(f"run_{kind}")
    rain = next(h for h in r.hedges if h.id == RAIN_HID)
    assert rain.ticker == RAIN_TICKER  # the most liquid (only) candidate


def test_deadline_stops_claude():
    fc = FakeClock()
    fc.t = 0.0

    def slow(kw):
        fc.t += desk.RUN_DEADLINE_S + 1
        return happy_script(RAIN, RAIN_TICKER, RAIN_HID)[0]

    r, _ = run(MockClaude([slow] * 5), "run_deadline", fc)
    assert r.agent == "fallback"
    check_fallback_entries("run_deadline")


def test_A18_fallback_mid_run_no_duplicates():
    err = errors()["500"]
    client = MockClaude(happy_script(RAIN, RAIN_TICKER, RAIN_HID) + [err] * 10)
    r, _ = run(client, "run_a18")
    es = {e.hedge_id: e for e in log.list("taxi") if e.run_id == "run_a18"}
    assert es[RAIN_HID].agent == "claude" and es[HOT_HID].agent == "fallback"
    ids = [h.id for h in db.list_hedges("taxi", WEEK)]
    assert sorted(ids) == sorted({RAIN_HID, HOT_HID}) and len(ids) == 2


def test_fallback_without_key_same_decisions_as_claude():
    from tests.agent.conftest import HOT_TICKER

    claude_run, _ = run(MockClaude(happy_script(RAIN, RAIN_TICKER, RAIN_HID) + happy_script(HOT, HOT_TICKER, HOT_HID)),
                        "run_cl")
    claude = {h.exposure_id: (h.status, h.ticker, h.n_filled, h.premium, h.decision.reasons) for h in claude_run.hedges}
    with db.session() as s:  # reset the week so the fallback starts from the same budget
        for row in s.exec(db.select(db.HedgeRow).where(db.HedgeRow.week_of == WEEK.isoformat())).all():
            s.delete(row)
    fb = asyncio.run(desk.run_week("taxi", WEEK, run_id="run_fb"))  # no key, no client
    assert fb.agent == "fallback"
    fallback = {h.exposure_id: (h.status, h.ticker, h.n_filled, h.premium, h.decision.reasons) for h in fb.hedges}
    assert fallback == claude
