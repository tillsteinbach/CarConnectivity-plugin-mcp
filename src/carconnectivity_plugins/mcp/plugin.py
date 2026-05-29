"""Module implements the plugin providing an MCP server for CarConnectivity."""
from __future__ import annotations

from typing import TYPE_CHECKING
from collections import deque
import logging
import threading

from carconnectivity.errors import ConfigurationError
from carconnectivity.util import config_remove_credentials
from carconnectivity_plugins.base.plugin import BasePlugin
from carconnectivity_plugins.mcp.server import CarConnectivityMCPServer

try:
    from carconnectivity_plugins.mcp._version import __version__
except ImportError:  # pragma: no cover
    __version__ = "unknown"

if TYPE_CHECKING:
    from typing import Dict, Optional
    from carconnectivity.carconnectivity import CarConnectivity

LOG: logging.Logger = logging.getLogger("carconnectivity.plugins.mcp")


class Plugin(BasePlugin):
    """Plugin exposing CarConnectivity as a FastMCP server."""

    def __init__(
        self,
        plugin_id: str,
        car_connectivity: CarConnectivity,
        config: Dict,
        *args,
        initialization: Optional[Dict] = None,
        **kwargs,
    ) -> None:
        BasePlugin.__init__(
            self,
            plugin_id=plugin_id,
            car_connectivity=car_connectivity,
            config=config,
            log=LOG,
            *args,
            initialization=initialization,
            **kwargs,
        )

        self._server_thread: Optional[threading.Thread] = None
        self._running: bool = False
        self._log_buffer: deque[str] = deque(maxlen=1000)
        self._log_buffer_handler = _RingBufferHandler(self._log_buffer)
        self._log_buffer_handler.setLevel(logging.INFO)
        LOG.addHandler(self._log_buffer_handler)

        transport = config.get("transport", "streamable-http")
        valid_transports = {"stdio", "streamable-http", "sse"}
        if transport not in valid_transports:
            raise ConfigurationError(f'Invalid transport specified in config ("transport" must be one of {sorted(valid_transports)})')

        self.active_config["transport"] = transport
        self.active_config["host"] = config.get("host", "127.0.0.1")
        self.active_config["port"] = config.get("port", 41000)
        self.active_config["path"] = config.get("path", "/mcp")
        self.active_config["allow_write"] = config.get("allow_write", False)
        self.active_config["auth_token"] = config.get("auth_token")

        if not isinstance(self.active_config["port"], int) or self.active_config["port"] < 1 or self.active_config["port"] > 65535:
            raise ConfigurationError('Invalid port specified in config ("port" out of range, must be 1-65535)')

        if not isinstance(self.active_config["path"], str) or not self.active_config["path"].startswith("/"):
            raise ConfigurationError('Invalid path specified in config ("path" must start with "/")')
        if not isinstance(self.active_config["allow_write"], bool):
            raise ConfigurationError('Invalid allow_write specified in config ("allow_write" must be a boolean)')
        if self.active_config["auth_token"] is not None and (
            not isinstance(self.active_config["auth_token"], str) or not self.active_config["auth_token"].strip()
        ):
            raise ConfigurationError('Invalid auth_token specified in config ("auth_token" must be a non-empty string)')

        self.server = CarConnectivityMCPServer(
            car_connectivity=car_connectivity,
            runtime_state_provider=self._runtime_state,
            log_provider=self._get_recent_logs,
            allow_write=self.active_config["allow_write"],
            auth_token=self.active_config["auth_token"],
        )

        LOG.info("Loading MCP plugin with config %s", config_remove_credentials(config))

    def startup(self) -> None:
        LOG.info("Starting MCP plugin")
        self._running = False
        self.healthy._set_value(value=False)  # pylint: disable=protected-access
        self._server_thread = threading.Thread(
            target=self.server.run,
            kwargs={
                "transport": self.active_config["transport"],
                "host": self.active_config["host"],
                "port": self.active_config["port"],
                "path": self.active_config["path"],
            },
            daemon=True,
            name="carconnectivity.plugins.mcp-server",
        )
        self._server_thread.start()
        self._running = True
        self.healthy._set_value(value=True)  # pylint: disable=protected-access

    def shutdown(self) -> None:
        self._running = False
        self.healthy._set_value(value=False)  # pylint: disable=protected-access
        self.server.stop()
        if self._server_thread is not None and self._server_thread.is_alive():
            self._server_thread.join(timeout=2)
        LOG.removeHandler(self._log_buffer_handler)
        return super().shutdown()

    def get_version(self) -> str:
        return __version__

    def get_type(self) -> str:
        return "carconnectivity-plugin-mcp"

    def get_name(self) -> str:
        return "MCP Plugin"

    def _runtime_state(self) -> dict:
        thread_alive = self._server_thread is not None and self._server_thread.is_alive()
        healthy = bool(getattr(self.healthy, "enabled", False) and getattr(self.healthy, "value", False))
        return {
            "plugin_id": self.id,
            "running": self._running and thread_alive,
            "healthy": healthy,
            "server_thread_alive": thread_alive,
            "transport": self.active_config["transport"],
            "host": self.active_config["host"],
            "port": self.active_config["port"],
            "path": self.active_config["path"],
            "allow_write": self.active_config["allow_write"],
            "authentication_enabled": bool(self.active_config["auth_token"]),
        }

    def _get_recent_logs(self, limit: int, contains: Optional[str]) -> list[str]:
        logs = list(self._log_buffer)
        if contains:
            logs = [line for line in logs if contains in line]
        return logs[-limit:]

    def get_runtime_state(self) -> dict:
        """Public runtime state accessor used by other plugins such as WebUI."""
        return self._runtime_state()

    def get_recent_logs(self, limit: int = 200, contains: Optional[str] = None) -> list[str]:
        """Public log accessor used by other plugins such as WebUI."""
        bounded_limit = max(1, min(int(limit), 500))
        return self._get_recent_logs(limit=bounded_limit, contains=contains)


class _RingBufferHandler(logging.Handler):
    """Log handler writing formatted log records into a bounded deque."""

    def __init__(self, buffer: deque[str]) -> None:
        super().__init__()
        self._buffer = buffer

    def emit(self, record: logging.LogRecord) -> None:
        self._buffer.append(self.format(record))
