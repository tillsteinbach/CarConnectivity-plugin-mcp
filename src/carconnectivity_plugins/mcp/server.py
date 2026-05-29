"""MCP server abstraction for exposing CarConnectivity via FastMCP."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable, Optional
import json

try:
    from fastmcp import FastMCP
except ImportError:  # pragma: no cover - exercised in dependency-missing environments
    FastMCP = None  # type: ignore[assignment]

try:
    from carconnectivity.attributes import GenericAttribute
except ImportError:  # pragma: no cover - exercised in dependency-missing environments
    class GenericAttribute:  # type: ignore[no-redef]
        """Fallback type used for tests without carconnectivity installed."""


try:
    from carconnectivity.commands import GenericCommand
except ImportError:  # pragma: no cover - exercised in dependency-missing environments
    class GenericCommand:  # type: ignore[no-redef]
        """Fallback type used for tests without carconnectivity installed."""


try:
    from carconnectivity.objects import GenericObject
except ImportError:  # pragma: no cover - exercised in dependency-missing environments
    class GenericObject:  # type: ignore[no-redef]
        """Fallback type used for tests without carconnectivity installed."""


@dataclass(slots=True)
class _PathMeta:
    path: str
    kind: str
    readable: bool
    writable: bool
    executable: bool


class CarConnectivityMCPServer:
    """Wrap FastMCP and expose generic read/write/command operations by path."""

    def __init__(
        self,
        car_connectivity: Any,
        server_name: str = "CarConnectivity MCP",
        mcp_factory: Optional[Callable[[str], Any]] = None,
        runtime_state_provider: Optional[Callable[[], dict[str, Any]]] = None,
        log_provider: Optional[Callable[[int, Optional[str]], list[str]]] = None,
    ) -> None:
        if mcp_factory is None:
            if FastMCP is None:
                raise RuntimeError("fastmcp dependency is required to run the MCP server")
            mcp_factory = FastMCP

        self.car_connectivity = car_connectivity
        self.mcp = mcp_factory(server_name)
        self._runtime_state_provider = runtime_state_provider
        self._log_provider = log_provider
        self._register_tools()
        self._register_prompts()

    def set_runtime_state_provider(self, provider: Callable[[], dict[str, Any]]) -> None:
        self._runtime_state_provider = provider

    def set_log_provider(self, provider: Callable[[int, Optional[str]], list[str]]) -> None:
        self._log_provider = provider

    def _register_tools(self) -> None:
        @self.mcp.tool()
        def get_element(path: str = "") -> Any:
            """DEPRECATED: return an object, attribute, or command at a CarConnectivity path."""
            return self.read(path)

        @self.mcp.tool()
        def get_resource(path: str = "") -> Any:
            """Read a CarConnectivity resource by path without side effects."""
            return self.read(path)

        @self.mcp.tool()
        def set_attribute(path: str, value: Any) -> dict[str, Any]:
            """Set a writable attribute by path."""
            return self.write(path=path, value=value)

        @self.mcp.tool()
        def execute_command(path: str, value: Any = None) -> dict[str, Any]:
            """Execute a command by path using the provided argument payload."""
            return self.command(path=path, value=value)

        @self.mcp.tool()
        def list_paths() -> list[dict[str, Any]]:
            """List all discovered paths and capabilities."""
            return [self._path_to_dict(meta) for meta in self._collect_paths()]

        @self.mcp.tool()
        def resolve_path(path: str) -> dict[str, Any]:
            """Get capability metadata for a specific path."""
            element = self._get_enabled_element(path)
            return self._path_to_dict(self._path_meta(path, element))

        @self.mcp.tool()
        def discover_capabilities() -> dict[str, Any]:
            """Discover resources grouped by readability, writability and executability."""
            metas = self._collect_paths()
            return {
                "readable_resources": [self._path_to_dict(meta) for meta in metas if meta.readable],
                "writable_attributes": [self._path_to_dict(meta) for meta in metas if meta.writable],
                "executable_commands": [self._path_to_dict(meta) for meta in metas if meta.executable],
                "vehicle_path_templates": sorted(
                    {
                        template
                        for template in (self._vehicle_path_template(meta.path) for meta in metas)
                        if template is not None
                    }
                ),
                "deprecated_tools": [
                    {
                        "tool": "get_element",
                        "replacement": "Use get_resource()",
                    }
                ],
            }

        @self.mcp.tool()
        def get_vehicles() -> list[dict[str, Any]]:
            """Get all vehicles with path and VIN if available."""
            vehicles: list[dict[str, Any]] = []
            for vehicle_path in self._vehicle_paths():
                vehicle_id = vehicle_path.split("/")[-1]
                vin_value = self._safe_read_attribute(f"{vehicle_path}/vin")
                vehicles.append(
                    {
                        "vehicle_path": vehicle_path,
                        "vehicle_id": vehicle_id,
                        "vin": str(vin_value) if vin_value not in (None, "") else vehicle_id,
                    }
                )
            return vehicles

        @self.mcp.tool()
        def get_vehicle_status(vin: str) -> dict[str, Any]:
            """Get status and known action capabilities for a vehicle with a VIN."""
            vehicle_path = self._find_vehicle_path_by_vin(vin)
            attributes = self._vehicle_attributes(vehicle_path)
            return {
                "vin": vin,
                "vehicle_path": vehicle_path,
                "attributes": attributes,
                "capabilities": {
                    "start_charging": self._has_vehicle_command(vehicle_path, "start_charging"),
                    "stop_charging": self._has_vehicle_command(vehicle_path, "stop_charging"),
                    "start_climatization": self._has_vehicle_command(vehicle_path, "start_climatization"),
                    "stop_climatization": self._has_vehicle_command(vehicle_path, "stop_climatization"),
                    "lock_vehicle": self._has_vehicle_command(vehicle_path, "lock_vehicle"),
                    "unlock_vehicle": self._has_vehicle_command(vehicle_path, "unlock_vehicle"),
                },
            }

        @self.mcp.tool()
        def start_charging(vin: str) -> dict[str, Any]:
            """Start charging for a vehicle identified by VIN."""
            return self._execute_vehicle_action(vin=vin, action="start_charging")

        @self.mcp.tool()
        def stop_charging(vin: str) -> dict[str, Any]:
            """Stop charging for a vehicle identified by VIN."""
            return self._execute_vehicle_action(vin=vin, action="stop_charging")

        @self.mcp.tool()
        def start_climatization(vin: str) -> dict[str, Any]:
            """Start climatization for a vehicle identified by VIN."""
            return self._execute_vehicle_action(vin=vin, action="start_climatization")

        @self.mcp.tool()
        def stop_climatization(vin: str) -> dict[str, Any]:
            """Stop climatization for a vehicle identified by VIN."""
            return self._execute_vehicle_action(vin=vin, action="stop_climatization")

        @self.mcp.tool()
        def lock_vehicle(vin: str) -> dict[str, Any]:
            """Lock a vehicle identified by VIN."""
            return self._execute_vehicle_action(vin=vin, action="lock_vehicle")

        @self.mcp.tool()
        def unlock_vehicle(vin: str) -> dict[str, Any]:
            """Unlock a vehicle identified by VIN."""
            return self._execute_vehicle_action(vin=vin, action="unlock_vehicle")

        @self.mcp.tool()
        def get_runtime_state() -> dict[str, Any]:
            """Get runtime and connector health information."""
            payload = self._runtime_state_provider() if self._runtime_state_provider else {"running": True}
            payload["connectors"] = self._connector_states()
            return payload

        @self.mcp.tool()
        def get_recent_logs(limit: int = 200, contains: Optional[str] = None) -> dict[str, Any]:
            """Get recent logs with bounded output size."""
            bounded_limit = max(1, min(int(limit), 500))
            lines = self._log_provider(bounded_limit, contains) if self._log_provider is not None else []
            return {
                "limit": bounded_limit,
                "contains": contains,
                "lines": lines,
            }

    def _register_prompts(self) -> None:
        if not hasattr(self.mcp, "prompt"):
            return

        @self.mcp.prompt()  # type: ignore[misc]
        def inspect_vehicle_by_vin(vin: str) -> list[dict[str, str]]:
            return [
                {
                    "role": "user",
                    "content": (
                        f"Inspect VIN {vin}. First call discover_capabilities(), then get_vehicle_status(vin). "
                        "For any state change, verify executable commands before invoking them."
                    ),
                }
            ]

        @self.mcp.prompt()  # type: ignore[misc]
        def prepare_vehicle_for_departure(vin: str) -> list[dict[str, str]]:
            return [
                {
                    "role": "user",
                    "content": (
                        f"Prepare VIN {vin} for departure. Start with discover_capabilities(), then get_vehicle_status(vin). "
                        "Use start_climatization(vin), stop_charging(vin), and unlock_vehicle(vin) only if commands exist."
                    ),
                }
            ]

        @self.mcp.prompt()  # type: ignore[misc]
        def diagnose_connector_health() -> list[dict[str, str]]:
            return [
                {
                    "role": "user",
                    "content": (
                        "Diagnose plugin and connector health. First call get_runtime_state(), then inspect connector flags. "
                        "If unhealthy, call get_recent_logs(limit=100, contains='error')."
                    ),
                }
            ]

    def _get_enabled_element(self, path: str) -> Any:
        element = self.car_connectivity.get_by_path(path)
        if element is False or element is None:
            raise ValueError(f"Path not found: /{path}")
        if hasattr(element, "enabled") and not element.enabled:
            raise ValueError(f"Element at /{path} is not enabled")
        return element

    @staticmethod
    def _to_serializable(element: Any) -> Any:
        if hasattr(element, "as_dict"):
            return element.as_dict()
        if hasattr(element, "as_json"):
            return json.loads(element.as_json())
        return element

    def read(self, path: str = "") -> Any:
        """Read any CarConnectivity element by path and return JSON-serializable content."""
        element = self._get_enabled_element(path)
        return self._to_serializable(element)

    def write(self, path: str, value: Any) -> dict[str, Any]:
        """Write a value to a writable GenericAttribute by path."""
        element = self._get_enabled_element(path)
        if not isinstance(element, GenericAttribute):
            raise ValueError(f"Element at /{path} is not an attribute")
        if not getattr(element, "is_changeable", False):
            raise ValueError(f"Attribute at /{path} is read-only")
        element.set_value(value)
        return {"status": "ok", "path": path}

    def command(self, path: str, value: Any = None) -> dict[str, Any]:
        """Execute a GenericCommand by path."""
        element = self._get_enabled_element(path)
        if not isinstance(element, GenericCommand):
            raise ValueError(f"Element at /{path} is not a command")
        element.set_value(value)
        return {"status": "ok", "path": path}

    def _path_meta(self, path: str, element: Any) -> _PathMeta:
        is_attribute = isinstance(element, GenericAttribute)
        is_command = isinstance(element, GenericCommand)
        is_object = isinstance(element, GenericObject) or hasattr(element, "get_children")
        kind = "object" if is_object else "attribute" if is_attribute else "command" if is_command else "unknown"
        return _PathMeta(
            path=path,
            kind=kind,
            readable=True,
            writable=is_attribute and bool(getattr(element, "is_changeable", False)),
            executable=is_command,
        )

    def _path_to_dict(self, meta: _PathMeta) -> dict[str, Any]:
        return {
            "path": meta.path,
            "kind": meta.kind,
            "readable": meta.readable,
            "writable": meta.writable,
            "executable": meta.executable,
            "vehicle_path_template": self._vehicle_path_template(meta.path),
            "actions": self._actions_for_meta(meta),
        }

    def _actions_for_meta(self, meta: _PathMeta) -> list[dict[str, Any]]:
        actions: list[dict[str, Any]] = [{"type": "read", "method": "get_resource", "parameters": [{"name": "path", "const": meta.path}]}]
        if meta.writable:
            actions.append(
                {
                    "type": "write",
                    "method": "set_attribute",
                    "parameters": [{"name": "path", "const": meta.path}, {"name": "value", "type": "any"}],
                }
            )
        if meta.executable:
            actions.append(
                {
                    "type": "execute",
                    "method": "execute_command",
                    "parameters": [{"name": "path", "const": meta.path}, {"name": "value", "type": "any", "optional": True}],
                }
            )
        return actions

    @staticmethod
    def _vehicle_path_template(path: str) -> Optional[str]:
        parts = [part for part in path.split("/") if part]
        if len(parts) < 2 or parts[0] != "vehicles":
            return None
        parts[1] = "{vin}"
        return "/".join(parts)

    def _collect_paths(self) -> list[_PathMeta]:
        root = self._find_root()
        if root is None:
            return []
        collected: list[_PathMeta] = []

        def walk(node: Any, prefix: str) -> None:
            if not hasattr(node, "get_children"):
                return
            for child_name, child in node.get_children(recursive=False):
                path = f"{prefix}/{child_name}" if prefix else child_name
                collected.append(self._path_meta(path, child))
                walk(child, path)

        walk(root, "")
        return collected

    def _find_root(self) -> Any:
        if hasattr(self.car_connectivity, "get_root"):
            return self.car_connectivity.get_root()
        try:
            return self._get_enabled_element("")
        except ValueError:
            return None

    def _vehicle_paths(self) -> list[str]:
        candidates = []
        for meta in self._collect_paths():
            parts = [part for part in meta.path.split("/") if part]
            if len(parts) == 2 and parts[0] == "vehicles" and meta.kind == "object":
                candidates.append(meta.path)
        return sorted(set(candidates))

    def _safe_read_attribute(self, path: str) -> Any:
        try:
            element = self._get_enabled_element(path)
        except ValueError:
            return None
        if isinstance(element, GenericAttribute) and hasattr(element, "value"):
            return getattr(element, "value")
        return self._to_serializable(element)

    def _find_vehicle_path_by_vin(self, vin: str) -> str:
        for vehicle_path in self._vehicle_paths():
            vehicle_id = vehicle_path.split("/")[-1]
            vin_value = self._safe_read_attribute(f"{vehicle_path}/vin")
            resolved_vin = str(vin_value) if vin_value not in (None, "") else vehicle_id
            if resolved_vin == vin:
                return vehicle_path
        raise ValueError(f"No vehicle found for VIN: {vin}")

    def _vehicle_attributes(self, vehicle_path: str) -> dict[str, Any]:
        values: dict[str, Any] = {}
        for meta in self._collect_paths():
            if not meta.path.startswith(f"{vehicle_path}/"):
                continue
            if meta.kind != "attribute":
                continue
            values[meta.path.split("/")[-1]] = self._safe_read_attribute(meta.path)
        return values

    def _command_candidates(self, action: str) -> list[str]:
        candidates: dict[str, list[str]] = {
            "start_charging": ["charging/start_charging", "commands/start_charging", "start_charging", "charge_start"],
            "stop_charging": ["charging/stop_charging", "commands/stop_charging", "stop_charging", "charge_stop"],
            "start_climatization": [
                "climatization/start_climatization",
                "commands/start_climatization",
                "start_climatization",
                "climatization_start",
            ],
            "stop_climatization": [
                "climatization/stop_climatization",
                "commands/stop_climatization",
                "stop_climatization",
                "climatization_stop",
            ],
            "lock_vehicle": ["doors/lock", "commands/lock", "lock", "lock_vehicle"],
            "unlock_vehicle": ["doors/unlock", "commands/unlock", "unlock", "unlock_vehicle"],
        }
        return candidates[action]

    def _resolve_vehicle_command(self, vehicle_path: str, action: str) -> str:
        candidates = self._command_candidates(action)
        for suffix in candidates:
            path = f"{vehicle_path}/{suffix}"
            try:
                element = self._get_enabled_element(path)
            except ValueError:
                continue
            if isinstance(element, GenericCommand):
                return path

        valid_suffixes = {candidate.split("/")[-1] for candidate in candidates}
        for meta in self._collect_paths():
            if not meta.path.startswith(f"{vehicle_path}/"):
                continue
            if not meta.executable:
                continue
            if meta.path.split("/")[-1] in valid_suffixes:
                return meta.path
        raise ValueError(f"No executable command found for action '{action}' on {vehicle_path}")

    def _has_vehicle_command(self, vehicle_path: str, action: str) -> bool:
        try:
            self._resolve_vehicle_command(vehicle_path, action)
        except ValueError:
            return False
        return True

    def _execute_vehicle_action(self, vin: str, action: str) -> dict[str, Any]:
        vehicle_path = self._find_vehicle_path_by_vin(vin)
        command_path = self._resolve_vehicle_command(vehicle_path=vehicle_path, action=action)
        payload = self.command(path=command_path, value=None)
        payload["vin"] = vin
        payload["action"] = action
        return payload

    def _connector_states(self) -> list[dict[str, Any]]:
        states: dict[str, dict[str, Any]] = {}
        interesting = {"running", "healthy", "connected", "last_error", "last_update", "state"}
        for meta in self._collect_paths():
            parts = [part for part in meta.path.split("/") if part]
            if len(parts) < 3 or parts[0] != "connectors":
                continue
            connector_id, field = parts[1], parts[2]
            if field not in interesting:
                continue
            states.setdefault(connector_id, {"connector_id": connector_id})[field] = self._safe_read_attribute(meta.path)
        return sorted(states.values(), key=lambda entry: str(entry["connector_id"]))

    def run(self, *, transport: str = "streamable-http", host: str = "127.0.0.1", port: int = 41000, path: str = "/mcp") -> None:
        """Run FastMCP with sensible defaults and compatibility fallbacks across versions."""
        kwargs: dict[str, Any] = {}
        if transport != "stdio":
            kwargs = {"host": host, "port": port, "path": path}

        try:
            self.mcp.run(transport=transport, **kwargs)
        except TypeError:
            if transport == "stdio":
                self.mcp.run()
            else:
                self.mcp.run(**kwargs)

    def stop(self) -> None:
        """Stop the MCP server if the underlying implementation supports it."""
        if hasattr(self.mcp, "stop"):
            self.mcp.stop()
