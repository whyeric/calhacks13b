"""Runtime settings (env / `.env`) and the single `Thresholds` object (CONTRACTS R19).

Nothing outside this module may hard-code a model id, URL or threshold.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from decimal import Decimal
from functools import lru_cache
from pathlib import Path

from pydantic import model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_DIR.parent

# Stats gap G2: backtest price fallback is trailing p-hat plus this markup ("frequency" tier).
FALLBACK_MARKUP = Decimal("0.02")

# --- Data layer (C1) -----------------------------------------------------------
# Repo-root data/ holds raw, gitignored exports; backend/app/data/ is code. Keep them distinct.
RAW_DATA_DIR = REPO_ROOT / "data"
RAW_TLC_DIR = RAW_DATA_DIR / "tlc"  # yellow_tripdata_YYYY-MM.parquet, taxi_zone_lookup.csv
FIXTURES_DIR = BACKEND_DIR / "fixtures"  # tracked aggregates and caches (same dir as app.db seeds)

# Confirm-check C2: TLC zone 186 = "Manhattan, Penn Station/Madison Sq West, Yellow Zone".
# Source: https://d37ci6vzurychx.cloudfront.net/misc/taxi_zone_lookup.csv
TAXI_ZONE_ID = 186

# Confirm-check C5: common window. TLC yellow-taxi files run through 2026-08 (checked 2026-10-24 on
# https://www.nyc.gov/site/tlc/about/tlc-trip-record-data.page); Dewey ends 2026-09-21. Start is the
# spec's fallback train year (Oct 2024 to Sep 2025). Train = first TRAIN_DAYS days, holdout = the rest.
WINDOW_START = date(2024, 10, 1)
WINDOW_END = date(2026, 8, 31)
TRAIN_DAYS = 365
TRAIN_END = WINDOW_START + timedelta(days=TRAIN_DAYS - 1)  # 2025-09-30
HOLDOUT_START = TRAIN_END + timedelta(days=1)  # 2025-10-01

# Gap G2: business hours for rain_open_hours, local NY time, [open, close). Taxi runs 24h but
# uses the same hours so both businesses share one definition.
BUSINESS_HOURS = (11, 23)

# Rain flags (spec §4.4). Data-layer defaults, overridable per call with the matched contract's
# threshold. Kept out of `Thresholds` because that dataclass is mirrored by the Settings contract.
RAIN_THRESHOLD_IN = 0.01  # daily precipitation >= this is a `rain` day
RAIN_OPEN_HOURS_IN = 0.05  # precipitation within BUSINESS_HOURS >= this is `rain_open_hours` (basis rule)

# Weather points (Open-Meteo archive, tz America/New_York). Settlement default is Central Park,
# the station Kalshi NYC weather contracts name; markets passes its own coordinates when it has them.
MSG_LATLON = (40.7505, -73.9934)
SETTLEMENT_STATION_LATLON = (40.7789, -73.9692)
WEATHER_TZ = "America/New_York"

# Dewey filters (gap G8: 10121 is MSG's own ZIP).
MSG_ZIPS = ("10001", "10119", "10121")

# Gap G11: US federal holidays (observed dates) plus Christmas Eve and New Year's Eve, covering the
# window. 2026-07-04 falls on a Saturday, so both the observed Friday and the day itself are listed.
HOLIDAYS: frozenset[date] = frozenset(
    date.fromisoformat(d)
    for d in (
        # 2024
        "2024-01-01", "2024-01-15", "2024-02-19", "2024-05-27", "2024-06-19", "2024-07-04",
        "2024-09-02", "2024-10-14", "2024-11-11", "2024-11-28", "2024-12-24", "2024-12-25",
        "2024-12-31",
        # 2025
        "2025-01-01", "2025-01-20", "2025-02-17", "2025-05-26", "2025-06-19", "2025-07-04",
        "2025-09-01", "2025-10-13", "2025-11-11", "2025-11-27", "2025-12-24", "2025-12-25",
        "2025-12-31",
        # 2026
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-05-25", "2026-06-19", "2026-07-03",
        "2026-07-04", "2026-09-07", "2026-10-12", "2026-11-11", "2026-11-26", "2026-12-24",
        "2026-12-25", "2026-12-31",
    )
)

# C1-A5: plausible median daily metered-fare revenue for the zone (set after C2/C5 were confirmed).
TAXI_MEDIAN_BAND_USD = (20_000.0, 150_000.0)  # observed median ~68k (2024-10..2026-08)
# Gap G3: the taxi build fails if more than this share of window days have no trips.
MAX_MISSING_DAY_SHARE = 0.02


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
