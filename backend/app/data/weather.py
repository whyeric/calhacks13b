"""Daily and hourly weather from the Open-Meteo archive, cached to parquet (spec §4.3).

Units come back as requested: precipitation in inches, temperature in °F, timestamps local
`America/New_York`. Two series share one schema: MSG (the business's own weather) and the
settlement station named by the matched contract (Central Park by default; markets passes its own
coordinates). Caches: `fixtures/weather_{name}.parquet` (daily) and `weather_{name}_hourly.parquet`.

Open-Meteo hourly values are the total over the hour ending at the timestamp, so "within business
hours [open, close)" means stamps with open < hour <= close.

With `DEMO_OFFLINE=1` (or `offline=True`) nothing is fetched; a missing or short cache raises
`WeatherCacheMiss` naming the file.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from pathlib import Path

import httpx
import pandas as pd

from app import config

ARCHIVE_URL = "https://archive-api.open-meteo.com/v1/archive"
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


if __name__ == "__main__":
    for lat, lon in (config.MSG_LATLON, config.SETTLEMENT_STATION_LATLON):
        w = load_weather(lat, lon, offline=False)
        print(series_name(lat, lon), w.source, len(w.daily), "days")
