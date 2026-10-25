"""C6-A2: every example JSON validates against its model and round-trips unchanged."""

import pytest
from pydantic import ValidationError

from app import models

from .conftest import EXAMPLES, EXAMPLES_DIR, dump_json, load_json, validate_example


def test_every_example_file_is_mapped():
    on_disk = {p.name for p in EXAMPLES_DIR.glob("*.json")}
    assert on_disk == set(EXAMPLES), "add new example files to EXAMPLES in conftest.py (and remove stale ones)"


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_example_validates_and_round_trips(name):
    raw, parsed = validate_example(name)
    assert dump_json(parsed) == raw


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_unknown_field_is_rejected(name):
    raw, _ = validate_example(name)
    item = raw[0] if isinstance(raw, list) else raw
    model = models.CONTRACT_MODELS[EXAMPLES[name]]
    with pytest.raises(ValidationError, match="extra"):
        model.model_validate({**item, "renamed_field": 1})


def test_declined_hedge_mirrors_spec_snippet():
    hedge = models.Hedge.model_validate(load_json(EXAMPLES_DIR / "hedge_declined.json"))
    d = hedge.decision
    assert hedge.status == d.status == "declined"
    assert d.reasons == ["overpriced", "too_expensive"]
    overpriced = next(c for c in d.checks if c.code == "overpriced")
    assert {k: str(v) for k, v in overpriced.metric.items()} == {"avg_price": "0.62", "fair": "0.27", "overpay": "0.35"}
    assert next(c for c in d.checks if c.code == "too_expensive").metric["swing"] == 900


def test_pending_hedge_has_within_budget_alternative():
    hedge = models.Hedge.model_validate(load_json(EXAMPLES_DIR / "hedge_pending.json"))
    budget = next(c for c in hedge.decision.checks if c.code == "over_budget").metric
    assert hedge.status == "pending_approval"
    assert hedge.premium > budget["remaining"]
    assert hedge.alternative is not None and hedge.alternative.premium <= budget["remaining"]


def test_decision_example_has_partial_and_resized_flags():
    d = models.Decision.model_validate(load_json(EXAMPLES_DIR / "decision.json"))
    metrics = {c.code: c.metric for c in d.checks}
    assert metrics["illiquid"]["partial"] is True
    assert metrics["basis_too_loose"]["resized"] is True
    assert d.status == "proposed"


def test_week_seed_covers_each_state():
    _, hedges = validate_example("week_seed.json")
    statuses = [h.status for h in hedges]
    for s in ("proposed", "pending_approval", "declined"):
        assert s in statuses
    assert any(h.partial for h in hedges)
    for h in hedges:
        if h.status == "declined":
            assert h.decision.reasons and h.decision.checks


def test_log_entry_variants():
    _, entries = validate_example("log_entry.json")
    assert {e.kind for e in entries} >= {"proposal", "approval"}
    assert {e.agent for e in entries} >= {"claude", "fallback"}
    assert any(e.kind == "approval" and e.actor == "owner" for e in entries)


def test_decisions_seed_mixes_actors_and_agents():
    _, entries = validate_example("decisions_seed.json")
    assert len(entries) >= 8
    assert {e.actor for e in entries} == {"desk", "owner", "system"}
    assert {"claude", "fallback"} <= {e.agent for e in entries}
    assert len({e.log_id for e in entries}) == len(entries)


def test_backtest_has_one_ineffective_exposure():
    _, bt = validate_example("backtest_result.json")
    assert [k for k, v in bt.per_exposure.items() if v.ineffective]


def test_reconciliation_flags_planted_short_deposit():
    _, recon = validate_example("reconciliation.json")
    assert len(recon.mismatches) == 1
    mm = recon.mismatches[0]
    assert mm.bank < mm.kalshi_ledger and mm.explanation and mm.action == "ask_owner"


def test_model_check_plants_500_over_50_seeds():
    _, mc = validate_example("model_check.json")
    assert mc.planted_usd == 500 and mc.n_seeds == 50
    lo, hi = mc.example.ci90
    assert mc.example.contains_truth == (lo <= mc.planted_usd <= hi)


def test_settings_mirror_config_thresholds():
    from dataclasses import fields

    from app.config import Thresholds

    assert set(models.ThresholdSettings.model_fields) == {f.name for f in fields(Thresholds)}


def test_settings_example_matches_config_defaults():
    from dataclasses import asdict

    from app.config import Thresholds

    _, settings = validate_example("settings.json")
    assert settings.thresholds.model_dump() == asdict(Thresholds())
