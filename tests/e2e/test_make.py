"""C8-A17 make_targets_exist: every demo-relevant target resolves (`make -n`, nothing runs)."""

import subprocess

import pytest

from conftest import REPO_ROOT


@pytest.mark.parametrize("target", ["dev", "demo", "seed", "seed-data", "warm", "test", "e2e", "clean", "install", "api"])
def test_a17_make_target_resolves(target):
    r = subprocess.run(["make", "-n", target], cwd=REPO_ROOT, capture_output=True, text=True, timeout=60)
    assert r.returncode == 0, r.stderr


def test_a17_demo_is_offline_and_seeds_first():
    out = subprocess.run(["make", "-n", "demo"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    assert "app.db seed" in out and "app.books.seed" in out, "demo must run seed first"
    assert out.index("app.db seed") < out.index("uvicorn")
    assert "--reload" not in out


def test_a17_clean_never_touches_fixtures():
    out = subprocess.run(["make", "-n", "clean"], cwd=REPO_ROOT, capture_output=True, text=True).stdout
    assert "fixtures" not in out
