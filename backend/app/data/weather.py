"""Daily and hourly weather from the Open-Meteo archive, cached to parquet (spec §4.3).

Units come back as requested: precipitation in inches, temperature in °F, timestamps local
`America/New_York`. Two series share one schema: MSG (the business's own weather) and the
settlement station named by the matched contract (Central Park by default; markets passes its own
coordinates). Caches: `fixtures/weather_{name}.parquet` (daily) and `weather_{name}_hourly.parquet`.

Open-Meteo hourly values are the total over the hour ending at the timestamp, so "within business
hours [open, close)" means stamps with open < hour <= close.

With `DEMO_OFFLINE=1` (or `offline=True`) nothing is fetched; a missing or short cache raises
`WeatherCacheMiss` naming the file.

Settlement record (research r3-noaa): Kalshi KXRAIN / KXHIGHNY settle on the NWS CLI report for
Central Park, which is NOAA GHCN-Daily station USW00094728. `load_ghcn` reads it from the committed
fixture `fixtures/ghcn_USW00094728.csv` (raw NCEI access-data CSV: PRCP inches, TMAX integer °F),
fetching from NCEI only when online and the fixture is short. Open-Meteo over-calls rain against
that record (40–47% wet days vs 31–38%) and disagrees on about 12% of days, so settlement flags and
p̂ use GHCN whenever it covers the dates (see `features.add_settlement`).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import pandas as pd

from app import config

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
GHCN_STATION = "USW00094728"  # Central Park; the NWS CLINYC report Kalshi NYC weather contracts settle on
GHCN_URL = "https://www.ncei.noaa.gov/access/services/data/v1"
GHCN_FIXTURE = f"ghcn_{GHCN_STATION}.csv"
DAILY_COLUMNS = ["date", "precipitation_sum", "temperature_2m_max"]
HOURLY_COLUMNS = ["time", "precipitation"]


class WeatherCacheMiss(FileNotFoundError):
    pass


@dataclass(frozen=True)
class Weather:
    daily: pd.DataFrame  # date, precipitation_sum (in), temperature_2m_max (°F)
    hourly: pd.DataFrame  # time (local, naive), precipitation (in)
    source: str  # "cache" | "open-meteo"


def series_name(lat: float, lon: float) -> str:
    if (lat, lon) == config.MSG_LATLON:
        return "msg"
    if (lat, lon) == config.SETTLEMENT_STATION_LATLON:
        return "station"
    return f"{lat:.4f}_{lon:.4f}"


def cache_paths(name: str, cache_dir: Path) -> tuple[Path, Path]:
    return cache_dir / f"weather_{name}.parquet", cache_dir / f"weather_{name}_hourly.parquet"


def request_params(lat: float, lon: float, start: date, end: date) -> dict[str, str]:
    return {
        "latitude": str(lat),
        "longitude": str(lon),
        "start_date": start.isoformat(),
        "end_date": end.isoformat(),
        "daily": "precipitation_sum,temperature_2m_max",
        "hourly": "precipitation",
        "temperature_unit": "fahrenheit",
        "precipitation_unit": "inch",
        "timezone": config.WEATHER_TZ,
    }


def parse(payload: dict) -> Weather:
    """Open-Meteo archive JSON to frames. Values are kept exactly as returned."""
    d, h = payload["daily"], payload["hourly"]
    daily = pd.DataFrame(
        {
            "date": pd.to_datetime(d["time"]).date,
            "precipitation_sum": pd.Series(d["precipitation_sum"], dtype="float64"),
            "temperature_2m_max": pd.Series(d["temperature_2m_max"], dtype="float64"),
        }
    )
    hourly = pd.DataFrame(
        {"time": pd.to_datetime(h["time"]), "precipitation": pd.Series(h["precipitation"], dtype="float64")}
    )
    return Weather(daily=daily, hourly=hourly, source="open-meteo")


def fetch(lat: float, lon: float, start: date, end: date, client: httpx.Client | None = None) -> Weather:
    own = client is None
    client = client or httpx.Client(timeout=60)
    try:
        resp = client.get(ARCHIVE_URL, params=request_params(lat, lon, start, end))
        resp.raise_for_status()
        return parse(resp.json())
    finally:
        if own:
            client.close()


def _slice(w: Weather, start: date, end: date, source: str) -> Weather:
    daily = w.daily[(w.daily["date"] >= start) & (w.daily["date"] <= end)].reset_index(drop=True)
    t = w.hourly["time"].dt.date
    hourly = w.hourly[(t >= start) & (t <= end)].reset_index(drop=True)
    return Weather(daily=daily, hourly=hourly, source=source)


def _read_cache(name: str, cache_dir: Path) -> Weather | None:
    d_path, h_path = cache_paths(name, cache_dir)
    if not (d_path.exists() and h_path.exists()):
        return None
    daily = pd.read_parquet(d_path)
    daily["date"] = pd.to_datetime(daily["date"]).dt.date
    hourly = pd.read_parquet(h_path)
    return Weather(daily=daily[DAILY_COLUMNS], hourly=hourly[HOURLY_COLUMNS], source="cache")


def _covers(w: Weather, start: date, end: date) -> bool:
    return len(w.daily) > 0 and w.daily["date"].min() <= start and w.daily["date"].max() >= end


def load_weather(
    lat: float = config.MSG_LATLON[0],
    lon: float = config.MSG_LATLON[1],
    start: date = config.WINDOW_START,
    end: date = config.WINDOW_END,
    *,
    name: str | None = None,
    cache_dir: Path = config.FIXTURES_DIR,
    offline: bool | None = None,
    client: httpx.Client | None = None,
) -> Weather:
    """Cached weather for [start, end]; fetches and writes the cache only when online and short."""
    name = name or series_name(lat, lon)
    if offline is None:
        offline = config.get_settings().demo_offline
    cached = _read_cache(name, cache_dir)
    if cached is not None and _covers(cached, start, end):
        return _slice(cached, start, end, "cache")
    if offline:
        d_path, _ = cache_paths(name, cache_dir)
        why = "missing" if cached is None else "does not cover the requested dates"
        raise WeatherCacheMiss(f"weather cache {d_path} {why} ({start}..{end}) and offline mode is on")

    w = fetch(lat, lon, start, end, client)
    if w.daily[["precipitation_sum", "temperature_2m_max"]].isna().any().any():
        raise ValueError(f"Open-Meteo returned nulls for {name} in {start}..{end}")
    cache_dir.mkdir(parents=True, exist_ok=True)
    d_path, h_path = cache_paths(name, cache_dir)
    w.daily.to_parquet(d_path, index=False)
    w.hourly.to_parquet(h_path, index=False)
    return _slice(w, start, end, "open-meteo")


def flags(
    w: Weather,
    rain_threshold: float | None = None,
    open_hours_threshold: float | None = None,
    hours: tuple[int, int] = config.BUSINESS_HOURS,
) -> pd.DataFrame:
    """Per date: `rain` (daily total >= threshold), `rain_open_hours` (open-hours total >= threshold), `tmax`."""
    rain_threshold = config.RAIN_THRESHOLD_IN if rain_threshold is None else rain_threshold
    open_hours_threshold = config.RAIN_OPEN_HOURS_IN if open_hours_threshold is None else open_hours_threshold
    open_h, close_h = hours

    hr = w.hourly
    hour = hr["time"].dt.hour
    # Hour-ending stamps: 00:00 closes the previous day's last hour.
    ending_day = (hr["time"] - pd.Timedelta(hours=1)).dt.date
    ending_hour = hour.where(hour != 0, 24)
    in_open = (ending_hour > open_h) & (ending_hour <= close_h)
    open_total = hr.loc[in_open, "precipitation"].groupby(ending_day[in_open]).sum()

    out = pd.DataFrame({"date": w.daily["date"]})
    # Round away float noise from summing hourly inches before comparing with >=.
    out["rain"] = w.daily["precipitation_sum"].round(6) >= rain_threshold
    out["rain_open_hours"] = out["date"].map(open_total).fillna(0.0).round(6) >= open_hours_threshold
    out["tmax"] = w.daily["temperature_2m_max"].astype("float64")
    return out


# --- NOAA GHCN-Daily (settlement record) -------------------------------------------


def ghcn_params(start: date, end: date, station: str = GHCN_STATION) -> dict[str, str]:
    return {
        "dataset": "daily-summaries", "stations": station, "startDate": start.isoformat(),
        "endDate": end.isoformat(), "dataTypes": "PRCP,TMAX", "units": "standard", "format": "csv",
    }


def parse_ghcn(text: str) -> pd.DataFrame:
    """NCEI access-data CSV (units=standard) to `date, prcp (in), tmax (°F)`. Trace is already 0."""
    from io import StringIO

    raw = pd.read_csv(StringIO(text), dtype={"STATION": str})
    return pd.DataFrame({
        "date": pd.to_datetime(raw["DATE"]).dt.date,
        "prcp": pd.to_numeric(raw["PRCP"], errors="coerce").astype("float64"),
        "tmax": pd.to_numeric(raw["TMAX"], errors="coerce").astype("float64"),
    }).dropna().sort_values("date").reset_index(drop=True)


def fetch_ghcn(start: date, end: date, client: httpx.Client | None = None) -> str:
    own = client is None
    client = client or httpx.Client(timeout=120)
    try:
        resp = client.get(GHCN_URL, params=ghcn_params(start, end))
        resp.raise_for_status()
        return resp.text
    finally:
        if own:
            client.close()


def load_ghcn(
    start: date = config.WINDOW_START,
    end: date = config.WINDOW_END,
    *,
    cache_dir: Path = config.FIXTURES_DIR,
    offline: bool | None = None,
    client: httpx.Client | None = None,
) -> pd.DataFrame:
    """Central Park GHCN-Daily rows in [start, end] (may have gaps; callers check coverage).

    Reads `fixtures/ghcn_USW00094728.csv`; when online and the fixture misses dates, fetches the
    range from NCEI and rewrites the fixture. Offline with no fixture raises `WeatherCacheMiss`.
    """
    if offline is None:
        offline = config.get_settings().demo_offline
    path = cache_dir / GHCN_FIXTURE
    df = parse_ghcn(path.read_text()) if path.exists() else None
    covered = df is not None and len(df) and df["date"].min() <= start and df["date"].max() >= end
    if not covered and not offline:
        fetched = parse_ghcn(fetch_ghcn(start, end, client))
        if len(fetched):
            merged = pd.concat([d for d in (df, fetched) if d is not None])
            df = merged.drop_duplicates("date", keep="last").sort_values("date").reset_index(drop=True)
            cache_dir.mkdir(parents=True, exist_ok=True)
            pd.DataFrame({
                "STATION": GHCN_STATION, "DATE": [d.isoformat() for d in df["date"]],
                "PRCP": df["prcp"].map("{:.2f}".format), "TMAX": df["tmax"].map("{:.0f}".format),
            }).to_csv(path, index=False)
    if df is None:
        raise WeatherCacheMiss(f"GHCN fixture {path} missing and offline mode is on")
    return df[(df["date"] >= start) & (df["date"] <= end)].reset_index(drop=True)


def ghcn_flags(g: pd.DataFrame, rain_threshold: float | None = None) -> pd.DataFrame:
    """Per date: `rain` (PRCP >= threshold, default 0.01 in = "more than 0 in") and `tmax` (°F)."""
    rain_threshold = config.RAIN_THRESHOLD_IN if rain_threshold is None else rain_threshold
    return pd.DataFrame({"date": g["date"], "rain": g["prcp"].round(6) >= rain_threshold, "tmax": g["tmax"]})


if __name__ == "__main__":
    for lat, lon in (config.MSG_LATLON, config.SETTLEMENT_STATION_LATLON):
        w = load_weather(lat, lon, offline=False)
        print(series_name(lat, lon), w.source, len(w.daily), "days")
