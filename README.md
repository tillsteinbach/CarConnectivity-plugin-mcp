# CarConnectivity-plugin-mcp
MCP Server plugin for CarConnectivity to enable AI agents to retrieve vehicle data and trigger supported vehicle commands.

## What this plugin provides
This plugin exposes the CarConnectivity object tree through a generic MCP interface and concrete vehicle-focused tools:

- `get_element(path="")`: Read objects, attributes, or commands by CarConnectivity path
- `set_attribute(path, value)`: Write changeable attributes
- `execute_command(path, value)`: Execute command elements
- `list_paths()`, `resolve_path(path)`, `discover_capabilities()`: Discover available paths and whether they are readable/writable/executable
- `get_vehicles()`, `get_vehicle_status(vin)`: Vehicle-centric read APIs
- `start_charging(vin)`, `stop_charging(vin)`, `start_climatization(vin)`, `stop_climatization(vin)`, `lock_vehicle(vin)`, `unlock_vehicle(vin)`: Vehicle-centric action tools
- `get_connector_states()`, `get_plugin_states()`, `get_mcp_server_logs(limit, contains)`: Connector/plugin runtime and bounded log access
- WebUI integration: if `carconnectivity-plugin-webui` is installed, MCP adds a `/mcp/status` plugin page with runtime health and recent logs

This keeps the server generic across connectors and vehicle brands while still enabling powerful agent workflows.

## Installation
```bash
pip install carconnectivity-plugin-mcp
```

## Configuration
Add the plugin to your `carconnectivity.json`:

```json
{
  "carConnectivity": {
    "plugins": [
      {
        "type": "mcp",
        "config": {
          "transport": "streamable-http",
          "host": "127.0.0.1",
          "port": 41000,
          "path": "/mcp"
        }
      }
    ]
  }
}
```

### Supported configuration parameters
- `transport`: `streamable-http` (default), `sse`, or `stdio`
- `host`: bind host for network transports (default: `127.0.0.1`)
- `port`: bind port for network transports (default: `41000`)
- `path`: endpoint path for network transports (default: `/mcp`)
