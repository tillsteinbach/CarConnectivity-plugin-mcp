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
        self.prompts = {}
        self.run = MagicMock()
        self.stop = MagicMock()

    def tool(self):
        def decorator(func):
            self.tools[func.__name__] = func
            return func

        return decorator

    def prompt(self):
        def decorator(func):
            self.prompts[func.__name__] = func
            return func

        return decorator


class FakeAttribute:
    def __init__(self, value=None, enabled: bool = True, is_changeable: bool = True) -> None:
        self.enabled = enabled
        self.is_changeable = is_changeable
        self.value = value
        self.set_value = MagicMock(side_effect=self._set_value)

    def _set_value(self, value):
        self.value = value


class FakeCommand:
    def __init__(self, enabled: bool = True) -> None:
        self.enabled = enabled
        self.set_value = MagicMock()


class FakeObject:
    def __init__(self, payload=None, children=None):
        self.enabled = True
        self.payload = payload if payload is not None else {}
        self.children = children if children is not None else {}

    def as_dict(self):
        return self.payload

    def get_children(self, recursive: bool = False):
        return list(self.children.items())


class FakeCarConnectivity:
    def __init__(self, root: FakeObject):
        self.root = root

    def get_root(self):
        return self.root

    def get_by_path(self, path: str):
        if path == "":
            return self.root
        current = self.root
        for part in [p for p in path.split("/") if p]:
            if not isinstance(current, FakeObject):
                return None
            current = current.children.get(part)
            if current is None:
                return None
        return current


def _make_server(get_by_path):
    cc = MagicMock()
    cc.get_by_path = get_by_path
    return CarConnectivityMCPServer(car_connectivity=cc, mcp_factory=FakeMCP), cc


def _make_graph_server():
    vehicle = FakeObject(
        children={
            "vin": FakeAttribute("WVWZZZ1JZXW000001", is_changeable=False),
            "mileage": FakeAttribute(12345, is_changeable=True),
            "start_charging": FakeCommand(),
            "stop_charging": FakeCommand(),
            "start_climatization": FakeCommand(),
            "stop_climatization": FakeCommand(),
            "lock": FakeCommand(),
            "unlock": FakeCommand(),
        }
    )
    connectors = FakeObject(
        children={
            "conn-1": FakeObject(
                children={
                    "running": FakeAttribute(True, is_changeable=False),
                    "healthy": FakeAttribute(True, is_changeable=False),
                    "last_error": FakeAttribute(None, is_changeable=False),
                }
            )
        }
    )
    root = FakeObject(children={"vehicles": FakeObject(children={"veh-1": vehicle}), "connectors": connectors})
    cc = FakeCarConnectivity(root)
    server = CarConnectivityMCPServer(car_connectivity=cc, mcp_factory=FakeMCP, runtime_state_provider=lambda: {"running": True}, log_provider=lambda limit, contains: ["ok", "error"][0:limit])
    return server, cc


@pytest.fixture(autouse=True)
def patch_types(monkeypatch):
    monkeypatch.setattr("carconnectivity_plugins.mcp.server.GenericAttribute", FakeAttribute)
    monkeypatch.setattr("carconnectivity_plugins.mcp.server.GenericCommand", FakeCommand)
    monkeypatch.setattr("carconnectivity_plugins.mcp.server.GenericObject", FakeObject)


def test_registers_tools():
    server, _ = _make_server(MagicMock())
    assert {"get_element", "set_attribute", "execute_command"}.issubset(set(server.mcp.tools.keys()))


def test_registers_prompts():
    server, _ = _make_server(MagicMock())
    assert {"inspect_vehicle_by_vin", "prepare_vehicle_for_departure", "diagnose_connector_health"}.issubset(set(server.mcp.prompts.keys()))


def test_read_returns_serialized_object():
    payload = {"vehicle": "ok"}
    server, cc = _make_server(MagicMock(return_value=FakeObject(payload=payload)))

    result = server.read("garage")

    assert result == payload
    cc.get_by_path.assert_called_once_with("garage")


def test_read_raises_on_missing_path():
    server, _ = _make_server(MagicMock(return_value=False))

    with pytest.raises(ValueError, match="Path not found"):
        server.read("missing")


def test_write_updates_changeable_attribute():
    attribute = FakeAttribute()
    server, _ = _make_server(MagicMock(return_value=attribute))

    result = server.write(path="a/b", value=42)

    attribute.set_value.assert_called_once_with(42)
    assert result["status"] == "ok"


def test_write_rejects_readonly_attribute():
    attribute = FakeAttribute(is_changeable=False)
    server, _ = _make_server(MagicMock(return_value=attribute))

    with pytest.raises(ValueError, match="read-only"):
        server.write(path="a/b", value=42)


def test_command_executes_generic_command():
    command = FakeCommand()
    server, _ = _make_server(MagicMock(return_value=command))

    result = server.command(path="a/cmd", value={"action": "start"})

    command.set_value.assert_called_once_with({"action": "start"})
    assert result["status"] == "ok"


def test_discovery_tools_include_action_metadata_and_templates():
    server, _ = _make_graph_server()

    list_paths = server.mcp.tools["list_paths"]
    discover_capabilities = server.mcp.tools["discover_capabilities"]

    entries = list_paths()
    mileage = next(entry for entry in entries if entry["path"] == "vehicles/veh-1/mileage")
    assert mileage["writable"] is True
    assert mileage["vehicle_path_template"] == "vehicles/{vin}/mileage"
    assert any(action["type"] == "write" for action in mileage["actions"])

    discovered = discover_capabilities()
    assert any(entry["path"] == "vehicles/veh-1/start_charging" for entry in discovered["executable_commands"])
    assert "vehicles/{vin}/start_charging" in discovered["vehicle_path_templates"]


def test_vehicle_tools_and_runtime_introspection():
    server, _ = _make_graph_server()

    get_vehicles = server.mcp.tools["get_vehicles"]
    get_vehicle_status = server.mcp.tools["get_vehicle_status"]
    start_charging = server.mcp.tools["start_charging"]
    get_runtime_state = server.mcp.tools["get_runtime_state"]
    get_recent_logs = server.mcp.tools["get_recent_logs"]

    vehicles = get_vehicles()
    assert vehicles[0]["vin"] == "WVWZZZ1JZXW000001"

    status = get_vehicle_status("WVWZZZ1JZXW000001")
    assert status["capabilities"]["start_charging"] is True

    start_result = start_charging("WVWZZZ1JZXW000001")
    assert start_result["action"] == "start_charging"

    runtime = get_runtime_state()
    assert runtime["running"] is True
    assert runtime["connectors"][0]["connector_id"] == "conn-1"

    logs = get_recent_logs(limit=2, contains="error")
    assert logs["limit"] == 2
    assert len(logs["lines"]) <= 2
