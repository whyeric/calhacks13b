"""Dewey (Advan weekly patterns) -> daily restaurant and MSG visit series (C1, issue #23).

Raw input (D3)
--------------
Repo-root `data/` (gitignored) holds two Advan-style weekly exports, one row per store-week,
columns BRAND, CITY, DATE_RANGE_START, DATE_RANGE_END, ID_STORE, LATITUDE, LONGITUDE,
LOCATION_NAME, NAICS_CODE, POSTAL_CODE, STREET_ADDRESS, TOP_CATEGORY, VISITS_BY_DAY,
VISIT_COUNTS. `VISITS_BY_DAY` is a JSON array string of 7 daily counts.

- restaurants folder: Manhattan restaurants & bars (~11.5k stores, ~1.6M rows).
- MSG folder: the arena alone (a single ID_STORE, NAICS 711211, 143 weeks).

Folder resolution, first hit wins:
1. `DEWEY_RESTAURANTS_DIR` / `DEWEY_MSG_DIR` (env or `.env`), absolute or relative to `data/`;
2. the names `manhattan_restaurants_bars_2024_2026` / `msg_arena_2024_2026` under `data/`;
3. auto-detect among `data/*/`: the folder whose parquet has one distinct ID_STORE is MSG,
   the other is restaurants. (On the original export the folders are the unlabeled UUIDs
   `01a16ff2-...` = restaurants and `01a16ff5-...` = MSG.)

Day alignment (G5)
------------------
DATE_RANGE_START is a naive local (America/New_York) Monday 00:00, and VISITS_BY_DAY[i] is the
local calendar day week_start + i. Overlapping or duplicated store-weeks are deduped so each
(store, date) appears once; the latest-starting week wins. Malformed arrays (not 7 ints, null,
unparseable JSON) are skipped and counted, or raise in strict mode; dates never shift.

Privacy (D2)
------------
Only daily aggregates leave this module, and they stay local: both output parquet files are
gitignored and rebuilt from `data/` with `make seed-data`, since the Dewey terms allow
publishing only summaries/insights (D2 pending). Tests use synthetic inputs only. The chosen restaurant is tracked by `place_id`, a
truncated sha256 of its ID_STORE (`CHOSEN_PLACE_ID`); a raw id override lives only in `.env`
(`DEWEY_PLACE_ID`), and no name, address, brand or coordinates are written anywhere.

CLI (run from backend/):
    python -m app.data.dewey rank            # print anonymized candidate ranking
    python -m app.data.dewey build           # write fixtures/{restaurant,msg_visits}_daily.parquet
"""

from __future__ import annotations

import argparse
import hashlib
import json
import logging
from collections.abc import Iterable
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd

from app.config import (
    DEWEY_START,
    FIXTURES_DIR,
    MSG_ZIPS,
    RAW_DATA_DIR,
    RESTAURANT_NAICS,
    SPIKE_MAD_K,
    SPIKE_WINDOW_DAYS,
    get_settings,
)

log = logging.getLogger(__name__)

RESTAURANTS_NAME = "manhattan_restaurants_bars_2024_2026"
MSG_NAME = "msg_arena_2024_2026"

# C3 choice (see README_dewey.md): opaque hash of the chosen bar's ID_STORE. DEWEY_PLACE_ID
# (raw id, .env only) overrides it.
CHOSEN_PLACE_ID = "p_afa556030e60"

# Kalshi MSG-event tickers whose underlying is MSG's own visit series.
TICKER_SOURCES = {"NBA-A": "msg"}

RAW_COLUMNS = ["ID_STORE", "POSTAL_CODE", "NAICS_CODE", "DATE_RANGE_START", "VISITS_BY_DAY"]
RESTAURANT_COLUMNS = ["date", "visits", "revenue_est", "estimated", "place_id"]
MSG_COLUMNS = ["date", "visits", "spike"]


class MalformedWeekError(ValueError):
    """A VISITS_BY_DAY value that is not exactly 7 non-negative integers."""


# ---------------------------------------------------------------- folders


def _parquet_glob(folder: Path) -> str:
    return str(folder / "*.parquet")


def _distinct_stores(folder: Path) -> int:
    import duckdb

    return duckdb.sql(f"select count(distinct ID_STORE) from '{_parquet_glob(folder)}'").fetchall()[0][0]


