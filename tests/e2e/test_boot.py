"""C8-A1 fresh_clone_boots_offline and C8-A3 cold_start_time.

The "fresh clone" is a copy of exactly what git would give a new checkout of this tree:
`git ls-files --cached --others --exclude-standard` (tracked files plus new, not-ignored ones),
so no `.env`, no `*.db`, no ledgers, no gitignored Dewey parquet, no venv, no node_modules.
`make seed && make demo` then run in that copy with:

* sockets blocked in every Python process via a `sitecustomize` on PYTHONPATH that refuses
  non-loopback connects/DNS and logs each attempt (the test asserts the log stays empty);
* `ANTHROPIC_API_KEY` empty, no `.env`;
* the current interpreter as `PY` (installing a venv would need the network).

`make demo` runs with `DEMO_WEB=0` (API only): the Next.js production build takes longer than
the 20 s budget and needs `node_modules`. Set `E2E_WEB=1` to also boot the frontend (it
symlinks this checkout's `frontend/node_modules` into the copy) and time first page load.
"""

from __future__ import annotations

import json
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

import pytest

from conftest import REPO_ROOT

pytestmark = pytest.mark.slow

HEALTH_BUDGET_S = 20.0
ANALYZE_BUDGET_S = 5.0

SITECUSTOMIZE = '''
import ipaddress, os, socket
_log = os.environ["E2E_SOCKET_LOG"]
def _loop(host):
    h = host.decode() if isinstance(host, bytes) else str(host)
    if h in ("localhost", ""):
        return True
    try:
        return ipaddress.ip_address(h.split("%")[0]).is_loopback
    except ValueError:
        return False
def _record(what):
    with open(_log, "a") as f:
        f.write(f"{os.getpid()} {what}\\n")
_c, _cx, _g = socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo
def connect(self, a):
    if self.family != getattr(socket, "AF_UNIX", None) and not _loop(a[0] if isinstance(a, tuple) else a):
        _record(f"connect {a!r}"); raise OSError(f"e2e: blocked {a!r}")
    return _c(self, a)
def connect_ex(self, a):
    if self.family != getattr(socket, "AF_UNIX", None) and not _loop(a[0] if isinstance(a, tuple) else a):
        _record(f"connect_ex {a!r}"); raise OSError(f"e2e: blocked {a!r}")
    return _cx(self, a)
def getaddrinfo(host, *a, **k):
    if host is not None and not _loop(host):
        _record(f"getaddrinfo {host!r}"); raise socket.gaierror(f"e2e: DNS blocked {host!r}")
    return _g(host, *a, **k)
socket.socket.connect, socket.socket.connect_ex, socket.getaddrinfo = connect, connect_ex, getaddrinfo
'''


def _free_port() -> int:
    s = socket.socket()
    s.bind(("127.0.0.1", 0))
    port = s.getsockname()[1]
    s.close()
    return port


def _fresh_copy(dest: Path) -> Path:
    out = subprocess.run(["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
                         cwd=REPO_ROOT, check=True, capture_output=True, text=True).stdout
    for rel in filter(None, out.split("\0")):
        src = REPO_ROOT / rel
        if not src.is_file():  # deleted in the working tree
            continue
        target = dest / rel
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(src, target)
    return dest


_OPENER = urllib.request.build_opener(urllib.request.ProxyHandler({}))  # loopback only, ignore *_PROXY


def _http(method: str, url: str, body: dict | None = None, timeout: float = 30.0):
    data = None if body is None else json.dumps(body).encode()
    req = urllib.request.Request(url, data=data, method=method, headers={"content-type": "application/json"})
    try:
        with _OPENER.open(req, timeout=timeout) as r:
            return r.status, json.loads(r.read() or b"null")
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read() or b"null")


def _env(tmp: Path) -> dict[str, str]:
    site = tmp / "site"
    site.mkdir()
    (site / "sitecustomize.py").write_text(SITECUSTOMIZE)
    env = {k: v for k, v in os.environ.items()
           if k not in ("DATABASE_URL", "LEDGERS_DIR", "MARKETS_BACKEND", "DEMO_SAMPLE_WEEK", "OWNER_TOKEN",
                        "PYTHONPATH", "VIRTUAL_ENV")}
    env.update(ANTHROPIC_API_KEY="", ANTHROPIC_MODEL="", PYTHONPATH=str(site),
               E2E_SOCKET_LOG=str(tmp / "sockets.log"), NEXT_TELEMETRY_DISABLED="1", PYTHONDONTWRITEBYTECODE="1")
    return env


