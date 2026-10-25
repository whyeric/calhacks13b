"""Generate serialization schemas directly from the shared Pydantic contracts."""
import json
import sys
from pathlib import Path

root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root / "frontend/.python-tools"), str(root / "backend")]
from pydantic.json_schema import models_json_schema
from app.models import (Business, AnalyzeResponse, Hedge, LogEntry, RunAccepted, RunStatus,
    BacktestResult, LedgerResponse, ReconResult, ChatReply, Settings, Health, ResearchReport)

models = [Business, AnalyzeResponse, Hedge, LogEntry, RunAccepted, RunStatus,
    BacktestResult, LedgerResponse, ReconResult, ChatReply, Settings, Health, ResearchReport]
_, schema = models_json_schema([(model, "serialization") for model in models])
document = {"openapi": "3.1.0", "info": {"title": "Hedge Desk contracts", "version": "1"}, "paths": {}, "components": {"schemas": schema["$defs"]}}
serialized = json.dumps(document, indent=2).replace("#/$defs/", "#/components/schemas/")
(root / "frontend/fixtures/contracts.json").write_text(serialized + "\n", encoding="utf-8")