def resolve_dirs(data_dir: Path = RAW_DATA_DIR) -> tuple[Path, Path]:
    """Return (restaurants_dir, msg_dir); see module docstring for the order."""
    s = get_settings()

    def from_setting(value: str | None) -> Path | None:
        if not value:
            return None
        p = Path(value)
        return p if p.is_absolute() else data_dir / p

    rest = from_setting(s.dewey_restaurants_dir) or _if_dir(data_dir / RESTAURANTS_NAME)
    msg = from_setting(s.dewey_msg_dir) or _if_dir(data_dir / MSG_NAME)
    if rest is None or msg is None:
        candidates = [d for d in sorted(data_dir.iterdir()) if d.is_dir() and any(d.glob("*.parquet"))]
        candidates = [d for d in candidates if d not in (rest, msg)]
        for d in candidates:
            if _distinct_stores(d) == 1:
                msg = msg or d
            else:
                rest = rest or d
    if rest is None or msg is None:
        raise FileNotFoundError(
            f"cannot find Dewey folders under {data_dir}; set DEWEY_RESTAURANTS_DIR and DEWEY_MSG_DIR"
        )
    return rest, msg


def _if_dir(p: Path) -> Path | None:
    return p if p.is_dir() else None


def read_weekly(
    folder: Path,
    zips: Iterable[str] | None = MSG_ZIPS,
    naics: Iterable[str] | None = RESTAURANT_NAICS,
    start: date = DEWEY_START,
) -> pd.DataFrame:
    """Read raw weekly rows (only RAW_COLUMNS, never names/addresses) with filters pushed down."""
    import duckdb

    where = [f"DATE_RANGE_START >= DATE '{start.isoformat()}'"]
    if zips is not None:
        where.append("POSTAL_CODE IN (" + ",".join(f"'{z}'" for z in zips) + ")")
    if naics is not None:
        where.append("NAICS_CODE IN (" + ",".join(f"'{n}'" for n in naics) + ")")
    sql = f"select {', '.join(RAW_COLUMNS)} from '{_parquet_glob(folder)}' where {' and '.join(where)}"
    return duckdb.sql(sql).df()


# ---------------------------------------------------------------- weekly -> daily


def filter_weekly(
    df: pd.DataFrame,
    zips: Iterable[str] = MSG_ZIPS,
    naics: Iterable[str] = RESTAURANT_NAICS,
    start: date = DEWEY_START,
) -> pd.DataFrame:
    """ZIP in list AND NAICS in list AND week_start >= start (spec §4.2)."""
    week_start = pd.to_datetime(df["DATE_RANGE_START"])
    keep = (
        df["POSTAL_CODE"].astype(str).isin(set(zips))
        & df["NAICS_CODE"].astype(str).isin(set(naics))
        & (week_start >= pd.Timestamp(start))
    )
    return df[keep]


def rows_for_ticker(ticker: str, restaurants: pd.DataFrame, msg: pd.DataFrame) -> pd.DataFrame:
    """Route a Kalshi MSG-event ticker to the series that settles it."""
    source = TICKER_SOURCES.get(ticker)
    if source == "msg":
        return msg
    raise KeyError(f"no Dewey series for ticker {ticker!r}")


def parse_visits_by_day(value) -> list[int]:
    """Accept a 7-item list/array or the raw JSON array string; raise MalformedWeekError otherwise."""
    if value is None or (isinstance(value, float) and np.isnan(value)):
        raise MalformedWeekError("visits_by_day is null")
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except json.JSONDecodeError as e:
            raise MalformedWeekError(f"visits_by_day is not a JSON array: {value[:40]!r}") from e
    if not isinstance(value, (list, tuple, np.ndarray)):
        raise MalformedWeekError(f"visits_by_day has type {type(value).__name__}, expected 7-item array")
    if len(value) != 7:
        raise MalformedWeekError(f"visits_by_day has {len(value)} values, expected 7")
    out = []
    for v in value:
        if v is None or isinstance(v, (str, bool)) or float(v) != int(v) or int(v) < 0:
            raise MalformedWeekError(f"visits_by_day has a non-count value {v!r}")
        out.append(int(v))
    return out


