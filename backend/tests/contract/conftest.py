"""Shared helpers for contract tests: which model each example file validates against."""

import json
from pathlib import Path

from pydantic import TypeAdapter

from app import models

FIXTURES = Path(__file__).resolve().parents[2] / "fixtures"
EXAMPLES_DIR = FIXTURES / "examples"
BUSINESSES_DIR = FIXTURES / "businesses"

# file name -> CONTRACT_MODELS name. A file holding a JSON array is a list of that model.
EXAMPLES: dict[str, str] = {
    "analyze_request.json": "AnalyzeRequest",
    "analyze_response.json": "AnalyzeResponse",
    "approve_request.json": "ApproveRequest",
    "backtest_result.json": "BacktestResult",
    "basis_stat.json": "BasisStat",
    "budget.json": "Budget",
    "business_restaurant.json": "Business",
    "business_taxi.json": "Business",
    "chat_reply.json": "ChatReply",
    "chat_request.json": "ChatRequest",
    "check.json": "Check",
    "decision.json": "Decision",
    "decisions_seed.json": "LogEntry",
    "desk_run_request.json": "DeskRunRequest",
    "error.json": "ErrorBody",
    "exposure.json": "Exposure",
    "exposure_dropped.json": "Exposure",
    "exposure_playoff.json": "Exposure",
    "health.json": "Health",
    "hedge_declined.json": "Hedge",
    "hedge_lite.json": "HedgeLite",
    "hedge_partial.json": "Hedge",
    "hedge_playoff_leg.json": "Hedge",
    "hedge_pending.json": "Hedge",
    "hedge_proposed.json": "Hedge",
    "ledger_entry.json": "LedgerEntry",
    "ledger_response.json": "LedgerResponse",
    "log_entry.json": "LogEntry",
    "model_check.json": "ModelCheck",
    "reconciliation.json": "ReconResult",
    "reconciliation_benchmark.json": "ReconBenchmark",
    "reject_request.json": "RejectRequest",
    "research_report.json": "ResearchReport",
    "run_accepted.json": "RunAccepted",
    "run_status.json": "RunStatus",
    "settings.json": "Settings",
    "week_seed.json": "Hedge",
}


def load_json(path: Path):
    return json.loads(path.read_text())


def validate_example(name: str):
    """Parse an example with its model; returns (raw JSON, model instance or list of them)."""
    model = models.CONTRACT_MODELS[EXAMPLES[name]]
    raw = load_json(EXAMPLES_DIR / name)
    if isinstance(raw, list):
        return raw, TypeAdapter(list[model]).validate_python(raw)
    return raw, model.model_validate(raw)


def dump_json(obj) -> object:
    """JSON-mode dump of a model or list of models, parsed back to plain Python."""
    if isinstance(obj, list):
        return [json.loads(o.model_dump_json()) for o in obj]
    return json.loads(obj.model_dump_json())
