import json
from pathlib import Path

import httpx
import pytest

REPO = Path(__file__).resolve().parents[2]
FIXTURES = REPO / "fixtures"


@pytest.fixture(autouse=True)
def _no_network(monkeypatch):
    """Any request that reaches a real transport fails the test."""
    async def refuse(self, request):
        raise AssertionError(f"network call in test: {request.url}")
    monkeypatch.setattr(httpx.AsyncHTTPTransport, "handle_async_request", refuse)


class MockKalshi:
    """httpx.MockTransport over a {path: body | [bodies] | callable} table; counts calls."""

    def __init__(self, routes: dict):
        self.routes = routes
        self.calls: list[httpx.Request] = []
        self.transport = httpx.MockTransport(self._handle)

    def _handle(self, request: httpx.Request) -> httpx.Response:
        self.calls.append(request)
        path = request.url.path.removeprefix("/trade-api/v2")
        route = self.routes.get(path)
        if route is None:
            return httpx.Response(404, json={"error": {"code": "not_found"}})
        if callable(route):
            return route(request)
        return httpx.Response(200, text=json.dumps(route))


def load(rel: str) -> dict:
    return json.loads((FIXTURES / rel).read_text())
