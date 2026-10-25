"""Durable QuickBooks connection: stored in the app DB, refreshed and rotated, revoked on
disconnect, throttling backed off, and no token in a log line. FakeQbo; no network."""

import logging
from datetime import timedelta

import httpx
import pytest

from app import clock, db
from app.config import Settings
from app.integrations import quickbooks as qbo

from .conftest import NOW, FakeQbo, connect_live, live_settings

pytestmark = pytest.mark.usefixtures("fresh_qbo")


def test_connection_survives_a_restart(monkeypatch):
    fake = FakeQbo()
    q = connect_live(fake, monkeypatch)
    row = db.get_qbo_connection()
    assert row["environment"] == "sandbox" and row["realm_id"] == fake.realm
    assert row["refresh_token"] == "r1" and row["refresh_expires_at"] == (NOW + timedelta(seconds=8726400)).isoformat()

    qbo.reset()  # a new process: nothing in memory
    again = qbo.QuickBooks(live_settings())
    assert again is not q
    s = again.status()
    assert s.connected and s.realm_id == fake.realm and s.company_name == "Sandbox Company_US_1"
    assert again.source().query("Bill") == []
    assert len(fake.token_calls) == 1  # no new consent, no refresh needed


def test_refresh_rotates_and_is_saved(monkeypatch):
    fake = FakeQbo()
    connect_live(fake, monkeypatch)
    monkeypatch.setattr(clock, "now", lambda: NOW + timedelta(minutes=59, seconds=30))  # inside the 60 s margin
    qbo.QuickBooks(live_settings()).source().query("Bill")
    assert fake.token_calls[-1] == {"grant_type": "refresh_token", "refresh_token": "r1"}
    row = db.get_qbo_connection()
    assert (row["access_token"], row["refresh_token"]) == ("a2", "r2")  # the rotated refresh token is kept

    # The next process uses the new refresh token, never the spent one.
    monkeypatch.setattr(clock, "now", lambda: NOW + timedelta(hours=3))
    qbo.QuickBooks(live_settings()).source().query("Bill")
    assert fake.token_calls[-1] == {"grant_type": "refresh_token", "refresh_token": "r2"}
    assert db.get_qbo_connection()["refresh_token"] == "r3"


def test_two_clients_spend_a_refresh_token_once(monkeypatch):
    fake = FakeQbo()
    q = connect_live(fake, monkeypatch)
    first, second = q.live(), q.live()  # both hold a1/r1
    fake.expired.add("a1")
    first.query("Bill")  # 401 -> refresh -> a2/r2 saved
    second.query("Bill")  # 401 -> finds a2 in the store instead of spending r1 again
    assert [c["grant_type"] for c in fake.token_calls] == ["authorization_code", "refresh_token"]
    assert second.tokens.access_token == "a2"


def test_expired_refresh_token_asks_to_reconnect(monkeypatch):
    connect_live(FakeQbo(), monkeypatch)
    monkeypatch.setattr(clock, "now", lambda: NOW + timedelta(days=101))
    with pytest.raises(qbo.NotConnected, match="reconnect"):
        qbo.QuickBooks(live_settings()).commitments()


def test_disconnect_revokes_and_deletes(monkeypatch):
    fake = FakeQbo()
    q = connect_live(fake, monkeypatch)
    s = q.disconnect()
    assert fake.revoked == [{"token": "r1"}]
    assert not s.connected and db.get_qbo_connection() is None
    with pytest.raises(qbo.NotConnected):
        q.source()


def test_disconnect_deletes_even_if_revoke_fails(monkeypatch):
    fake = FakeQbo()
    q = connect_live(fake, monkeypatch)
    monkeypatch.setattr(qbo, "TRANSPORT", httpx.MockTransport(lambda r: httpx.Response(503)))
    assert not q.disconnect().connected and db.get_qbo_connection() is None


def test_demo_connection_is_stored_but_not_live(monkeypatch):
    demo = qbo.QuickBooks(Settings(demo_offline=True))
    demo.connect()
    assert db.get_qbo_connection()["environment"] == "demo"
    assert qbo.QuickBooks(Settings(demo_offline=True)).status().connected  # survives a restart
    live = qbo.QuickBooks(live_settings())
    assert not live.status().connected  # a demo connection is not a live one
    with pytest.raises(qbo.NotConnected):
        live.source()
    prod = qbo.QuickBooks(live_settings(qbo_environment="production"))
    connect_live(FakeQbo(), monkeypatch)
    assert not prod.status().connected  # nor a sandbox connection a production one


def test_tokens_never_logged(monkeypatch, caplog):
    caplog.set_level(logging.DEBUG)
    fake = FakeQbo()
    q = connect_live(fake, monkeypatch)
    fake.expired.add("a1")
    q.source().query("Bill")
    fake.throttle = 1
    q.source().query("Bill")
    tokens = q.load_tokens()
    assert "a2" not in repr(tokens) and "r2" not in repr(tokens)
    text = caplog.text
    for secret in ("a1", "r1", "a2", "r2", "csecret"):
        assert f"'{secret}'" not in text and f" {secret} " not in text and f"={secret}" not in text


def test_429_backs_off_then_succeeds(monkeypatch, fresh_qbo):
    fake = FakeQbo()
    q = connect_live(fake, monkeypatch)
    fake.throttle = 3
    assert q.source().query("Bill") == []
    assert fresh_qbo == [1.0, 2.0, 4.0]  # exponential without Retry-After


def test_429_uses_retry_after_and_gives_up(monkeypatch, fresh_qbo):
    fake = FakeQbo()
    q = connect_live(fake, monkeypatch)
    calls = {"n": 0}

    def always_429(request):
        if request.url.path.endswith("/query"):
            calls["n"] += 1
            return httpx.Response(429, headers={"Retry-After": "7"})
        return fake.handle(request)

    monkeypatch.setattr(qbo, "TRANSPORT", httpx.MockTransport(always_429))
    with pytest.raises(qbo.Unavailable) as e:
        q.source().query("Bill")
    assert e.value.detail["status"] == 429
    assert fresh_qbo == [7.0] * qbo.MAX_THROTTLE_RETRIES and calls["n"] == qbo.MAX_THROTTLE_RETRIES + 1


def test_bodies_keep_decimals_exact():
    from decimal import Decimal

    assert qbo.dumps({"Amount": Decimal("1317.40"), "Qty": 3, "ok": True, "n": None}) == \
        '{"Amount":1317.40,"Qty":3,"ok":true,"n":null}'
    with pytest.raises(TypeError):
        qbo.dumps({"Amount": 1.5})