def explode_weeks(df: pd.DataFrame, strict: bool = False) -> pd.DataFrame:
    """Weekly rows -> (store_id, date, visits), one row per store-day, deduped.

    Malformed weeks are skipped with a logged count (or raise if `strict`).
    """
    records = []
    skipped = 0
    for store, week_start, raw in zip(df["ID_STORE"], df["DATE_RANGE_START"], df["VISITS_BY_DAY"]):
        try:
            days = parse_visits_by_day(raw)
        except MalformedWeekError as e:
            if strict:
                raise MalformedWeekError(f"store {_hash(store)} week {week_start}: {e}") from e
            skipped += 1
            continue
        d0 = pd.Timestamp(week_start).date()
        records.extend((store, d0 + timedelta(days=i), v, d0) for i, v in enumerate(days))
    if skipped:
        log.warning("dewey: skipped %d malformed week(s)", skipped)
    out = pd.DataFrame(records, columns=["store_id", "date", "visits", "week_start"])
    # Overlapping weeks: keep the most recent week's value for each store-day.
    out = out.sort_values(["store_id", "date", "week_start"]).drop_duplicates(["store_id", "date"], keep="last")
    out.attrs["skipped_weeks"] = skipped
    return out.drop(columns="week_start").reset_index(drop=True)


# ---------------------------------------------------------------- series


