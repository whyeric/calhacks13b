"""C6-A3: every model in CONTRACT_MODELS has at least one example file."""

from app import models

from .conftest import EXAMPLES


def test_every_contract_model_has_an_example():
    covered = set(EXAMPLES.values())
    missing = sorted(set(models.CONTRACT_MODELS) - covered)
    assert not missing, f"no example in fixtures/examples/ for: {missing}"


def test_examples_only_name_registered_models():
    assert set(EXAMPLES.values()) <= set(models.CONTRACT_MODELS)
