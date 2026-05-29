"""Tests for the MCP server wrapper."""
from __future__ import annotations

from unittest.mock import MagicMock
import json

import pytest

from carconnectivity_plugins.mcp.server import CarConnectivityMCPServer


class FakeMCP:
    """Minimal fake FastMCP implementation used in tests."""

    def __init__(self, name: str, auth=None) -> None:
        self.name = name
        self.auth = auth
        self.tools = {}
        self.resources = {}
        self.transforms = []
        self.run = MagicMock()
        self.stop = MagicMock()

    def tool(self, **_kwargs):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator

    def resource(self, uri: str | None = None, **_kwargs):
        def decorator(func):
            self.resources[func.__name__] = {"uri": uri, "func": func}
            return func

        return decorator

    def add_transform(self, transform):
        self.transforms.append(transform)


class FakeAttribute:
    def __init__(self, path: str, value=None, is_changeable: bool = True) -> None:
        self._path = path
        self.value = value
        self.is_changeable = is_changeable
        self.set_value = MagicMock(side_effect=self._set_value)

    def _set_value(self, value):
        self.value = value

    def get_absolute_path(self) -> str:
        return self._path

    def as_json(self) -> str:
        return json.dumps({"path": self._path, "value": self.value})


class FakeCommand:
    def __init__(self, path: str) -> None:
        self._path = path
        self.set_value = MagicMock()

    def get_absolute_path(self) -> str:
        return self._path


class FakeObject:
    def __init__(self, path: str, children=None) -> None:
        self._path = path
        self.children = children or []

    def get_absolute_path(self) -> str:
        return self._path

    def as_json(self) -> str:
        return json.dumps({"path": self._path})


class FakeCarConnectivity:
    def __init__(self, by_path: dict[str, object], children=None) -> None:
        self._by_path = by_path
        self.children = children or []

    def get_by_path(self, path: str):
        return self._by_path.get(path)


@pytest.fixture(autouse=True)
def patch_types(monkeypatch):
    monkeypatch.setattr("carconnectivity_plugins.mcp.server.GenericAttribute", FakeAttribute)
    monkeypatch.setattr("carconnectivity_plugins.mcp.server.GenericCommand", FakeCommand)
    monkeypatch.setattr("carconnectivity_plugins.mcp.server.GenericObject", FakeObject)


def test_registers_tools_and_resources():
    server = CarConnectivityMCPServer(car_connectivity=FakeCarConnectivity(by_path={}), mcp_factory=FakeMCP)

    assert {"set_attribute", "execute_command"} == set(server.mcp.tools.keys())
    assert {"list_paths", "read_from_path", "get_mcp_server_logs"} == set(server.mcp.resources.keys())


def test_set_attribute_requires_explicit_write_access():
    attribute = FakeAttribute("/vehicles/1/mileage", 123, is_changeable=True)
    server = CarConnectivityMCPServer(
        car_connectivity=FakeCarConnectivity(by_path={"/vehicles/1/mileage": attribute}),
        mcp_factory=FakeMCP,
    )

    with pytest.raises(PermissionError, match="Write access is disabled"):
        server.mcp.tools["set_attribute"]("/vehicles/1/mileage", 456)

    attribute.set_value.assert_not_called()


def test_execute_command_requires_explicit_write_access():
    command = FakeCommand("/vehicles/1/lock")
    server = CarConnectivityMCPServer(
        car_connectivity=FakeCarConnectivity(by_path={"/vehicles/1/lock": command}),
        mcp_factory=FakeMCP,
    )

    with pytest.raises(PermissionError, match="Write access is disabled"):
        server.mcp.tools["execute_command"]("/vehicles/1/lock", None)

    command.set_value.assert_not_called()


def test_write_and_command_work_when_enabled():
    attribute = FakeAttribute("/vehicles/1/mileage", 123, is_changeable=True)
    command = FakeCommand("/vehicles/1/lock")
    server = CarConnectivityMCPServer(
        car_connectivity=FakeCarConnectivity(
            by_path={
                "/vehicles/1/mileage": attribute,
                "/vehicles/1/lock": command,
            }
        ),
        mcp_factory=FakeMCP,
        allow_write=True,
    )

    assert server.mcp.tools["set_attribute"]("/vehicles/1/mileage", 456) is True
    assert server.mcp.tools["execute_command"]("/vehicles/1/lock", {"state": "lock"}) is True

    attribute.set_value.assert_called_once_with(456)
    command.set_value.assert_called_once_with({"state": "lock"})


def test_read_from_path_serializes_result():
    attribute = FakeAttribute("/vehicles/1/mileage", 123, is_changeable=True)
    server = CarConnectivityMCPServer(
        car_connectivity=FakeCarConnectivity(by_path={"/vehicles/1/mileage": attribute}),
        mcp_factory=FakeMCP,
    )

    response = server.mcp.resources["read_from_path"]["func"]("vehicles/1/mileage")
    assert json.loads(response)["value"] == 123


def test_configures_auth_provider_if_credentials_set():
    server = CarConnectivityMCPServer(
        car_connectivity=FakeCarConnectivity(by_path={}),
        mcp_factory=FakeMCP,
        client_id="my-client",
        client_secret="secret-token",
    )
    assert server.mcp.auth is not None

    server_without_auth = CarConnectivityMCPServer(
        car_connectivity=FakeCarConnectivity(by_path={}),
        mcp_factory=FakeMCP,
    )
    assert server_without_auth.mcp.auth is None

    server_missing_secret = CarConnectivityMCPServer(
        car_connectivity=FakeCarConnectivity(by_path={}),
        mcp_factory=FakeMCP,
        client_id="my-client",
    )
    assert server_missing_secret.mcp.auth is None

    server_missing_id = CarConnectivityMCPServer(
        car_connectivity=FakeCarConnectivity(by_path={}),
        mcp_factory=FakeMCP,
        client_secret="secret-token",
    )
    assert server_missing_id.mcp.auth is None
