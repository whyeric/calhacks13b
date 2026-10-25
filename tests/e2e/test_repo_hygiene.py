"""C8-A12 no_raw_data_tracked, C8-A13 secrets_not_tracked, C8-A14 public_naming."""

from __future__ import annotations

import csv
import io
import os
import subprocess
from pathlib import Path

import pytest

from conftest import BACKEND, REPO_ROOT

RAW_COLUMNS = {"visits_by_day", "placekey", "tpep_pickup_datetime"}
MAX_FIXTURE_PARQUET = 5 * 1024 * 1024
# A raw-shaped file is allowed only when it is visibly synthetic (a unit-test input, not data).
SYNTHETIC_PREFIX = "Synthetic"


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout


def tracked() -> list[str]:
    return [p for p in git("ls-files", "-z").split("\0") if p]


def _columns_and_frame(path: Path):
    if path.suffix == ".parquet":
        import pyarrow.parquet as pq

        t = pq.read_table(path)
        return [c.lower() for c in t.schema.names], t.to_pandas()
    with path.open(newline="") as f:
        header = next(csv.reader(f), [])
    return [c.strip().lower() for c in header], None


# --- C8-A12 -----------------------------------------------------------------------


def test_a12_no_raw_data_tracked():
    files = tracked()
    assert not [p for p in files if p == "data" or p.startswith("data/")], "raw data/ is tracked"

    parquets = [p for p in files if p.endswith(".parquet")]
    outside = [p for p in parquets if "fixtures/" not in p]
    assert not outside, f"parquet outside fixtures/: {outside}"
    big = [p for p in parquets if (REPO_ROOT / p).stat().st_size > MAX_FIXTURE_PARQUET]
    assert not big, f"fixture parquet over 5 MB: {big}"

    offenders = []
    for p in files:
        if not p.endswith((".parquet", ".csv")):
            continue
        cols, frame = _columns_and_frame(REPO_ROOT / p)
        raw = RAW_COLUMNS & set(cols)
        if not raw:
            continue
        names = None if frame is None else {str(c).lower(): c for c in frame.columns}.get("location_name")
        synthetic = frame is not None and names is not None and \
            frame[names].astype(str).str.startswith(SYNTHETIC_PREFIX).all() and len(frame) <= 50
        if not synthetic:
            offenders.append((p, sorted(raw)))
    assert not offenders, f"tracked files with raw Dewey/TLC columns: {offenders}"


def test_a12_fixture_series_are_aggregates():
    """No per-trip or per-weekly-visit rows: every tracked fixture series has one row per day
    (or per hour for the hourly weather), and nothing is keyed by store or trip."""
    import pyarrow.parquet as pq

    for p in tracked():
        if not (p.startswith("backend/fixtures/") and p.endswith(".parquet")):
            continue
        df = pq.read_table(REPO_ROOT / p).to_pandas()
        key = "date" if "date" in df.columns else "time"
        assert key in df.columns, f"{p}: no date/time key"
        assert df[key].is_unique, f"{p}: more than one row per {key} (not an aggregate)"
        assert not {"id_store", "placekey", "trip_id"} & {c.lower() for c in df.columns}, p


# --- C8-A13 -----------------------------------------------------------------------


def test_a13_secrets_not_tracked():
    files = set(tracked())
    assert ".gitignore" in files, ".gitignore must be tracked"
    assert ".env" not in files and not [p for p in files if p.endswith("/.env")]
    assert not [p for p in files if p.endswith((".db", ".db-wal", ".db-shm"))], "SQLite files tracked"
    for probe in (".env", "backend/hedge_desk.db", "hedge_desk.db", ".naming-denylist"):
        r = subprocess.run(["git", "check-ignore", "-q", "--no-index", probe], cwd=REPO_ROOT)
        assert r.returncode == 0, f"{probe} is not matched by .gitignore"


def test_a13_no_keys_outside_docs():
    # A key prefix, or the variable assigned a real-looking value (not "" or an empty example line).
    # Split so this file doesn't match itself.
    pattern = "sk-" + "ant-|ANTHROPIC_API_KEY" + "=[\"']?[A-Za-z0-9_-]{8,}"
    r = subprocess.run(["git", "grep", "-nE", pattern, "--", ".", ":(exclude)docs", ":(exclude)*.md",
                        ":(exclude).env.example"], cwd=REPO_ROOT, capture_output=True, text=True)
    assert r.returncode == 1, f"possible secrets in tracked files:\n{r.stdout}"
    example = (REPO_ROOT / ".env.example").read_text()
    assert ("sk-" + "ant-") not in example
    for line in example.splitlines():
        if line.startswith("ANTHROPIC_API_KEY="):
            assert line == "ANTHROPIC_API_KEY=", "the example must ship an empty key"


# --- C8-A14 -----------------------------------------------------------------------


def _denylist() -> list[str]:
    path = Path(os.environ.get("NAMING_DENYLIST", REPO_ROOT / ".naming-denylist"))
    if not path.exists():
        return []
    return [ln.strip() for ln in path.read_text().splitlines() if ln.strip() and not ln.startswith("#")]


def test_a14_fixtures_use_public_name():
    import json

    b = json.loads((BACKEND / "fixtures" / "businesses" / "restaurant.json").read_text())
    assert b["name"] == "Bar across from MSG"


def test_a14_public_naming(client):
    names = _denylist()
    if not names:
        pytest.skip("C8-A14: no .naming-denylist at the repo root (it is local and untracked); "
                    "create one with the real venue's name(s) to run this check")
    api_text = "".join(client.get(u).text for u in ("/businesses", "/businesses/restaurant/hedges",
                                                     "/businesses/restaurant/decisions",
                                                     "/businesses/restaurant/ledger"))
    for name in names:
        r = subprocess.run(["git", "grep", "-il", "-F", name], cwd=REPO_ROOT, capture_output=True, text=True)
        assert r.returncode == 1, f"denylisted name found in tracked files: {r.stdout.split()}"
        assert name.lower() not in api_text.lower(), "denylisted name in an API response"
