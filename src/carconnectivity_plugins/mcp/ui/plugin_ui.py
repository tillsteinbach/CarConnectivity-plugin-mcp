"""User interface integration for the MCP plugin."""
from __future__ import annotations

import os
from typing import TYPE_CHECKING

import flask
from flask_login import login_required

from carconnectivity_plugins.base.plugin import BasePlugin
from carconnectivity_plugins.base.ui.plugin_ui import BasePluginUI

if TYPE_CHECKING:
    from typing import Dict, List, Literal, Optional, Union


class PluginUI(BasePluginUI):
    """WebUI adapter exposing MCP runtime state and recent logs."""

    def __init__(self, plugin: BasePlugin, app: flask.Flask, *args, **kwargs):
        blueprint: Optional[flask.Blueprint] = flask.Blueprint(
            name=plugin.id,
            import_name="carconnectivity-plugin-mcp",
            url_prefix=f"/{plugin.id}",
            template_folder=os.path.dirname(__file__) + "/templates",
        )
        super().__init__(plugin, blueprint=blueprint, app=app, *args, **kwargs)

        @self.blueprint.route("/", methods=["GET"])
        def root():
            return flask.redirect(flask.url_for("plugins.mcp.status"))

        @self.blueprint.route("/status", methods=["GET"])
        @login_required
        def status():
            log_limit = flask.request.args.get("log_limit", default=50, type=int)
            plugin_runtime = self.plugin.get_runtime_state()
            logs = self.plugin.get_recent_logs(limit=log_limit)
            return flask.render_template(
                "mcp/status.html",
                current_app=flask.current_app,
                plugin=self.plugin,
                runtime=plugin_runtime,
                logs=logs,
                log_limit=max(1, min(int(log_limit), 500)),
            )

    def get_nav_items(self) -> List[Dict[Literal["text", "url", "sublinks", "divider"], Union[str, List]]]:
        return super().get_nav_items() + [{"text": "Status", "url": flask.url_for("plugins.mcp.status")}]

    def get_title(self) -> str:
        return "MCP"
