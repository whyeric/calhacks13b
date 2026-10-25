"""C1-A12..A15: Open-Meteo parsing, rain flags, cache-only loads, settlement station."""

import json
from datetime import date
from pathlib import Path

import httpx
import pandas as pd
import pytest

from app import config
from app.data import weather

FIX = Path(__file__).parent / "fixtures"


def _payload(days: list[str], precip_sum: list[float], tmax: list[float], hourly: dict[str, float] | None = None) -> dict:
    """Open-Meteo-shaped payload; `hourly` maps "YYYY-MM-DDTHH:00" to inches, other hours 0."""
    hourly = hourly or {}
    times = [f"{d}T{h:02d}:00" for d in days for h in range(24)]
    return {
        "daily": {"time": days, "precipitation_sum": precip_sum, "temperature_2m_max": tmax},
        "hourly": {"time": times, "precipitation": [hourly.get(t, 0.0) for t in times]},
    }


def test_weather_parse_and_units():  # C1-A12
    raw = json.loads((FIX / "open_meteo_msg_20241001.json").read_text())
    assert raw["daily_units"]["precipitation_sum"] == "inch"
    assert raw["daily_units"]["temperature_2m_max"] == "°F"
    w = weather.parse(raw)
    assert list(w.daily.columns) == weather.DAILY_COLUMNS
    assert w.daily["temperature_2m_max"].tolist() == raw["daily"]["temperature_2m_max"]
    assert w.daily["precipitation_sum"].tolist() == raw["daily"]["precipitation_sum"]
    assert len(w.hourly) == 72


def test_rain_threshold_boundary_and_override():  # C1-A12
    w = weather.parse(_payload(["2024-06-01", "2024-06-02"], [0.0099, 0.01], [80.0, 81.0]))
    assert weather.flags(w)["rain"].tolist() == [False, True]
    assert weather.flags(w, rain_threshold=0.005)["rain"].tolist() == [True, True]
    assert weather.flags(w, rain_threshold=0.02)["rain"].tolist() == [False, False]


def test_rain_open_hours_flag():  # C1-A13
    days = ["2024-06-01", "2024-06-02", "2024-06-03"]
    hourly = {
        "2024-06-01T13:00": 0.02, "2024-06-01T18:00": 0.02,  # 0.04 in open hours
        "2024-06-02T13:00": 0.03, "2024-06-02T20:00": 0.02,  # 0.05 in open hours
        "2024-06-03T06:00": 0.30,  # morning only
    }
    w = weather.parse(_payload(days, [0.04, 0.05, 0.30], [70.0, 70.0, 70.0], hourly))
    f = weather.flags(w)
    assert f["rain_open_hours"].tolist() == [False, True, False]
    assert f["rain"].tolist() == [True, True, True]


def test_weather_cache_no_live_fetch(tmp_path, monkeypatch):  # C1-A14
    w = weather.parse(_payload(["2024-06-01", "2024-06-02"], [0.0, 0.2], [70.0, 71.0]))
    d_path, h_path = weather.cache_paths("msg", tmp_path)
    w.daily.to_parquet(d_path, index=False)
    w.hourly.to_parquet(h_path, index=False)

    def boom(*a, **k):
        raise AssertionError("network used")

    monkeypatch.setattr(weather, "fetch", boom)
    monkeypatch.setattr(httpx.Client, "get", boom)
    got = weather.load_weather(*config.MSG_LATLON, date(2024, 6, 1), date(2024, 6, 2), cache_dir=tmp_path, offline=False)
    assert got.source == "cache" and len(got.daily) == 2

    empty = tmp_path / "empty"
    with pytest.raises(weather.WeatherCacheMiss, match="weather_msg.parquet"):
        weather.load_weather(*config.MSG_LATLON, date(2024, 6, 1), date(2024, 6, 2), cache_dir=empty, offline=True)
    with pytest.raises(weather.WeatherCacheMiss, match="does not cover"):
        weather.load_weather(*config.MSG_LATLON, date(2024, 6, 1), date(2024, 6, 9), cache_dir=tmp_path, offline=True)


def test_settlement_station_series(tmp_path):  # C1-A15
    seen = {}
    payload = _payload(["2024-06-01"], [0.1], [75.0])

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, json=payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    lat, lon = config.SETTLEMENT_STATION_LATLON
    w = weather.load_weather(lat, lon, date(2024, 6, 1), date(2024, 6, 1), cache_dir=tmp_path, offline=False, client=client)
    assert (float(seen["latitude"]), float(seen["longitude"])) == (lat, lon)
    assert (float(seen["latitude"]), float(seen["longitude"])) != config.MSG_LATLON
    assert seen["precipitation_unit"] == "inch" and seen["temperature_unit"] == "fahrenheit"
    assert list(w.daily.columns) == weather.DAILY_COLUMNS
    assert (tmp_path / "weather_station.parquet").exists()


def test_checked_in_weather_caches_cover_window():
    for name in ("msg", "station"):
        w = weather.load_weather(start=config.WINDOW_START, end=config.WINDOW_END, name=name, offline=True)
        assert len(w.daily) == (config.WINDOW_END - config.WINDOW_START).days + 1
        assert not w.daily.isna().any().any()
        assert pd.api.types.is_datetime64_any_dtype(w.hourly["time"])


# --- NOAA GHCN-Daily, the KXRAIN / KXHIGHNY settlement record (research r3-noaa) ---

GHCN_CSV = (
    '"STATION","DATE","PRCP","TMAX"\n'
    '"USW00094728","2024-10-01","0.00","69"\n'
    '"USW00094728","2024-10-02","0.01","85"\n'
    '"USW00094728","2024-10-03","0.45","86"\n'
)


def test_ghcn_parse_and_flags():
    g = weather.parse_ghcn(GHCN_CSV)
    assert list(g.columns) == ["date", "prcp", "tmax"] and g["date"].iloc[0] == date(2024, 10, 1)
    f = weather.ghcn_flags(g)
    assert f["rain"].tolist() == [False, True, True]  # >= 0.01 in, i.e. "more than 0 in"; trace is 0
    assert f["tmax"].tolist() == [69.0, 85.0, 86.0]


def test_ghcn_fixture_covers_the_project_window_offline():
    g = weather.load_ghcn(offline=True)
    assert len(g) == (config.WINDOW_END - config.WINDOW_START).days + 1
    assert not g.isna().any().any()
    assert (config.FIXTURES_DIR / weather.GHCN_FIXTURE).stat().st_size < 100_000  # small, committed


def test_ghcn_offline_without_fixture_is_a_cache_miss(tmp_path):
    with pytest.raises(weather.WeatherCacheMiss):
        weather.load_ghcn(cache_dir=tmp_path, offline=True)


def test_ghcn_fetches_and_merges_when_online(tmp_path):
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.update(request.url.params)
        return httpx.Response(200, text=GHCN_CSV)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    g = weather.load_ghcn(date(2024, 10, 1), date(2024, 10, 3), cache_dir=tmp_path, offline=False, client=client)
    assert len(g) == 3 and seen["stations"] == weather.GHCN_STATION and seen["units"] == "standard"
    again = weather.load_ghcn(date(2024, 10, 1), date(2024, 10, 3), cache_dir=tmp_path, offline=True)
    assert again.equals(g)
