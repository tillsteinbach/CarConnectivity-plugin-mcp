"""Tests for the MCP server wrapper."""
from __future__ import annotations

from unittest.mock import MagicMock

import pytest

from carconnectivity_plugins.mcp.server import CarConnectivityMCPServer


class FakeMCP:
    """Minimal fake FastMCP implementation used in tests."""

    def __init__(self, name: str) -> None:
        self.name = name
        self.tools = {}
        self.run = MagicMock()
        self.stop = MagicMock()

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func
        return decorator


class FakeAttribute:
    def __init__(self, enabled: bool = True, is_changeable: bool = True) -> None:
        self.enabled = enabled
        self.is_changeable = is_changeable
        self.set_value = MagicMock()


class FakeCommand:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.set_value = MagicMock()


class FakeObject:
    def __init__(self, payload):
        self.enabled = True
        self.payload = payload

    def as_dict(self):
        return self.payload


def _make_server(get_by_path):
    cc = MagicMock()
    cc.get_by_path = get_by_path
    return CarConnectivityMCPServer(car_connectivity=cc, mcp_factory=FakeMCP), cc


def test_registers_tools():
    server, _ = _make_server(MagicMock())
    assert set(server.mcp.tools.keys()) == {"get_element", "set_attribute", "execute_command"}


def test_read_returns_serialized_object():
    payload = {"vehicle": "ok"}
    server, cc = _make_server(MagicMock(return_value=FakeObject(payload)))

    result = server.read("garage")

    assert result == payload
    cc.get_by_path.assert_called_once_with("garage")


def test_read_raises_on_missing_path():
    server, _ = _make_server(MagicMock(return_value=False))

    with pytest.raises(ValueError, match="Path not found"):
        server.read("missing")


def test_write_updates_changeable_attribute(monkeypatch):
    attribute = FakeAttribute()
    server, _ = _make_server(MagicMock(return_value=attribute))
    monkeypatch.setattr("carconnectivity_plugins.mcp.server.GenericAttribute", FakeAttribute)

    result = server.write(path="a/b", value=42)

    attribute.set_value.assert_called_once_with(42)
    assert result["status"] == "ok"


def test_write_rejects_readonly_attribute(monkeypatch):
    attribute = FakeAttribute(is_changeable=False)
    server, _ = _make_server(MagicMock(return_value=attribute))
    monkeypatch.setattr("carconnectivity_plugins.mcp.server.GenericAttribute", FakeAttribute)

    with pytest.raises(ValueError, match="read-only"):
        server.write(path="a/b", value=42)


def test_command_executes_generic_command(monkeypatch):
    command = FakeCommand()
    server, _ = _make_server(MagicMock(return_value=command))
    monkeypatch.setattr("carconnectivity_plugins.mcp.server.GenericCommand", FakeCommand)

    result = server.command(path="a/cmd", value={"action": "start"})

    command.set_value.assert_called_once_with({"action": "start"})
    assert result["status"] == "ok"
