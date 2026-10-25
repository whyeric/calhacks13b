"""Per-business feature table, one row per calendar day (spec §4.4).

Built from tracked fixtures only: taxi or restaurant revenue, MSG weather, Knicks/Rangers schedule
CSVs, and (when the Dewey build has produced it) MSG visit spikes. Gap G4: `msg_event = home_game OR
spike`; without `msg_visits_daily.parquet` it is `home_game` alone. The restaurant table needs
`restaurant_daily.parquet` from the Dewey build and raises `FileNotFoundError` without it.

The settlement flag for `fair` (CONTRACTS R17) comes from the station series, not the business's own
weather: `add_settlement(df, ...)` adds `settle_rain` (and `settle_hot` = station tmax > strike, given one), then
`event_frequency(df, "settle_rain")` is p̂ on `train` only.
"""

from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from app import config
from app.data import sports, taxi, weather

COLUMNS = [
    "date", "revenue", "dow", "doy", "is_holiday", "msg_event", "home_game", "home_win",
    "rain", "rain_open_hours", "tmax", "estimated",
]
BUSINESSES = ("taxi", "restaurant")
RESTAURANT_FIXTURE = "restaurant_daily.parquet"
MSG_VISITS_FIXTURE = "msg_visits_daily.parquet"


def _revenue(business_id: str, fixtures_dir: Path) -> pd.DataFrame:
    if business_id == "taxi":
        return taxi.load(fixtures_dir)[["date", "revenue"]]
    if business_id == "restaurant":
        path = fixtures_dir / RESTAURANT_FIXTURE
        if not path.exists():
            raise FileNotFoundError(f"restaurant fixture missing: {path} (built by the Dewey pipeline)")
        df = pd.read_parquet(path)
        df["date"] = pd.to_datetime(df["date"]).dt.date
        return df.rename(columns={"revenue_est": "revenue"})[["date", "revenue"]]
    raise ValueError(f"unknown business_id {business_id!r}; expected one of {BUSINESSES}")


def _spikes(fixtures_dir: Path) -> pd.Series | None:
    path = fixtures_dir / MSG_VISITS_FIXTURE
    if not path.exists():
        return None
    df = pd.read_parquet(path)
    return pd.Series(df["spike"].astype(bool).to_numpy(), index=pd.to_datetime(df["date"]).dt.date)


def build(
    business_id: str,
    rain_threshold: float | None = None,
    hours: tuple[int, int] = config.BUSINESS_HOURS,
    *,
    open_hours_threshold: float | None = None,
    end: date | None = None,
    fixtures_dir: Path = config.FIXTURES_DIR,
) -> pd.DataFrame:
    """Feature table for "taxi" or "restaurant", with `split`. Thresholds default to `config.RAIN_*`."""
    rev = _revenue(business_id, fixtures_dir)
    start = max(config.WINDOW_START, rev["date"].min())
    stop = min(config.WINDOW_END, rev["date"].max(), end or config.WINDOW_END)
    rev = rev[(rev["date"] >= start) & (rev["date"] <= stop)]

    w = weather.load_weather(*config.MSG_LATLON, start, stop, cache_dir=fixtures_dir)
    wf = weather.flags(w, rain_threshold, open_hours_threshold, hours)
    games, _ = sports.msg_games(start, stop, fixtures_dir=fixtures_dir, offline=True)

    df = pd.DataFrame({"date": pd.date_range(start, stop, freq="D").date})
    df = df.merge(rev, on="date", how="left").merge(games, on="date", how="left").merge(wf, on="date", how="left")
    if df.isna().any().any():
        bad = df.columns[df.isna().any()].tolist()
        raise ValueError(f"{business_id}: missing inputs for {bad} between {start} and {stop}")

    df["revenue"] = df["revenue"].astype("float64")
    df = df.join(calendar(df["date"]))
    spikes = _spikes(fixtures_dir)
    spike = df["date"].map(spikes).fillna(False).astype(bool) if spikes is not None else False
    df["msg_event"] = df["home_game"] | spike
    df["estimated"] = business_id == "restaurant"
    for col in ("home_game", "home_win", "rain", "rain_open_hours", "msg_event", "is_holiday", "estimated"):
        df[col] = df[col].astype(bool)
    df["tmax"] = df["tmax"].astype("float64")
    return split(df[COLUMNS])


