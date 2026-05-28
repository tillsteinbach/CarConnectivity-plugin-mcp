"""MCP server abstraction for exposing CarConnectivity via FastMCP."""
from __future__ import annotations

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


class CarConnectivityMCPServer:
    """Wrap FastMCP and expose generic read/write/command operations by path."""

    def __init__(
        self,
        car_connectivity: Any,
        server_name: str = "CarConnectivity MCP",
        mcp_factory: Optional[Callable[[str], Any]] = None,
    ) -> None:
        if mcp_factory is None:
            if FastMCP is None:
                raise RuntimeError("fastmcp dependency is required to run the MCP server")
            mcp_factory = FastMCP

        self.car_connectivity = car_connectivity
        self.mcp = mcp_factory(server_name)
        self._register_tools()

    def _register_tools(self) -> None:
        @self.mcp.tool()
        def get_element(path: str = "") -> Any:
            """Return an object, attribute, or command at a CarConnectivity path."""
            return self.read(path)

        @self.mcp.tool()
        def set_attribute(path: str, value: Any) -> dict[str, Any]:
            """Set a writable attribute by path."""
            return self.write(path=path, value=value)

        @self.mcp.tool()
        def execute_command(path: str, value: Any = None) -> dict[str, Any]:
            """Execute a command by path using the provided argument payload."""
            return self.command(path=path, value=value)

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