def _boot(tmp_path: Path, web: bool):
    repo = _fresh_copy(tmp_path / "clone")
    assert not (repo / ".env").exists() and not list((repo / "backend").glob("*.db"))
    if web:
        nm = REPO_ROOT / "frontend" / "node_modules"
        if not nm.is_dir():
            pytest.skip("E2E_WEB=1 needs frontend/node_modules in this checkout (make install)")
        (repo / "frontend" / "node_modules").symlink_to(nm)
    env = _env(tmp_path)
    port, web_port = _free_port(), _free_port()
    make = ["make", f"PY={sys.executable}", f"API_PORT={port}", f"WEB_PORT={web_port}",
            f"API_URL=http://127.0.0.1:{port}", f"DEMO_WEB={1 if web else 0}"]

    seed = subprocess.run([*make, "seed"], cwd=repo, env=env, capture_output=True, text=True, timeout=300)
    assert seed.returncode == 0, seed.stdout[-2000:] + seed.stderr[-2000:]
    for name in ("bank_statement.csv", "bank_statement_clean.csv", "bank_statement_restaurant.csv"):
        assert (repo / "backend/fixtures" / name).read_bytes() == (REPO_ROOT / "backend/fixtures" / name).read_bytes(), \
            f"make seed rewrote tracked {name} (must be deterministic)"

    t0 = time.monotonic()
    proc = subprocess.Popen([*make, "demo"], cwd=repo, env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                            text=True, start_new_session=True)
    return repo, env, proc, t0, port, web_port, tmp_path / "sockets.log"


def _stop(proc: subprocess.Popen) -> str:
    try:
        os.killpg(proc.pid, signal.SIGTERM)
    except ProcessLookupError:
        pass
    try:
        out, _ = proc.communicate(timeout=20)
    except subprocess.TimeoutExpired:
        os.killpg(proc.pid, signal.SIGKILL)
        out, _ = proc.communicate()
    return out or ""


def test_a1_a3_fresh_clone_boots_offline(tmp_path):
    repo, env, proc, t0, port, _wp, sock_log = _boot(tmp_path, web=False)
    base = f"http://127.0.0.1:{port}"
    try:
        healthy_at = None
        while time.monotonic() - t0 < 60:
            assert proc.poll() is None, "make demo exited early:\n" + _stop(proc)[-3000:]
            try:
                status, body = _http("GET", f"{base}/health", timeout=2)
                if status == 200:
                    healthy_at = time.monotonic() - t0
                    break
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            time.sleep(0.1)
        assert healthy_at is not None, "no /health 200 within 60 s"
        assert body["status"] == "ok" and body["offline"] is True and body["anthropic"] == "fallback"
        # A3: make demo -> first /health 200
        assert healthy_at < HEALTH_BUDGET_S, f"cold start {healthy_at:.1f}s > {HEALTH_BUDGET_S}s"

        status, businesses = _http("GET", f"{base}/businesses")
        assert status == 200 and sorted(b["id"] for b in businesses) == ["restaurant", "taxi"]
        assert (repo / "backend" / "hedge_desk.db").exists(), "the server is not running from the fresh copy"

        timings = {}
        for b in ("taxi", "restaurant"):
            t = time.monotonic()
            status, res = _http("POST", f"{base}/businesses/{b}/analyze", {})
            timings[b] = time.monotonic() - t
            if b == "taxi" or (repo / "backend/fixtures/restaurant_daily.parquet").exists():
                assert status == 200, res
            else:  # fresh clone: Dewey series are gitignored -> graceful 409
                assert status == 409 and res["error"]["code"] == "analysis_unavailable", res
            assert timings[b] < ANALYZE_BUDGET_S, f"analyze {b} took {timings[b]:.1f}s"
        print(f"\nC8-A3: /health 200 after {healthy_at:.2f}s; analyze " +
              ", ".join(f"{k} {v:.2f}s" for k, v in timings.items()))
    finally:
        out = _stop(proc)
    assert "Hedge Desk API ready" in out, out[-3000:]
    attempts = sock_log.read_text() if sock_log.exists() else ""
    assert not attempts, f"blocked socket attempts during boot:\n{attempts}"


@pytest.mark.skipif(os.environ.get("E2E_WEB") != "1", reason="set E2E_WEB=1 to boot the frontend too")
def test_a1_fresh_clone_serves_frontend(tmp_path):
    _repo, _env_, proc, t0, port, web_port, sock_log = _boot(tmp_path, web=True)
    try:
        ready = None
        while time.monotonic() - t0 < 600:
            assert proc.poll() is None, "make demo exited early:\n" + _stop(proc)[-3000:]
            try:
                with _OPENER.open(f"http://127.0.0.1:{web_port}/", timeout=5) as r:
                    if r.status == 200:
                        ready = time.monotonic() - t0
                        break
            except (urllib.error.URLError, ConnectionError, OSError):
                pass
            time.sleep(0.5)
        assert ready is not None, "frontend never served /"
        print(f"\nC8-A1 (web): first page 200 after {ready:.1f}s (includes next build)")
        time.sleep(2)  # make's own readiness loop polls every 0.5 s; let it print "Hedge Desk ready"
    finally:
        out = _stop(proc)
    assert "Hedge Desk ready" in out, out[-3000:]
    attempts = sock_log.read_text() if sock_log.exists() else ""
    assert not attempts, f"blocked socket attempts (python processes) during boot:\n{attempts}"
