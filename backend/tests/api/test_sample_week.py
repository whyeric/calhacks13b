"""DEMO_SAMPLE_WEEK (#39 carry-over): the seeded example week is flagged on /health, a real desk
run replaces it, and every real open hedge matches a hedgeable exposure from /analyze."""

import pytest
from fastapi.testclient import TestClient

from app import config, db
from app.config import FIXTURES_DIR
from tests.api.conftest import FIXTURE_WEEK, load_example
from tests.api.test_desk_run import poll

OPEN = ("proposed", "pending_approval")
SAMPLE_IDS = {h["id"] for h in load_example("week_seed.json")}
# restaurant_daily.parquet is built from raw Dewey exports (gitignored); without it the
# restaurant has no analysis and its desk run fails.
needs_restaurant = pytest.mark.skipif(
    not (FIXTURES_DIR / "restaurant_daily.parquet").exists(), reason="restaurant_daily.parquet not built"
)
BUSINESSES = [pytest.param("restaurant", marks=needs_restaurant), "taxi"]


def _run(client, business_id, week=FIXTURE_WEEK, expect="done"):
    run_id = client.post(f"/businesses/{business_id}/desk/run", json={"week_of": week}).json()["run_id"]
    run = poll(client, run_id, timeout=60)
    assert run["status"] == expect, run
    return run_id


def _hedges(client, business_id, week=FIXTURE_WEEK):
    return client.get(f"/businesses/{business_id}/hedges", params={"week_of": week}).json()


def assert_open_hedges_match_analysis(client, business_id):
    """Every non-sample proposed/pending hedge is for a hedgeable exposure /analyze reports."""
    a = client.post(f"/businesses/{business_id}/analyze", json={})
    assert a.status_code == 200, a.text
    hedgeable = {e["id"] for e in a.json()["exposures"] if e["hedgeable"]}
    for h in _hedges(client, business_id):
        if h["status"] in OPEN and not db.is_sample_hedge(h["id"]):
            assert h["exposure_id"] in hedgeable, (business_id, h["id"], h["exposure_id"], sorted(hedgeable))


def test_health_flags_sample_week(client):
    h = client.get("/health").json()
    assert h["sample_week"] is True and h["sample_businesses"] == ["restaurant", "taxi"]
    ids = {h["id"] for b in ("taxi", "restaurant") for h in _hedges(client, b)}
    assert ids == SAMPLE_IDS


@pytest.mark.parametrize("business_id", BUSINESSES)
def test_desk_run_replaces_sample_hedges(client, business_id, caplog):
    sample_log = {e["log_id"] for e in client.get(f"/businesses/{business_id}/decisions").json()
                  if e["hedge_id"] in SAMPLE_IDS}
    assert sample_log
    with caplog.at_level("INFO", logger="hedge_desk.api"):
        _run(client, business_id)
    assert any("replaced sample week" in r.getMessage() for r in caplog.records)

    hedges = _hedges(client, business_id)
    assert not any(db.is_sample_hedge(h["id"]) for h in hedges)
    other = "taxi" if business_id == "restaurant" else "restaurant"
    assert client.get("/health").json()["sample_businesses"] == [other]

    view = {e["log_id"] for e in client.get(f"/businesses/{business_id}/decisions", params={"limit": 500}).json()}
    assert not view & sample_log  # hidden from the view, still stored (append-only)
    assert sample_log <= {e.log_id for e in db.list_log(business_id)}

    # Re-seeding (make seed) does not bring the sample back over a week a real run decided.
    if hedges:
        db.seed()
        assert not any(db.is_sample_hedge(h["id"]) for h in _hedges(client, business_id))
    assert_open_hedges_match_analysis(client, business_id)


@needs_restaurant
def test_both_replaced_clears_flag(client):
    for b in ("restaurant", "taxi"):
        _run(client, b)
    h = client.get("/health").json()
    assert h["sample_week"] is False and h["sample_businesses"] == []


@pytest.mark.parametrize("markets_backend", ["fixture", "kalshi"])
@pytest.mark.parametrize("business_id", BUSINESSES)
def test_real_open_hedges_are_hedgeable_exposures(client, monkeypatch, business_id, markets_backend):
    """The consistency check, after a real run on fixture markets or the offline Kalshi cache."""
    monkeypatch.setenv("MARKETS_BACKEND", markets_backend)
    config.get_settings.cache_clear()
    _run(client, business_id)
    assert_open_hedges_match_analysis(client, business_id)


def test_failed_run_restores_sample(client, monkeypatch):
    from app.agent import desk

    async def boom(*a, **k):
        raise RuntimeError("markets exploded")

    monkeypatch.setattr(desk, "run_week", boom)
    before = {h["id"] for h in _hedges(client, "taxi")}
    _run(client, "taxi", expect="failed")
    assert {h["id"] for h in _hedges(client, "taxi")} == before
    assert client.get("/health").json()["sample_businesses"] == ["restaurant", "taxi"]


def test_sample_week_off(app_env, monkeypatch):
    """DEMO_SAMPLE_WEEK=0: startup drops stored sample hedges; /health says false."""
    monkeypatch.setenv("DEMO_SAMPLE_WEEK", "0")
    config.get_settings.cache_clear()
    assert db.list_sample_hedges()  # app_env seeded the sample before the flag flipped
    from app.main import app

    with TestClient(app) as client:
        h = client.get("/health").json()
        assert h["sample_week"] is False and h["sample_businesses"] == []
        assert [h for b in ("taxi", "restaurant") for h in _hedges(client, b)] == []
        decisions = client.get("/businesses/restaurant/decisions").json()
        assert not any(e["hedge_id"] in SAMPLE_IDS for e in decisions)
        _run(client, "taxi")
        assert not any(db.is_sample_hedge(h["id"]) for h in _hedges(client, "taxi"))
        assert_open_hedges_match_analysis(client, "taxi")


def test_seed_without_sample_week(tmp_path):
    engine = db.make_engine(f"sqlite:///{tmp_path / 'fresh.db'}")
    counts = db.seed(engine, sample_week=False)
    assert counts["hedges"] == 0 and counts["businesses"] == 2
    # ledger history (not about a sample-week hedge) is still loaded for app.books.seed
    assert counts["log"] > 0 and all(e.hedge_id not in SAMPLE_IDS for e in db.list_log(engine=engine))
    assert db.sample_businesses(engine) == []
