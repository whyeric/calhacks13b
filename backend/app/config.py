"""Runtime settings (env / `.env`) and the single `Thresholds` object (CONTRACTS R19).

Nothing outside this module may hard-code a model id, URL or threshold.
"""

from dataclasses import dataclass
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

# Stats gap G2: backtest price fallback is trailing p-hat plus this markup ("frequency" tier).
FALLBACK_MARKUP = Decimal("0.02")


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        # Repo-root .env first; backend/.env (if any) overrides it.
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",  # .env also carries frontend keys such as NEXT_PUBLIC_API_URL
        frozen=True,
    )

    anthropic_api_key: str | None = None  # unset -> deterministic fallback agent
    anthropic_model: str | None = None  # pinned id from .env; never defaulted here
    kalshi_base_url: str = "https://external-api.kalshi.com/trade-api/v2"
    demo_offline: bool = False  # True blocks all outbound HTTP
    database_url: str = "sqlite:///./hedge_desk.db"
    weekly_budget_default: Decimal = Decimal("250")
    avg_check_usd: Decimal = Decimal("35")
    avg_check_label: str = "assumed"
    cors_origins: str = "http://localhost:3000,http://127.0.0.1:3000"
    owner_token: str | None = None  # G1: off unless set

    @model_validator(mode="after")
    def _model_required_with_key(self) -> "Settings":
        if self.anthropic_api_key and not self.anthropic_model:
            raise ValueError("ANTHROPIC_MODEL must be set when ANTHROPIC_API_KEY is set")
        return self

    @property
    def use_claude(self) -> bool:
        return bool(self.anthropic_api_key and self.anthropic_model)

    @property
    def cors_origin_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@dataclass(frozen=True)
class Thresholds:
    """Decline-rule and agent limits. Defaults only; per-business overrides live in the DB (R14)."""

    min_size_usd: Decimal = Decimal("150")  # rule 1 / exposure gate: |effect| below this is not hedged
    min_support: int = 10  # event days in train
    overpay_max: Decimal = Decimal("0.15")  # rule 3: avg_price - fair, strictly greater fails
    cost_ratio_max: Decimal = Decimal("0.35")  # rule 5: expected cost / protected amount
    fill_decline: Decimal = Decimal("0.5")  # rule 2: fill ratio below this is declined
    fill_full: Decimal = Decimal("1.0")  # rule 2: between decline and full is partial
    max_slip: Decimal = Decimal("0.05")  # book walk: max price above best ask
    basis_r2_min: float = 0.5  # rule 4
    max_tool_calls: int = 12  # agent loop cap per turn


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_thresholds() -> Thresholds:
    return Thresholds()
