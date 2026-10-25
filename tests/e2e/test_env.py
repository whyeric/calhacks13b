"""C8-A2 env_example_complete."""

from __future__ import annotations

import shutil
import subprocess
import sys

from conftest import BACKEND, REPO_ROOT

SPEC_VARS = ("ANTHROPIC_API_KEY", "ANTHROPIC_MODEL", "KALSHI_BASE_URL", "DEMO_OFFLINE", "DATABASE_URL",
             "WEEKLY_BUDGET_DEFAULT", "AVG_CHECK_USD")  # spec §12


def parse_env(text: str) -> dict[str, str]:
    out = {}
    for line in text.splitlines():
        line = line.strip()
        if line and not line.startswith("#") and "=" in line:
            k, v = line.split("=", 1)
            out[k.strip()] = v.strip()
    return out


def test_a2_env_example_complete():
    env = parse_env((REPO_ROOT / ".env.example").read_text())
    missing = [k for k in (*SPEC_VARS, "NEXT_PUBLIC_API_URL") if k not in env]
    assert not missing, f".env.example lacks {missing}"
    assert not [k for k, v in env.items() if v.startswith("sk-" + "ant-")]
    assert env["ANTHROPIC_API_KEY"] == ""
    assert env["ANTHROPIC_MODEL"] and env["ANTHROPIC_MODEL"] != "latest"


def test_a2_settings_cover_example():
    """Every backend key in .env.example is a field of `config.Settings` (no dead config)."""
    from app.config import Settings

    env = parse_env((REPO_ROOT / ".env.example").read_text())
    fields = {f.upper() for f in Settings.model_fields}
    backend_keys = [k for k in env if not k.startswith("NEXT_PUBLIC_")]
    assert not [k for k in backend_keys if k not in fields], "keys Settings would ignore"
    assert {k for k in SPEC_VARS} <= fields


def test_a2_boots_with_only_env_example(tmp_path):
    """Copy the backend next to a `.env` that is exactly `.env.example`; settings load and the
    app answers /health and /businesses (in a fresh interpreter, so no cached settings leak)."""
    root = tmp_path / "repo"
    shutil.copytree(BACKEND / "app", root / "backend" / "app")
    shutil.copytree(BACKEND / "fixtures", root / "backend" / "fixtures")
    shutil.copy(REPO_ROOT / ".env.example", root / ".env")
    script = (
        "import os\n"
        "for k in list(os.environ):\n"
        "    if k in %r: del os.environ[k]\n"
        "from fastapi.testclient import TestClient\n"
        "from app.config import get_settings\n"
        "s = get_settings(); assert s.demo_offline is False and not s.use_claude, s\n"
        "os.environ['DEMO_OFFLINE'] = '1'; get_settings.cache_clear()\n"
        "from app.main import app\n"
        "with TestClient(app) as c:\n"
        "    assert c.get('/health').status_code == 200\n"
        "    ids = sorted(b['id'] for b in c.get('/businesses').json())\n"
        "    assert ids == ['restaurant', 'taxi'], ids\n"
        "print('ok')\n"
    ) % ([*SPEC_VARS, "DEMO_SAMPLE_WEEK", "LEDGERS_DIR", "MARKETS_BACKEND", "OWNER_TOKEN"],)
    r = subprocess.run([sys.executable, "-c", script], cwd=root / "backend", capture_output=True, text=True,
                       timeout=120)
    assert r.returncode == 0 and r.stdout.strip().endswith("ok"), r.stderr[-2000:]
    assert (root / "backend" / "hedge_desk.db").exists(), "DATABASE_URL from .env.example not used"
