"""The backtest is stored by `make seed` / API startup, so GET /backtest is served offline (e2e gap)."""

from fastapi.testclient import TestClient

from app import backtest_job, config, db
from app.models import BacktestResult


def test_startup_stores_the_backtest_for_businesses_with_data(app_env, monkeypatch):
    monkeypatch.setenv("BACKTEST_ON_STARTUP", "1")
    config.get_settings.cache_clear()
    assert db.get_analysis("taxi", "backtest") is None
    from app.main import app

    with TestClient(app) as c:
        r = c.get("/businesses/taxi/backtest")
        assert r.status_code == 200, r.text
        body = BacktestResult.model_validate(r.json())
        assert body.weekly and body.worst_week_unhedged is not None
        if not (config.FIXTURES_DIR / "restaurant_daily.parquet").exists():  # fresh clone: no Dewey data
            assert c.get("/businesses/restaurant/backtest").json()["error"]["code"] == "backtest_not_ready"


def test_ensure_skips_existing_rows_and_missing_data(app_env):
    first = backtest_job.ensure(["taxi"])
    assert first == {"taxi": "stored"}
    assert backtest_job.ensure(["taxi"]) == {"taxi": "exists"}
    assert backtest_job.ensure(["taxi"], force=True) == {"taxi": "stored"}
    if not (config.FIXTURES_DIR / "restaurant_daily.parquet").exists():
        assert backtest_job.ensure(["restaurant"])["restaurant"].startswith("skipped")
