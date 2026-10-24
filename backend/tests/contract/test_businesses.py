"""C6-A24: business fixtures validate and carry the right real/estimated labels."""

import pytest

from app.models import Business

from .conftest import BUSINESSES_DIR, EXAMPLES_DIR, load_json


def _load(name: str) -> Business:
    return Business.model_validate(load_json(BUSINESSES_DIR / f"{name}.json"))


def test_both_businesses_present():
    assert {p.stem for p in BUSINESSES_DIR.glob("*.json")} == {"taxi", "restaurant"}


def test_taxi_is_real():
    taxi = _load("taxi")
    assert taxi.kind == "taxi"
    assert taxi.estimated is False and taxi.data_label == "real"


def test_restaurant_is_estimated_with_assumed_check():
    bar = _load("restaurant")
    assert bar.kind == "restaurant"
    assert bar.estimated is True and bar.data_label == "estimated"
    assert bar.avg_check_usd is not None and bar.avg_check_label == "assumed"


@pytest.mark.parametrize("name", ["taxi", "restaurant"])
def test_example_copy_matches_fixture(name):
    assert load_json(EXAMPLES_DIR / f"business_{name}.json") == load_json(BUSINESSES_DIR / f"{name}.json")


def test_estimated_flag_must_match_label():
    data = load_json(BUSINESSES_DIR / "restaurant.json")
    data["estimated"] = False
    with pytest.raises(ValueError):
        Business.model_validate(data)
