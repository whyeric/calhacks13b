"""Shared QuickBooks test helpers: a temp app DB, a pinned clock, a live client on FakeQbo."""

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest

from app import clock
from app.config import Settings
from app.integrations import quickbooks as qbo

from .fake_qbo import REALM, FakeQbo

NOW = datetime(2026, 10, 25, 17, 0, tzinfo=timezone.utc)


@pytest.fixture
def fresh_qbo(monkeypatch, tmp_path):
    """A temp app DB (the connection lives there), no network, the clock pinned at NOW, and the
    seeder's waits recorded instead of slept. Yields the list of waits."""
    from app import config, db

    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'qbo.db'}")
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()
    db.create_schema()
    qbo.reset()
    waits: list[float] = []
    monkeypatch.setattr(qbo, "TRANSPORT", None)
    monkeypatch.setattr(qbo, "SLEEP", waits.append)
    monkeypatch.setattr(clock, "now", lambda: NOW)
    yield waits
    qbo.reset()
    config.get_settings.cache_clear()
    db.get_engine.cache_clear()


def live_settings(**kw) -> Settings:
    base = dict(qbo_client_id="cid", qbo_client_secret="csecret", demo_offline=False,
                qbo_redirect_uri="http://localhost:8000/integrations/quickbooks/callback",
                qbo_environment="sandbox", frontend_url="http://localhost:3000")
    return Settings(**(base | kw))


def connect_live(fake: FakeQbo, monkeypatch, settings: Settings | None = None) -> qbo.QuickBooks:
    """Run the OAuth flow against the fake; the connection is stored in the app DB."""
    monkeypatch.setattr(qbo, "TRANSPORT", fake.transport)
    q = qbo.QuickBooks(settings or live_settings())
    state = parse_qs(urlparse(q.connect().authorize_url).query)["state"][0]
    q.callback("auth-code", state, fake.realm)
    return q


__all__ = ["NOW", "REALM", "FakeQbo", "connect_live", "live_settings"]
