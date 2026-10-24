"""C6-A22: config defaults and overrides; thresholds in one object."""

import dataclasses
from decimal import Decimal

import pytest

from app import config
from app.config import Settings, Thresholds, get_settings

ENV_KEYS = [
    "ANTHROPIC_API_KEY",
    "ANTHROPIC_MODEL",
    "KALSHI_BASE_URL",
    "DEMO_OFFLINE",
    "DATABASE_URL",
    "WEEKLY_BUDGET_DEFAULT",
    "AVG_CHECK_USD",
    "AVG_CHECK_LABEL",
    "CORS_ORIGINS",
    "OWNER_TOKEN",
]


@pytest.fixture(autouse=True)
def clean_env(monkeypatch):
    for key in ENV_KEYS:
        monkeypatch.delenv(key, raising=False)
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def load(**kwargs) -> Settings:
    # _env_file=None isolates from any real .env on the machine.
    return Settings(_env_file=None, **kwargs)


def test_empty_env_defaults():
    s = load()
    assert s.anthropic_api_key is None
    assert s.anthropic_model is None
    assert s.use_claude is False
    assert s.kalshi_base_url == "https://external-api.kalshi.com/trade-api/v2"
    assert s.demo_offline is False
    assert s.database_url == "sqlite:///./hedge_desk.db"
    assert s.weekly_budget_default == Decimal("250")
    assert s.avg_check_usd == Decimal("35")
    assert s.avg_check_label == "assumed"
    assert s.cors_origin_list == ["http://localhost:3000", "http://127.0.0.1:3000"]
    assert s.owner_token is None


def test_env_overrides_apply(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setenv("ANTHROPIC_MODEL", "pinned-model-id")
    monkeypatch.setenv("KALSHI_BASE_URL", "http://127.0.0.1:9999")
    monkeypatch.setenv("DEMO_OFFLINE", "1")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./other.db")
    monkeypatch.setenv("WEEKLY_BUDGET_DEFAULT", "400.50")
    monkeypatch.setenv("AVG_CHECK_USD", "42")
    monkeypatch.setenv("CORS_ORIGINS", "http://a.test, http://b.test")
    monkeypatch.setenv("OWNER_TOKEN", "secret")
    s = load()
    assert s.anthropic_api_key == "test-key"
    assert s.anthropic_model == "pinned-model-id"
    assert s.use_claude is True
    assert s.kalshi_base_url == "http://127.0.0.1:9999"
    assert s.demo_offline is True
    assert s.database_url == "sqlite:///./other.db"
    assert s.weekly_budget_default == Decimal("400.50")
    assert s.avg_check_usd == Decimal("42")
    assert s.cors_origin_list == ["http://a.test", "http://b.test"]
    assert s.owner_token == "secret"


def test_env_file_is_read(tmp_path):
    env = tmp_path / ".env"
    env.write_text("WEEKLY_BUDGET_DEFAULT=99.99\nDEMO_OFFLINE=1\nNEXT_PUBLIC_API_URL=http://x\n")
    s = Settings(_env_file=env)
    assert s.weekly_budget_default == Decimal("99.99")
    assert s.demo_offline is True


def test_budget_is_decimal_not_float(monkeypatch):
    monkeypatch.setenv("WEEKLY_BUDGET_DEFAULT", "0.1")
    s = load()
    assert type(s.weekly_budget_default) is Decimal
    assert s.weekly_budget_default == Decimal("0.1")
    assert type(s.avg_check_usd) is Decimal


def test_key_without_model_is_rejected(monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    with pytest.raises(ValueError, match="ANTHROPIC_MODEL"):
        load()


def test_model_id_not_hard_coded():
    with open(config.__file__) as f:
        assert "claude-" not in f.read()


def test_thresholds_single_object():
    t = Thresholds()
    assert dataclasses.is_dataclass(t)
    assert t.min_size_usd == Decimal("150")
    assert t.min_support == 10
    assert t.overpay_max == Decimal("0.15")
    assert t.cost_ratio_max == Decimal("0.35")
    assert t.fill_decline == Decimal("0.5")
    assert t.fill_full == Decimal("1.0")
    assert t.max_slip == Decimal("0.05")
    assert t.basis_r2_min == 0.5
    assert t.max_tool_calls == 12
    assert config.get_thresholds() == t
    with pytest.raises(dataclasses.FrozenInstanceError):
        t.overpay_max = Decimal("0.2")  # type: ignore[misc]
    # Overrides produce a new object rather than mutating the defaults.
    assert dataclasses.replace(t, overpay_max=Decimal("0.4")).overpay_max == Decimal("0.4")


def test_get_settings_cached(monkeypatch):
    monkeypatch.setitem(Settings.model_config, "env_file", None)
    assert get_settings() is get_settings()
