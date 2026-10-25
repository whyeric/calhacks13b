"""API test app: temp SQLite seeded from fixtures, DEMO_OFFLINE=1, no Anthropic key,
fixture-backed markets, temp ledgers dir, and a pinned clock (Sat 2026-10-24 19:00 UTC,
so the desk week is the fixture week of Mon 2026-10-26)."""

import json
from datetime import datetime, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from app import clock, config, db

NOW = datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc)
FIXTURE_WEEK = "2026-10-26"
EXAMPLES = Path(__file__).resolve().parents[2] / "fixtures" / "examples"


def load_example(name: str):
    return json.loads((EXAMPLES / name).read_text())


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'test.db'}")
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "")
    monkeypatch.setenv("ANTHROPIC_MODEL", "")
    monkeypatch.setenv("MARKETS_BACKEND", "fixture")
    monkeypatch.setenv("LEDGERS_DIR", str(tmp_path / "ledgers"))
    monkeypatch.delenv("OWNER_TOKEN", raising=False)
    monkeypatch.delenv("CONTROLLER_TOKEN", raising=False)
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()
    monkeypatch.setattr(clock, "now", lambda: NOW)
    db.seed()
    yield tmp_path
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()


@pytest.fixture
def client(app_env):
    from app.main import app

    with TestClient(app) as c:
        yield c


@pytest.fixture
def stub_analysis(monkeypatch):
    """Analysis from the example response instead of fitting the feature table."""
    from app import analysis
    from app.models import AnalyzeResponse

    res = AnalyzeResponse.model_validate(load_example("analyze_response.json"))
    monkeypatch.setattr(analysis, "compute", lambda business_id, strike=None: res)
    return res
