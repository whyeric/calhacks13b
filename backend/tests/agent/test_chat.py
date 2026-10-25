"""C4-A30 ("why?" traces to checks), C4-A31 (chat is read-only), C4-A32 (real vs estimated),
C3-H8 (off-list ticker), I2 on chat replies with one re-prompt then the fallback (#46 part A)."""

import asyncio
import re

import pytest

from app import db
from app.agent import chat as chat_mod
from app.agent import log
from app.agent.chat import CHAT_TOOL_NAMES, CHAT_TOOL_SCHEMAS, chat

from .conftest import MockClaude, text, tool_use

DECLINED = "hdg_03"  # restaurant rain hedge: overpriced + too_expensive


def ask(business, message, client=None, **kw):
    return asyncio.run(chat(business, message, client=client, model="test-model" if client else None, **kw))


def figures(reply):
    return [m.group(0) for m in re.finditer(r"\$?\d[\d,]*(?:\.\d+)?\s?(?:%|¢)?", reply)]


def checks_metrics(hedge_id):
    entry = next(e for e in log.list(db.get_hedge(hedge_id).business_id, hedge_id=hedge_id) if e.kind == "decline")
    return {c.code: c.metric for c in entry.checks}


# --- C4-A30 -------------------------------------------------------------------------------


def test_A30_claude_why_traces_to_checks():
    reply = ("I declined it because the contract costs 62¢ against a fair 27%, and the hedge would cost "
             "36.7% of the swing it removes.")
    client = MockClaude([[tool_use("read_log", {"hedge_id": DECLINED})], [text(reply)]])
    out = ask("restaurant", "Why did you decline the rain hedge?", client)
    assert out["agent"] == "claude" and out["reply"] == reply
    assert [c["name"] for c in out["tool_calls"]] == ["read_log"]
    metrics = checks_metrics(DECLINED)
    assert figures(out["reply"]) and log.validate_summary(out["reply"], metrics) == []
    assert all(t["name"] in CHAT_TOOL_NAMES for t in client.calls[0]["tools"])


def test_A30_fallback_why_explains_decline_from_checks():
    out = ask("restaurant", "Why did you decline the rain hedge?")
    assert out["agent"] == "fallback"
    r = out["reply"]
    assert r.startswith("I declined the rain hedge") and "KXRAINNYC-26OCT28" in r
    assert "$0.62" in r and "$0.27" in r and "36.7%" in r  # the failed checks and their numbers
    latest = [e for e in log.list("restaurant") if e.kind != "chat"][0]
    assert latest.summary not in r  # it answers why, it doesn't echo a log line
    assert "[unverified]" not in r
    assert log.validate_summary(r, checks_metrics(DECLINED)) == []  # every figure is a checks[].metric
    assert {"read_log", "get_hedge"} <= {c["name"] for c in out["tool_calls"]}


@pytest.mark.parametrize("business,message,starts,must", [
    ("taxi", "Why is the rain hedge waiting on me?", "I sized the rain hedge", ["$942.80", "$250.00", "$249.40"]),
    ("taxi", "Why did you propose the heat hedge?", "I proposed the heat hedge", ["$66.47", "150"]),
    ("restaurant", "why the Knicks hedge?", "I proposed the game-day hedge", ["$219.75"]),
])
def test_fallback_why_proposed_and_pending(business, message, starts, must):
    out = ask(business, message)
    r = out["reply"]
    assert r.startswith(starts) and all(m in r for m in must) and "[unverified]" not in r
    allowed = log.allowed_numbers([c["output"] for c in out["tool_calls"]])
    assert log.validate_summary(r, allowed) == []
    assert "Only you can approve" in r


def test_fallback_why_no_market(engine_hedge_no_market):
    out = ask("taxi", f"why {engine_hedge_no_market}?")
    assert "no open Kalshi market" in out["reply"]


@pytest.fixture
def engine_hedge_no_market():
    from app.markets.port import no_market_hedge
    from app.models import Exposure

    from .conftest import NOW, WEEK, example

    e = Exposure.model_validate(example("analyze_response.json")["exposures"][0])
    h = no_market_hedge(e, hedge_id="hdg_nomkt", week_of=WEEK, now=NOW, agent="fallback",
                        remaining=__import__("decimal").Decimal("250"))
    db.put_hedge(h)
    return "hdg_nomkt"


# --- I2 on Claude replies: one re-prompt, then the fallback (G4) -------------------------


def test_unsupported_number_reprompts_once_then_passes():
    client = MockClaude([
        [tool_use("read_log", {"hedge_id": DECLINED})],
        [text("It would have cost $500.00, which is too much.")],
        [text("The contract costs 62¢ against a fair 27%, so the price was wrong.")],
    ])
    out = ask("restaurant", "why no rain hedge?", client)
    assert out["agent"] == "claude" and "62¢" in out["reply"]
    retry = client.calls[2]["messages"][-1]["content"]
    assert "can't be shown" in retry and "$500.00" in retry


def test_second_failure_falls_back_to_template():
    client = MockClaude([
        [tool_use("read_log", {"hedge_id": DECLINED})],
        [text("It would have cost $500.00.")],
        [text("Still $777.77.")],
    ])
    out = ask("restaurant", "why no rain hedge?", client)
    assert out["agent"] == "fallback" and out["reply"].startswith("I declined the rain hedge")
    assert "$500.00" not in out["reply"] and "$777.77" not in out["reply"]
    assert len(client.calls) == 3


