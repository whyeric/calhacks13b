"""C2-A38: stats/ is pure. No network/LLM/DB imports and no file writes."""

import ast
import builtins
import io
import os
import subprocess
import sys
from pathlib import Path

import pytest

import app.stats as stats_pkg
from app.stats.exposure import beta_settlement, fit_exposures
from tests.fixtures.synth_features import synth_taxi

STATS_DIR = Path(stats_pkg.__file__).parent
BACKEND_DIR = STATS_DIR.parents[1]
FORBIDDEN = {"httpx", "anthropic", "sqlmodel", "requests", "urllib", "socket", "sqlite3", "duckdb"}
WRITE_CALLS = {"to_parquet", "to_csv", "to_json", "write_text", "write_bytes", "savefig"}


def _stats_sources():
    files = sorted(STATS_DIR.glob("*.py"))
    assert files
    return files


@pytest.mark.parametrize("path", _stats_sources(), ids=lambda p: p.name)
def test_no_forbidden_imports_or_writes_in_source(path):
    tree = ast.parse(path.read_text())
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            roots = {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            roots = {(node.module or "").split(".")[0]}
        else:
            roots = set()
        assert not roots & FORBIDDEN, f"{path.name}: imports {roots & FORBIDDEN}"
        if isinstance(node, ast.Call):
            fn = node.func
            name = fn.attr if isinstance(fn, ast.Attribute) else getattr(fn, "id", "")
            assert name not in WRITE_CALLS | {"open"}, f"{path.name}: calls {name}()"


def test_import_pulls_in_no_io_modules():
    mods = ", ".join(f"'{m}'" for m in ("httpx", "anthropic", "sqlmodel"))
    code = (
        "import sys, pkgutil, importlib, app.stats as p\n"
        "for m in pkgutil.iter_modules(p.__path__): importlib.import_module(f'app.stats.{m.name}')\n"
        f"print([m for m in ({mods}) if m in sys.modules])"
    )
    out = subprocess.run(
        [sys.executable, "-c", code], cwd=BACKEND_DIR, capture_output=True, text=True, check=True
    )
    assert out.stdout.strip() == "[]"


def test_fit_writes_no_files(monkeypatch):
    df = synth_taxi(0)

    def refuse(*a, **k):
        raise AssertionError("stats must not open files")

    monkeypatch.setattr(builtins, "open", refuse)
    monkeypatch.setattr(io, "open", refuse)
    monkeypatch.setattr(os, "open", refuse)
    fit_exposures(df, {"hot": 85.0})
    beta_settlement(df, df["rain"], event="rain")