def calendar(dates: pd.Series) -> pd.DataFrame:
    """`dow` (Mon=0), `doy` (1..366) and `is_holiday` (config list only) for a column of dates."""
    ts = pd.to_datetime(dates)
    return pd.DataFrame(
        {
            "dow": ts.dt.day_of_week.astype("int64"),
            "doy": ts.dt.day_of_year.astype("int64"),
            "is_holiday": dates.isin(config.HOLIDAYS),
        },
        index=dates.index,
    )


def split(df: pd.DataFrame) -> pd.DataFrame:
    """`split` = "train" for the first `TRAIN_DAYS` calendar days of the table, "holdout" after."""
    out = df.sort_values("date").reset_index(drop=True).copy()
    cutoff = pd.Timestamp(out["date"].iloc[0]) + pd.Timedelta(days=config.TRAIN_DAYS - 1)
    out["split"] = (pd.to_datetime(out["date"]) <= cutoff).map({True: "train", False: "holdout"})
    return out


def event_frequency(df: pd.DataFrame, col: str) -> float:
    """p̂: share of `train` days where `col` is true."""
    if "split" not in df.columns:
        df = split(df)
    train = df.loc[df["split"] == "train", col]
    if train.empty:
        raise ValueError("no train rows")
    return float(train.astype(bool).mean())


def hot(df: pd.DataFrame, strike: float) -> pd.Series:
    """`hot = tmax >= strike` (spec §5); the strike comes from the matched temperature contract."""
    return df["tmax"] >= strike


def add_settlement(
    df: pd.DataFrame,
    lat: float = config.SETTLEMENT_STATION_LATLON[0],
    lon: float = config.SETTLEMENT_STATION_LATLON[1],
    *,
    rain_threshold: float | None = None,
    strike: float | None = None,
    fixtures_dir: Path = config.FIXTURES_DIR,
) -> pd.DataFrame:
    """Adds the contract's settlement flags from the station series: `settle_rain`, and `settle_hot` given a strike."""
    start, stop = df["date"].min(), df["date"].max()
    w = weather.load_weather(lat, lon, start, stop, cache_dir=fixtures_dir)
    f = weather.flags(w, rain_threshold).set_index("date")
    out = df.copy()
    out["settle_rain"] = out["date"].map(f["rain"]).astype(bool)
    if strike is not None:
        # KXHIGHNY pays only when the high is strictly above the strike (same rule as app/stats).
        out["settle_hot"] = out["date"].map(f["tmax"]) > strike
    return out


def example_rows(business_id: str, n: int = 5, fixtures_dir: Path = config.FIXTURES_DIR) -> list[dict]:
    """`n` JSON-ready rows for `fixtures/features/{business}_rows.json`: the first dry plain day, rain day,
    open-hours rain day, home win and holiday, so consumers see every flag set at least once."""
    df = build(business_id, fixtures_dir=fixtures_dir)
    plain = ~(df["rain"] | df["home_game"] | df["is_holiday"])
    picks = [plain, df["rain"] & ~df["rain_open_hours"], df["rain_open_hours"], df["home_win"], df["is_holiday"]]
    idx = {mask[mask].index[0] for mask in picks if mask.any()}
    idx = sorted(idx | set(df.index.difference(list(idx))[: max(0, n - len(idx))]))[:n]
    rows = df.loc[idx].copy()
    rows["date"] = rows["date"].map(date.isoformat)
    return rows.to_dict(orient="records")
