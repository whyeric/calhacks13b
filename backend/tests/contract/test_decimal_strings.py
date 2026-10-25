"""C6-A4: Decimal fields are JSON strings; floats appear only on statistics keys."""

import re
from decimal import Decimal

import pytest
from pydantic import BaseModel

from app.models import DECIMAL_STR

from .conftest import EXAMPLES, validate_example

# Statistics and non-money parameters that stay JSON numbers (CONTRACTS R1).
FLOAT_KEYS = {"p_value", "coverage", "reduction_pct", "priced_real_pct", "frac", "target", "strike", "basis_r2_min",
              "rain_size_multiplier",
              "precision", "recall", "cause_accuracy",  # reconciliation benchmark scores
              "expected_count"}  # expected_count: model-implied expected events (playoff home games)


def _decimal_paths(obj, raw, path="$"):
    """Yield (path, raw value) for every value the model holds as a Decimal."""
    if isinstance(obj, BaseModel):
        for name in type(obj).model_fields:
            yield from _decimal_paths(getattr(obj, name), raw[name], f"{path}.{name}")
    elif isinstance(obj, (list, tuple)):
        for i, (o, r) in enumerate(zip(obj, raw, strict=True)):
            yield from _decimal_paths(o, r, f"{path}[{i}]")
    elif isinstance(obj, dict):
        for k, o in obj.items():
            yield from _decimal_paths(o, raw[k], f"{path}.{k}")
    elif isinstance(obj, Decimal):
        yield path, raw


def _float_keys(raw, key=None):
    if isinstance(raw, float):
        yield key
    elif isinstance(raw, dict):
        for k, v in raw.items():
            yield from _float_keys(v, k)
    elif isinstance(raw, list):
        for v in raw:
            yield from _float_keys(v, key)


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_decimal_fields_are_strings(name):
    raw, parsed = validate_example(name)
    paths = list(_decimal_paths(parsed, raw))
    for path, value in paths:
        assert isinstance(value, str) and re.fullmatch(DECIMAL_STR, value), f"{name} {path}: {value!r}"


@pytest.mark.parametrize("name", sorted(EXAMPLES))
def test_floats_only_on_stat_keys(name):
    raw, _ = validate_example(name)
    bad = {k for k in _float_keys(raw) if not (k in FLOAT_KEYS or k.startswith("r2_"))}
    assert not bad, f"{name}: float values under money/price keys {sorted(bad)}"


def test_walker_sees_money_fields():
    # Guard against the walker silently finding nothing.
    raw, hedge = validate_example("hedge_pending.json")
    paths = dict(_decimal_paths(hedge, raw))
    assert paths["$.premium"] == "942.80"
    assert paths["$.fills[0].price"] == "0.74"
    assert paths["$.decision.checks[6].metric.remaining"] == "250.00"
