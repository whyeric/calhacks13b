"""C6-A17/A18: offline with sockets blocked (pyproject addopts --disable-socket), no Anthropic
key: health says fallback, every route answers from fixtures/caches, desk runs complete."""

import socket

import pytest

from tests.api.test_desk_run import poll


@pytest.mark.filterwarnings("ignore::UserWarning")
def test_sockets_blocked():
    with pytest.raises(Exception):
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("1.1.1.1", 80))


def test_offline_no_key_end_to_end(client):
    h = client.get("/health").json()
    assert h == {"status": "ok", "offline": True, "anthropic": "fallback",
                 "sample_week": True, "sample_businesses": ["restaurant", "taxi"]}
    assert client.post("/businesses/taxi/analyze", json={}).status_code == 200
    run_id = client.post("/businesses/taxi/desk/run", json={"week_of": "2026-11-02"}).json()["run_id"]
    assert poll(client, run_id, timeout=30)["status"] == "done"
    entries = [e for e in client.get("/businesses/taxi/decisions").json() if e["run_id"] == run_id]
    assert entries and all(e["agent"] == "fallback" for e in entries)
    chat = client.post("/businesses/taxi/chat", json={"message": "what happened?"})
    assert chat.status_code == 200 and chat.json()["reply"]
    for url in ("/businesses", "/businesses/taxi/hedges", "/businesses/taxi/ledger",
                "/businesses/taxi/decisions", "/businesses/taxi/settings"):
        assert client.get(url).status_code == 200, url
