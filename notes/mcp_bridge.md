# mcp_bridge.py
## Purpose
Persistent subprocess pool for MCP servers — JSON-RPC 2.0 over stdio, startup cost paid once.
## Key Functions
- `call_mcp_server(server_name, tool_name, params, context_intent)` — invoke MCP tool
- `list_mcp_tools(server_name)` — enumerate available tools for a server
- `get_enabled_servers()` — list enabled MCP server names from config
- `reload_config()` / `save_config(cfg)` — hot-reload mcp_config.json
- `_get_process(server_name)` — get or start MCP subprocess
- `_stop_all_processes()` — shutdown all MCP subprocesses
- `_check_privacy(context_intent)` — block MCP calls for private intents
- `_MCPProcess` class — wraps subprocess with stdin/stdout JSON-RPC pipe
## Imports From
config
## Imported By
intent_dispatch, chat_server (MCP admin endpoints)
## Status
OK
## Notes
Config at mcp_config.json. Privacy gate prevents MCP calls for PRIVATE_INTENTS. Per-server intent allow-list.
