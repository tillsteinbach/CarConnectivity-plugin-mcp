"""MCP server abstraction for exposing CarConnectivity via FastMCP."""
from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Optional
import json
import io
import base64
import hmac

try:
    from fastmcp import FastMCP
    from fastmcp.server.transforms import ResourcesAsTools, PromptsAsTools
    from fastmcp.exceptions import NotFoundError
    from fastmcp.server.auth import TokenVerifier, AccessToken
except ImportError:  # pragma: no cover - exercised in dependency-missing environments
    FastMCP = None  # type: ignore[assignment]
    TokenVerifier = object  # type: ignore[assignment]
    AccessToken = None  # type: ignore[assignment]

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


class _StaticTokenVerifier(TokenVerifier):
    """Verify a static bearer token configured for the plugin."""

    def __init__(self, expected_token: str) -> None:
        super().__init__()
        self._expected_token = expected_token

    async def verify_token(self, token: str) -> Optional[AccessToken]:
        if hmac.compare_digest(token, self._expected_token):
            return AccessToken(token=token, client_id="mcp-static-token", scopes=[])
        return None


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
        allow_write: bool = False,
        auth_token: Optional[str] = None,
    ) -> None:
        if mcp_factory is None:
            if FastMCP is None:
                raise RuntimeError("fastmcp dependency is required to run the MCP server")
            mcp_factory = FastMCP

        self.car_connectivity: CarConnectivity = car_connectivity
        self._allow_write = allow_write
        auth_provider = _StaticTokenVerifier(auth_token) if auth_token else None
        try:
            self.mcp = mcp_factory(server_name, auth=auth_provider)
        except TypeError:
            self.mcp = mcp_factory(server_name)
        self._runtime_state_provider = runtime_state_provider
        self._log_provider = log_provider
        self._register_tools()
        self._register_prompts()
        if hasattr(self.mcp, "add_transform"):
            try:
                self.mcp.add_transform(ResourcesAsTools(self.mcp))
                self.mcp.add_transform(PromptsAsTools(self.mcp))
            except TypeError:
                # Compatibility with test doubles and older server implementations.
                pass

    def set_runtime_state_provider(self, provider: Callable[[], dict[str, Any]]) -> None:
        self._runtime_state_provider = provider

    def set_log_provider(self, provider: Callable[[int, Optional[str]], list[str]]) -> None:
        self._log_provider = provider

    def _register_tools(self) -> None:

        @self.mcp.tool()
        def set_attribute(path: str, value: Any) -> bool:
            """Set a writable attribute by path."""
            if not self._allow_write:
                raise PermissionError("Write access is disabled in plugin configuration")
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
            if not self._allow_write:
                raise PermissionError("Write access is disabled in plugin configuration")
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
