"""C8 end-to-end fixtures (issue #21).

Every test here runs with outbound sockets blocked and no Anthropic key:

* `socket.socket.connect` / `connect_ex` and `socket.getaddrinfo` refuse any non-loopback
  address and record the attempt in `BLOCKED`. The autouse `_no_network` fixture fails a test
  that made any attempt, even if the code under test swallowed the error.
* `ANTHROPIC_API_KEY` is empty and `DEMO_OFFLINE=1`, so the desk uses the fallback agent and
  Kalshi reads come from `backend/fixtures/kalshi_cache/` only.

Run with `make e2e` (from the repo root) or `cd backend && .venv/bin/python -m pytest ../tests/e2e`.
In-process tests pin the clock to the demo "as of" time (Sat 2026-10-24 19:00 UTC, desk week
Mon 2026-10-26), the week the committed Kalshi cache was warmed for.
"""

from __future__ import annotations

import ipaddress
import os
import socket
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
BACKEND = REPO_ROOT / "backend"
FIXTURES = BACKEND / "fixtures"
CACHE_DIR = FIXTURES / "kalshi_cache"
NOW = datetime(2026, 10, 24, 19, 0, tzinfo=timezone.utc)
DEMO_WEEK = "2026-10-26"

# Dewey-derived daily series are gitignored (license, D2): a fresh clone has neither file.
RESTAURANT_FILES = (FIXTURES / "restaurant_daily.parquet", FIXTURES / "msg_visits_daily.parquet")
HAS_RESTAURANT_DATA = all(p.exists() for p in RESTAURANT_FILES)

if str(BACKEND) not in sys.path:  # `app` importable when pytest is run from the repo root
    sys.path.insert(0, str(BACKEND))

# Settings are read from the environment (and .env files); pin the demo-relevant ones before
# `app` is imported anywhere.
os.environ["ANTHROPIC_API_KEY"] = ""
os.environ["ANTHROPIC_MODEL"] = ""
os.environ["DEMO_OFFLINE"] = "1"
os.environ.pop("OWNER_TOKEN", None)
os.environ.pop("CONTROLLER_TOKEN", None)

# --- socket blocker ------------------------------------------------------------

BLOCKED: list[str] = []
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_getaddrinfo = socket.getaddrinfo


def _is_loopback(host: object) -> bool:
    if host is None:
        return True
    h = host.decode() if isinstance(host, bytes) else str(host)
    if h in ("localhost", "", "testserver"):
        return True
    try:
        return ipaddress.ip_address(h.split("%")[0]).is_loopback
    except ValueError:
        return False


def _addr_ok(sock: socket.socket, address: object) -> bool:
    if sock.family == getattr(socket, "AF_UNIX", None):
        return True
    host = address[0] if isinstance(address, tuple) else address
    return _is_loopback(host)


class NetworkBlocked(OSError):
    pass


def _connect(self, address):
    if not _addr_ok(self, address):
        BLOCKED.append(f"connect {address!r}")
        raise NetworkBlocked(f"e2e: outbound connection blocked: {address!r}")
    return _real_connect(self, address)


def _connect_ex(self, address):
    if not _addr_ok(self, address):
        BLOCKED.append(f"connect_ex {address!r}")
        raise NetworkBlocked(f"e2e: outbound connection blocked: {address!r}")
    return _real_connect_ex(self, address)


def _getaddrinfo(host, *args, **kwargs):
    if not _is_loopback(host):
        BLOCKED.append(f"getaddrinfo {host!r}")
        raise socket.gaierror(f"e2e: DNS blocked for {host!r}")
    return _real_getaddrinfo(host, *args, **kwargs)


socket.socket.connect = _connect
socket.socket.connect_ex = _connect_ex
socket.getaddrinfo = _getaddrinfo


@pytest.fixture(autouse=True)
def _no_network():
    start = len(BLOCKED)
    yield
    attempts = BLOCKED[start:]
    assert not attempts, f"outbound network attempted: {attempts}"


# --- in-process app ------------------------------------------------------------


@pytest.fixture
def app_env(tmp_path, monkeypatch):
    """Fresh SQLite + ledgers in tmp, `make seed` equivalent (businesses, sample week, books),
    real analysis and the real Kalshi markets backend replaying the committed cache."""
    from app import clock, config, db

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'e2e.db'}")
    monkeypatch.setenv("LEDGERS_DIR", str(tmp_path / "ledgers"))
    monkeypatch.setenv("MARKETS_BACKEND", "auto")
    monkeypatch.delenv("DEMO_SAMPLE_WEEK", raising=False)
    config.get_settings.cache_clear()
    config.get_thresholds.cache_clear()
    db.get_engine.cache_clear()
    monkeypatch.setattr(clock, "now", lambda: NOW)

    from app.books.seed import seed_books

    db.seed()
    (tmp_path / "statements").mkdir()
    # Bank statements go to tmp so the test never rewrites tracked fixtures; reconcile reads
    # the committed ones (test_reconcile checks they are identical).
    seed_books(ledger_dir=tmp_path / "ledgers", out_dir=tmp_path / "statements")
    yield tmp_path
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()


@pytest.fixture
def client(app_env):
    from fastapi.testclient import TestClient

    from app.main import app

    with TestClient(app) as c:
        yield c


def run_desk(client, business_id: str, timeout: float = 60.0) -> dict:
    r = client.post(f"/businesses/{business_id}/desk/run", json={})
    assert r.status_code == 202, r.text
    run_id = r.json()["run_id"]
    end = time.monotonic() + timeout
    while time.monotonic() < end:
        body = client.get(f"/runs/{run_id}").json()
        if body["status"] in ("done", "failed"):
            return body
        time.sleep(0.05)
    raise AssertionError(f"desk run {run_id} did not finish in {timeout}s")


def run_entries(client, business_id: str, run_id: str) -> list[dict]:
    return [e for e in client.get(f"/businesses/{business_id}/decisions", params={"limit": 500}).json()
            if e["run_id"] == run_id]
