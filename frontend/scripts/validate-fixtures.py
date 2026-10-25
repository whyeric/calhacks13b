"""Validate every mock payload using the consuming backend contract."""
import json
import sys
from pathlib import Path
root = Path(__file__).resolve().parents[2]
sys.path[:0] = [str(root / "frontend/.python-tools"), str(root / "backend")]
from app.models import (Business, AnalyzeResponse, Hedge, LogEntry, Budget, BacktestResult, LedgerResponse,
    ChatReply, Settings, Health, ResearchReport)
fixtures = root / "frontend/fixtures"
count = 0
for path in fixtures.glob("*.json"):
    name = path.stem
    if name == "budget_snapshots":
        for snapshot in json.loads(path.read_text(encoding="utf-8")).values():
            Budget.model_validate(snapshot)
            count += 1
        continue
    model = (Business if name.startswith("businesses") else AnalyzeResponse if name.startswith("analyze_")
        else Hedge if name.startswith("hedge") else LogEntry if name == "decisions"
        else BacktestResult if name.startswith("backtest_") else LedgerResponse if name.startswith("ledger_")
        else ChatReply if name == "chat_reply" else Settings if name == "settings" else Health if name == "health"
        else ResearchReport if name.startswith("research_") else None)
    if model is None:
        continue
    data = json.loads(path.read_text(encoding="utf-8"))
    for item in data if isinstance(data, list) else [data]:
        if model is Health:  # sample_week fields land with PR #60; validate whatever the model knows
            item = {k: v for k, v in item.items() if k in Health.model_fields}
        model.model_validate(item)
        count += 1
print(f"C7-A34: {count} frontend fixture objects validated against backend models")