def spike_flags(visits: pd.Series, window: int = SPIKE_WINDOW_DAYS, k: float = SPIKE_MAD_K) -> pd.Series:
    """visits > median + k * MAD of the previous `window` days. Past-only: day t sees t-window..t-1.

    The first days (fewer than window // 2 of history) are never spikes.
    """
    past = visits.astype(float).shift(1)
    min_periods = max(1, window // 2)
    med = past.rolling(window, min_periods=min_periods).median()
    mad = past.rolling(window, min_periods=min_periods).apply(
        lambda w: np.median(np.abs(w - np.median(w))), raw=True
    )
    return (visits > med + k * mad).fillna(False).astype(bool)


def _hash(store_id: str) -> str:
    return "p_" + hashlib.sha256(str(store_id).encode()).hexdigest()[:12]


def place_hash(store_id: str) -> str:
    """Opaque, stable place id for a raw ID_STORE."""
    return _hash(store_id)


def _full_calendar(daily: pd.DataFrame) -> pd.DataFrame:
    """Reindex to every day between min and max; fail if more than 2% are missing (G3)."""
    days = pd.date_range(min(daily["date"]), max(daily["date"]), freq="D").date
    out = daily.set_index("date").reindex(days)
    missing = int(out["visits"].isna().sum())
    if missing > 0.02 * len(days):
        raise ValueError(f"{missing} of {len(days)} days missing (> 2%)")
    if missing:
        log.warning("dewey: %d missing day(s) dropped (no interpolation)", missing)
    return out.dropna(subset=["visits"]).rename_axis("date").reset_index()


def build_msg_daily(msg_weekly: pd.DataFrame, strict: bool = False) -> pd.DataFrame:
    daily = explode_weeks(msg_weekly, strict=strict)
    daily = daily.groupby("date", as_index=False)["visits"].sum()
    daily = _full_calendar(daily)
    daily["visits"] = daily["visits"].astype("int64")
    daily["spike"] = spike_flags(daily["visits"])
    return daily[MSG_COLUMNS]


def build_restaurant_daily(
    store_daily: pd.DataFrame, avg_check_usd: Decimal | None = None
) -> pd.DataFrame:
    """One store's (date, visits) -> restaurant_daily schema. `estimated` is always True (I6)."""
    if store_daily["store_id"].nunique() != 1:
        raise ValueError("build_restaurant_daily expects exactly one store")
    avg = Decimal(avg_check_usd if avg_check_usd is not None else get_settings().avg_check_usd)
    store = store_daily["store_id"].iloc[0]
    daily = _full_calendar(store_daily[["date", "visits"]])
    daily["visits"] = daily["visits"].astype("int64")
    daily["revenue_est"] = [float(Decimal(int(v)) * avg) for v in daily["visits"]]
    daily["estimated"] = True
    daily["place_id"] = place_hash(store)
    return daily[RESTAURANT_COLUMNS]


def rank_candidates(rest_daily: pd.DataFrame, msg_daily: pd.DataFrame) -> pd.DataFrame:
    """Rank stores by weekly visits and rise on MSG spike nights (C3). Anonymized ids only.

    `rise` = mean visits on spike days / mean visits on non-spike days of the same weekday.
    """
    span = (max(msg_daily["date"]) - min(msg_daily["date"])).days + 1
    m = rest_daily.merge(msg_daily[["date", "spike"]], on="date", how="inner")
    m["dow"] = pd.to_datetime(m["date"]).dt.day_of_week
    base = m[~m["spike"]].groupby(["store_id", "dow"])["visits"].mean().rename("base")
    m = m.join(base, on=["store_id", "dow"])
    spikes = m[m["spike"]]
    rise = (spikes.groupby("store_id")["visits"].sum() / spikes.groupby("store_id")["base"].sum()).rename("rise")
    g = rest_daily.groupby("store_id")["visits"]
    out = pd.DataFrame({
        "days": g.size(),
        "weekly_visits": g.mean() * 7,
        "median_daily": g.median(),
    }).join(rise)
    out["coverage"] = out["days"] / span
    eligible = (out["coverage"] >= 0.98) & (out["weekly_visits"] >= 200)
    out["eligible"] = eligible
    out["score"] = np.where(eligible, out["rise"], np.nan)
    out = out.sort_values(["eligible", "score", "weekly_visits"], ascending=False)
    out.index = [place_hash(s) for s in out.index]
    out.index.name = "place_id"
    return out


def _raw_id_for(place_id: str, store_ids: Iterable[str]) -> str:
    for s in store_ids:
        if place_hash(s) == place_id:
            return s
    raise KeyError(place_id)


# ---------------------------------------------------------------- build / CLI


def load_all(data_dir: Path = RAW_DATA_DIR) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(restaurant store-days near MSG, MSG daily series) from the raw folders."""
    rest_dir, msg_dir = resolve_dirs(data_dir)
    msg_daily = build_msg_daily(read_weekly(msg_dir, zips=None, naics=None))
    rest_daily = explode_weeks(read_weekly(rest_dir))
    return rest_daily, msg_daily


def build(out_dir: Path = FIXTURES_DIR, data_dir: Path = RAW_DATA_DIR) -> dict:
    rest_daily, msg_daily = load_all(data_dir)
    ranking = rank_candidates(rest_daily, msg_daily)
    store_ids = rest_daily["store_id"].unique()
    chosen_raw = get_settings().dewey_place_id or _raw_id_for(CHOSEN_PLACE_ID, store_ids)
    restaurant = build_restaurant_daily(rest_daily[rest_daily["store_id"] == chosen_raw])
    out_dir.mkdir(parents=True, exist_ok=True)
    restaurant.attrs, msg_daily.attrs = {}, {}
    restaurant.to_parquet(out_dir / "restaurant_daily.parquet", index=False)
    msg_daily.to_parquet(out_dir / "msg_visits_daily.parquet", index=False)
    return {"restaurant": restaurant, "msg": msg_daily, "ranking": ranking, "chosen_raw": chosen_raw}


def main(argv: list[str] | None = None) -> None:
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(message)s")
    parser = argparse.ArgumentParser(prog="python -m app.data.dewey")
    sub = parser.add_subparsers(dest="cmd", required=True)
    sub.add_parser("rank", help="print anonymized candidate ranking near MSG")
    p_build = sub.add_parser("build", help="write restaurant_daily and msg_visits_daily fixtures")
    p_build.add_argument("--out-dir", type=Path, default=FIXTURES_DIR)
    p_build.add_argument("--print-raw-id", action="store_true", help="print chosen ID_STORE for .env")
    args = parser.parse_args(argv)

    if args.cmd == "rank":
        rest_daily, msg_daily = load_all()
        print(rank_candidates(rest_daily, msg_daily).head(20).round(3).to_string())
        return
    res = build(args.out_dir)
    r, m = res["restaurant"], res["msg"]
    print(res["ranking"].head(10).round(3).to_string())
    print(f"restaurant {r['place_id'].iloc[0]}: {len(r)} days {r['date'].min()}..{r['date'].max()}, "
          f"median daily visits {r['visits'].median():.0f}")
    print(f"msg: {len(m)} days, {int(m['spike'].sum())} spike days")
    if args.print_raw_id:
        print(f"DEWEY_PLACE_ID={res['chosen_raw']}")


if __name__ == "__main__":
    main()
