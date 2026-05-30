"""
routes/mcp.py — MCP (Model Context Protocol) API endpoints.
  GET    /api/mcp/status
  GET    /api/mcp/tools/{server_name}
  POST   /api/mcp/call
  GET    /api/mcp/config
  POST   /api/mcp/config/add
  POST   /api/mcp/config/toggle/{server_name}
  DELETE /api/mcp/config/remove/{server_name}
"""

import asyncio
import os

from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

from config import get_logger

log = get_logger("routes.mcp")
router = APIRouter()


def _check_mcp_admin(req: Request):
    expected = os.getenv("MCP_ADMIN_TOKEN", "")
    if not expected:
        log.error("MCP_ADMIN_TOKEN not set; rejecting MCP mutation request")
        return JSONResponse(status_code=401, content={"ok": False, "error": "Unauthorized: MCP_ADMIN_TOKEN is not configured on the server."})
    supplied = req.headers.get("X-Admin-Token", "")
    if not (bool(expected) and supplied == expected):
        return JSONResponse(status_code=401, content={"ok": False, "error": "Unauthorized: missing or invalid X-Admin-Token header."})
    return None


@router.get("/api/mcp/status")
async def api_mcp_status():
    """Return enabled/disabled status, tool count, and last_called for all MCP servers."""
    try:
        import mcp_bridge
        status = await asyncio.to_thread(mcp_bridge.get_mcp_status)
        return status
    except Exception as e:
        log.error(f"MCP status error: {e}")
        return {"error": str(e)}


@router.get("/api/mcp/tools/{server_name}")
async def api_mcp_tools(server_name: str):
    """Return list of available tools for a named MCP server."""
    try:
        import mcp_bridge
        tools = await asyncio.to_thread(mcp_bridge.list_mcp_tools, server_name)
        return {"server": server_name, "tools": tools}
    except Exception as e:
        log.error(f"MCP tools error [{server_name}]: {e}")
        return {"server": server_name, "tools": [], "error": str(e)}


@router.post("/api/mcp/call")
async def api_mcp_call(req: Request):
    """Call a tool on an MCP server. Body: {server, tool, arguments}."""
    denied = _check_mcp_admin(req)
    if denied:
        return denied
    data = await req.json()
    server = data.get("server", "")
    tool = data.get("tool", "")
    arguments = data.get("arguments", {})
    if not server or not tool:
        return {"error": "server and tool fields required"}
    try:
        import mcp_bridge
        result = await asyncio.to_thread(mcp_bridge.call_mcp_server, server, tool, arguments)
        return {"result": result, "server": server, "tool": tool}
    except Exception as e:
        log.error(f"MCP call error [{server}/{tool}]: {e}")
        return {"result": None, "server": server, "tool": tool, "error": str(e)}


@router.get("/api/mcp/config")
async def api_mcp_config_get():
    """Return full mcp_config.json contents."""
    try:
        import mcp_bridge
        cfg = await asyncio.to_thread(mcp_bridge._load_config)
        return cfg
    except Exception as e:
        log.error(f"MCP config get error: {e}")
        return {"error": str(e)}


@router.post("/api/mcp/config/add")
async def api_mcp_config_add(req: Request):
    """Add or update an MCP server."""
    denied = _check_mcp_admin(req)
    if denied:
        return denied
    data = await req.json()
    name = data.get("name", "").strip()
    command = data.get("command", "").strip()
    if not name or not command:
        return {"ok": False, "error": "name and command required"}
    try:
        import mcp_bridge
        cfg = mcp_bridge._load_config()
        cfg.setdefault("servers", {})[name] = {
            "enabled": data.get("enabled", False),
            "command": command,
            "args": data.get("args", []),
            "description": data.get("description", ""),
            "allowed_intents": data.get("allowed_intents", ["mcp"]),
            "env_vars": data.get("env_vars", {}),
        }
        await asyncio.to_thread(mcp_bridge.save_config, cfg)
        return {"ok": True, "name": name}
    except Exception as e:
        log.error(f"MCP config add error: {e}")
        return {"ok": False, "error": str(e)}


@router.post("/api/mcp/config/toggle/{server_name}")
async def api_mcp_config_toggle(server_name: str, req: Request):
    """Toggle enabled/disabled for a named server."""
    denied = _check_mcp_admin(req)
    if denied:
        return denied
    try:
        import mcp_bridge
        cfg = mcp_bridge._load_config()
        servers = cfg.get("servers", {})
        if server_name not in servers:
            return {"ok": False, "error": f"Server '{server_name}' not found"}
        servers[server_name]["enabled"] = not servers[server_name].get("enabled", False)
        new_state = servers[server_name]["enabled"]
        await asyncio.to_thread(mcp_bridge.save_config, cfg)
        return {"ok": True, "name": server_name, "enabled": new_state}
    except Exception as e:
        log.error(f"MCP toggle error [{server_name}]: {e}")
        return {"ok": False, "error": str(e)}


@router.delete("/api/mcp/config/remove/{server_name}")
async def api_mcp_config_remove(server_name: str, req: Request):
    """Remove an MCP server entry from config."""
    denied = _check_mcp_admin(req)
    if denied:
        return denied
    try:
        import mcp_bridge
        cfg = mcp_bridge._load_config()
        servers = cfg.get("servers", {})
        if server_name not in servers:
            return {"ok": False, "error": f"Server '{server_name}' not found"}
        del servers[server_name]
        await asyncio.to_thread(mcp_bridge.save_config, cfg)
        return {"ok": True, "removed": server_name}
    except Exception as e:
        log.error(f"MCP remove error [{server_name}]: {e}")
        return {"ok": False, "error": str(e)}