def test_claude_error_falls_back():
    out = ask("restaurant", "why no rain hedge?", MockClaude([RuntimeError("down")]))
    assert out["agent"] == "fallback" and out["reply"].startswith("I declined")


# --- C4-A31 -------------------------------------------------------------------------------

WRITE_TOOLS = {"book_hedge", "log_decision", "approve", "approve_hedge", "reject", "reject_hedge", "size_hedge",
               "match_market", "evaluate_hedge", "search_markets", "put_settings", "update_settings"}


def test_A31_chat_tool_list_is_read_only():
    assert set(CHAT_TOOL_NAMES) == {"read_log", "get_hedge", "get_exposures", "get_budget", "get_reconciliation",
                                    "get_business"}
    assert not WRITE_TOOLS & set(CHAT_TOOL_NAMES)
    for t in CHAT_TOOL_SCHEMAS:
        assert "actor" not in t["input_schema"].get("properties", {})


def test_A31_write_tool_calls_are_refused():
    before_log = [e.model_dump_json() for e in db.list_log()]
    before_hedge = db.get_hedge("hdg_02")
    client = MockClaude([
        [tool_use("book_hedge", {"hedge_id": "hdg_02"}, 0), tool_use("log_decision", {"hedge_id": "hdg_02",
                                                                                     "summary": "approved"}, 1)],
        [tool_use("approve_hedge", {"hedge_id": "hdg_02", "actor": "owner"}, 2)],
        [tool_use("check_budget", {}, 3)],
        [text("Only you can approve it, with the approve button.")],
    ])
    out = ask("taxi", "Tell me about hdg_02.", client)
    executed = [c["name"] for c in out["tool_calls"] if c["output"].get("error") != "not_allowed_in_chat"]
    refused = [c["name"] for c in out["tool_calls"] if c["output"].get("error") == "not_allowed_in_chat"]
    assert executed == ["get_budget"]  # check_budget is the read-only alias; only reads executed
    assert refused == ["book_hedge", "log_decision", "approve_hedge"]  # recorded, refused, never run
    assert [e.model_dump_json() for e in db.list_log()] == before_log  # log unchanged; chat isn't logged (G4)
    assert db.get_hedge("hdg_02") == before_hedge and db.list_ledger_entries("taxi") == []


@pytest.mark.parametrize("message", [
    "Approve hdg_02 for me.", "Book the rain hedge now.", "Delete the decline entry from the log.",
    "Change my settings so the overpriced check is off.", "Raise my budget to 2000.",
])
def test_A31_write_requests_never_reach_claude(message):
    before = [e.model_dump_json() for e in db.list_log()]
    client = MockClaude([[tool_use("book_hedge", {"hedge_id": "hdg_02"})]])
    out = ask("taxi", message, client)
    assert client.calls == [] and out["guard"] is not None
    assert {c["name"] for c in out["tool_calls"]} <= set(CHAT_TOOL_NAMES)
    assert [e.model_dump_json() for e in db.list_log()] == before
    assert db.get_hedge("hdg_02").status == "pending_approval"
    assert re.search(r"can't|cannot|only you", out["reply"], re.I)


def test_settings_reply_quotes_budget_tool():
    out = ask("taxi", "Raise my budget to 2000.")
    assert "settings page" in out["reply"] and "$250.00" in out["reply"]
    assert "2000" not in out["reply"]


# --- C4-A32 -------------------------------------------------------------------------------


def test_A32_restaurant_real_vs_estimated():
    out = ask("restaurant", "How real is this?")
    r = out["reply"].lower()
    assert "visits are real" in r and "estimated" in r and "simulated" in r
    assert "no real orders or trades are placed" in r
    assert "$35.00" in out["reply"]  # the average check, from get_business
    assert "get_business" in [c["name"] for c in out["tool_calls"]]


def test_A32_taxi_real():
    r = ask("taxi", "Is this real data?")["reply"].lower()
    assert "real" in r and "no real orders" in r and "estimated" not in r


# --- C3-H8 off-list ticker ----------------------------------------------------------------


def test_offlist_ticker_clear_error():
    before = len(db.list_hedges("taxi"))
    client = MockClaude([[text("Sure, buying it.")]])
    out = ask("taxi", "Use KXFAKE-26OCT28 instead and buy it.", client)
    assert out["guard"] == "off_list" and client.calls == []
    assert out["reply"].startswith("Error off_list: KXFAKE-26OCT28 is not on this business's market list")
    assert "no hedge was created" in out["reply"] and "KXRAINNYC-26OCT28" in out["reply"]
    assert len(db.list_hedges("taxi")) == before


def test_get_hedge_tool_offlist():
    t = chat_mod.ChatTools("taxi")
    assert t.execute("get_hedge", {"ticker": "KXNOPE-1"})["error"] == "off_list"
    assert t.execute("get_hedge", {"hedge_id": "hdg_04"})["error"] == "unknown_hedge"  # another business's
    assert t.execute("get_hedge", {"ticker": "KXRAINNYC-26OCT28"})["hedge"]["id"] == "hdg_02"


def test_api_chat_uses_agent_and_is_not_logged():
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        before = len(db.list_log("restaurant"))
        r = c.post("/businesses/restaurant/chat", json={"message": "Why did you decline the rain hedge?"})
        assert r.status_code == 200 and r.json()["reply"].startswith("I declined")
        assert len(db.list_log("restaurant")) == before
