"""MCP server abstraction for exposing CarConnectivity via FastMCP."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional
import json
import io
import base64

try:
    from fastmcp import FastMCP
    from fastmcp.server.transforms import ResourcesAsTools, PromptsAsTools
    from fastmcp.exceptions import NotFoundError
except ImportError:  # pragma: no cover - exercised in dependency-missing environments
    FastMCP = None  # type: ignore[assignment]

try:
    from carconnectivity.attributes import GenericAttribute
except ImportError:  # pragma: no cover - exercised in dependency-missing environments
    class GenericAttribute:  # type: ignore[no-redef]
        """Fallback type used for tests without carconnectivity installed."""

try:
    from carconnectivity.attributes import ImageAttribute
except ImportError:  # pragma: no cover - exercised in dependency-missing environments
    class ImageAttribute:  # type: ignore[no-redef]
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

if TYPE_CHECKING:
    from typing import Callable
    from carconnectivity.carconnectivity import CarConnectivity

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
        car_connectivity: CarConnectivity,
        server_name: str = "CarConnectivity MCP",
        mcp_factory: Optional[Callable[[str], Any]] = None,
        runtime_state_provider: Optional[Callable[[], dict[str, Any]]] = None,
        log_provider: Optional[Callable[[int, Optional[str]], list[str]]] = None,
    ) -> None:
        if mcp_factory is None:
            if FastMCP is None:
                raise RuntimeError("fastmcp dependency is required to run the MCP server")
            mcp_factory = FastMCP

        self.car_connectivity: CarConnectivity = car_connectivity
        self.mcp = mcp_factory(server_name, )
        self._runtime_state_provider = runtime_state_provider
        self._log_provider = log_provider
        self._register_tools()
        self._register_prompts()
        self.mcp.add_transform(ResourcesAsTools(self.mcp))
        self.mcp.add_transform(PromptsAsTools(self.mcp))

    def set_runtime_state_provider(self, provider: Callable[[], dict[str, Any]]) -> None:
        self._runtime_state_provider = provider

    def set_log_provider(self, provider: Callable[[int, Optional[str]], list[str]]) -> None:
        self._log_provider = provider

    def _register_tools(self) -> None:

        @self.mcp.tool()
        def set_attribute(path: str, value: Any) -> bool:
            """Set a writable attribute by path."""
            attribute = self.car_connectivity.get_by_path(path)
            if attribute is None or not isinstance(attribute, GenericAttribute):
                raise NotFoundError(f"Attribute not found at path: {path}")
            if not attribute.is_changeable:
                raise ValueError(f"Attribute at path {path} is not writable")
            attribute.set_value(value)
            return True

        @self.mcp.tool(description="Execute a command by path with an optional argument payload.")
        def execute_command(path: str, value: Any = None) -> bool:
            """Execute a command by path using the provided argument payload."""
            command: Optional[GenericCommand] = self.car_connectivity.get_by_path(path)
            if command is None or not isinstance(command, GenericCommand):
                raise NotFoundError(f"Command not found at path: {path}")
            command.set_value(value)
            return True

        @self.mcp.resource("carconnectivity://paths", description="List all discovered paths and their capabilities.", mime_type="application/json")
        def list_paths() -> str:
            """List all discovered paths and capabilities."""
            paths: dict[str, dict[str, Any]] = {}
            for element in self._recursive_get_children(self.car_connectivity):
                paths[element.get_absolute_path()] = {
                    "type": type(element).__name__,
                    "is_attribute": isinstance(element, GenericAttribute),
                    "is_command": isinstance(element, GenericCommand),
                    "is_object": isinstance(element, GenericObject),
                    "readable": True,
                    "writable": isinstance(element, GenericAttribute) and element.is_changeable,
                    "executable": isinstance(element, GenericCommand),
                }
            return json.dumps(paths)

        @self.mcp.resource("carconnectivity://path/{path}",
                           description="Returns a json representation of the element at the specified path, or an empty object if not found or not enabled.",
                           mime_type="application/json")
        def read_from_path(path: str) -> str:
            """Get capability metadata for a specific path."""
            if not path.startswith("/"):
                path = "/" + path
            element: GenericObject | GenericAttribute | None = self.car_connectivity.get_by_path(path)
            if element is not None:
                if isinstance(element, ImageAttribute):
                    if element.value is None:
                        return "{}"
                    image = element.value
                    img_io = io.BytesIO()  # pyright: ignore[reportPossiblyUnboundVariable]
                    image.save(img_io, 'PNG')
                    return json.dumps({"image": f"data:image/png;base64,{base64.b64encode(img_io.getvalue()).decode()}"})
                return_json: Optional[str] = element.as_json()
                return return_json if return_json is not None else "{}"
            raise NotFoundError()

        @self.mcp.resource("carconnectivity://mcp/logs{?limit,contains}")
        def get_mcp_server_logs(limit: int = 200, contains: Optional[str] = None) -> dict[str, Any]:
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
"""
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
                    "Diagnose plugin and connector health. First call get_connector_states() and get_plugin_states(). "
                    "If unhealthy, call get_mcp_server_logs(limit=100, contains='error')."
                    ),
                }
            ]
"""
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

    def _recursive_get_children(self, element: GenericObject) -> list[GenericObject | GenericAttribute ]:
        children: list[GenericObject | GenericAttribute] = []
        for child in element.children:
            children.append(child)
            if isinstance(child, GenericObject):
                children.extend(self._recursive_get_children(child))
        return children
