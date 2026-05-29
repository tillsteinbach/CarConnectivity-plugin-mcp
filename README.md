
# CarConnectivity-plugin-mcp

MCP server plugin for CarConnectivity.

## What this plugin currently provides

This plugin exposes the CarConnectivity object tree through generic MCP capabilities.

Examples from Claude Desktop:


<img width="600" alt="image" src="https://github.com/user-attachments/assets/05f6d57c-de53-492a-888f-3f152cab5f86" />

### MCP tools

- `set_attribute(path, value)` – write a changeable attribute
- `execute_command(path, value=None)` – execute a command at a CarConnectivity path

### MCP resources

- `carconnectivity://paths` – list all discovered paths and capabilities
- `carconnectivity://path/{path}` – get one object/attribute/command as JSON
- `carconnectivity://mcp/logs{?limit,contains}` – bounded MCP plugin logs

FastMCP `ResourcesAsTools` is enabled, so resources are also callable from clients as tools.

If `carconnectivity-plugin-webui` is installed, MCP also provides a `/mcp/status` WebUI page with runtime health and recent logs.

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
          "path": "/mcp",
          "https": false,
          "allow_write": false,
          "auth_token": "replace-with-strong-random-token"
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
- `https`: enable HTTPS for network transports (default: `false`)
- `ssl_certfile`: path to TLS certificate file (required when `https` is `true`)
- `ssl_keyfile`: path to TLS private key file (required when `https` is `true`)
- `auth_token`: optional static bearer token; when set, clients must send an `Authorization` header with the bearer token
- `allow_write`: set to `true` to allow `set_attribute` and `execute_command` (default: `false`, read-only mode)

By default this plugin runs in **read-only mode**. To allow changing values or executing commands, you must explicitly set `allow_write` to `true`.

## Using it from Claude Desktop

1. Start CarConnectivity with this plugin enabled.
2. Install the HTTP-to-stdio bridge:

```bash
npm install -g mcp-remote
```

3. Edit your Claude Desktop MCP config:
   - macOS: `~/Library/Application Support/Claude/claude_desktop_config.json`
   - Windows: `%APPDATA%\\Claude\\claude_desktop_config.json`

4. Add this server entry:

```json
{
  "mcpServers": {
    "carconnectivity": {
      "command": "mcp-remote",
      "args": ["http://127.0.0.1:41000/mcp"]
    }
  }
}
```

5. Restart Claude Desktop.
