"""HTTPS related tests for MCP server runner options."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from carconnectivity_plugins.mcp.server import CarConnectivityMCPServer


class FakeMCP:
    """Minimal fake FastMCP implementation used in tests."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.run = MagicMock()

    def tool(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator

    def resource(self, *args, **kwargs):
        def decorator(func):
            return func

        return decorator

    def add_transform(self, transform):
        return None


def _make_server() -> CarConnectivityMCPServer:
    cc = MagicMock()
    return CarConnectivityMCPServer(car_connectivity=cc, mcp_factory=FakeMCP)


@pytest.fixture(autouse=True)
def patch_transforms(monkeypatch):
    monkeypatch.setattr("carconnectivity_plugins.mcp.server.ResourcesAsTools", lambda mcp: object())
    monkeypatch.setattr("carconnectivity_plugins.mcp.server.PromptsAsTools", lambda mcp: object())


def test_run_passes_ssl_kwargs_when_https_enabled():
    server = _make_server()

    server.run(
        transport="streamable-http",
        host="0.0.0.0",
        port=41000,
        path="/mcp",
        https=True,
        ssl_certfile="/tmp/cert.pem",
        ssl_keyfile="/tmp/key.pem",
    )

    server.mcp.run.assert_called_once_with(
        transport="streamable-http",
        host="0.0.0.0",
        port=41000,
        path="/mcp",
        ssl_certfile="/tmp/cert.pem",
        ssl_keyfile="/tmp/key.pem",
    )


def test_run_ignores_ssl_kwargs_for_stdio():
    server = _make_server()

    server.run(transport="stdio", https=True, ssl_certfile="/tmp/cert.pem", ssl_keyfile="/tmp/key.pem")

    server.mcp.run.assert_called_once_with(transport="stdio")


def test_run_fallback_retries_without_ssl_kwargs():
    server = _make_server()
    server.mcp.run.side_effect = [TypeError("old api"), TypeError("no ssl args"), None]

    server.run(
        transport="streamable-http",
        host="127.0.0.1",
        port=41000,
        path="/mcp",
        https=True,
        ssl_certfile="/tmp/cert.pem",
        ssl_keyfile="/tmp/key.pem",
    )

    assert server.mcp.run.call_args_list[2].kwargs == {
        "host": "127.0.0.1",
        "port": 41000,
        "path": "/mcp",
    }
