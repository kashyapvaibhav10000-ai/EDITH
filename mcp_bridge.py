"""
EDITH MCP Bridge — Persistent subprocess pool with JSON-RPC 2.0 over stdio.

Each enabled MCP server runs as a long-lived background process. Node/npx
startup cost is paid once; all subsequent calls reuse the open pipe.
Auto-restarts if the process dies. Thread-safe via per-server lock.
"""

import json
import os
import queue
import subprocess
import threading
import time
from typing import Any

from config import get_logger, EDITH_PATH

log = get_logger("mcp_bridge")

try:
    from config import MCP_CONFIG_PATH, MCP_LOG_PATH, MCP_TIMEOUT
except ImportError:
    MCP_CONFIG_PATH = os.path.join(EDITH_PATH, "mcp_config.json")
    MCP_LOG_PATH    = os.path.join(EDITH_PATH, "logs", "mcp.log")
    MCP_TIMEOUT     = 30

# ──────────────────────────────────────────────
# Config cache
# ──────────────────────────────────────────────
_config: dict = {}
_config_lock = threading.Lock()


def _load_config() -> dict:
    """Load mcp_config.json (in-memory cache; cleared by reload_config)."""
    global _config
    with _config_lock:
        if _config:
            return _config
        try:
            with open(MCP_CONFIG_PATH, "r") as f:
                _config = json.load(f)
            log.info(f"MCP config loaded: {len(_config.get('servers', {}))} servers")
        except Exception as e:
            log.error(f"Failed to load MCP config: {e}")
            _config = {"servers": {}}
        return _config


def reload_config() -> dict:
    """Force-reload config from disk, clear tool cache, stop stale processes."""
    global _config
    with _config_lock:
        _config = {}
    # Stop all running processes so they restart with new config on next call
    _stop_all_processes()
    return _load_config()


def save_config(cfg: dict) -> None:
    """Write config to disk then reload."""
    with open(MCP_CONFIG_PATH, "w") as f:
        json.dump(cfg, f, indent=2)
    reload_config()
    log.info(f"MCP config saved: {len(cfg.get('servers', {}))} servers")


def _get_server_cfg(server_name: str) -> dict | None:
    return _load_config().get("servers", {}).get(server_name)


def _build_env(server_cfg: dict) -> dict:
    env = os.environ.copy()
    for var_name in server_cfg.get("env_vars", {}):
        val = os.getenv(var_name, "")
        if val:
            env[var_name] = val
    return env


# ──────────────────────────────────────────────
# Persistent Process Pool
# ──────────────────────────────────────────────

class _MCPProcess:
    """
    Wraps a single long-lived MCP server subprocess.

    Maintains a background reader thread that pulls JSON lines from stdout
    and routes them to per-request queues keyed by JSON-RPC id.
    """

    def __init__(self, server_name: str, server_cfg: dict):
        self.server_name = server_name
        self.server_cfg  = server_cfg
        self.lock        = threading.Lock()   # serialise writes to stdin
        self._proc: subprocess.Popen | None = None
        self._reader: threading.Thread | None = None
        self._pending: dict[int, queue.Queue] = {}  # req_id → response queue
        self._pending_lock = threading.Lock()
        self._req_counter  = 0
        self._dead         = False            # set True after unrecoverable failure

    # ── lifecycle ──

    def start(self) -> None:
        """Spawn the subprocess and start the stdout reader thread."""
        cmd = [self.server_cfg["command"]] + self.server_cfg.get("args", [])
        env = _build_env(self.server_cfg)
        log.info(f"[{self.server_name}] Starting MCP process: {' '.join(cmd)}")
        self._proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            env=env,
            text=True,
            bufsize=1,           # line-buffered
        )
        self._dead = False
        self._reader = threading.Thread(
            target=self._read_loop,
            name=f"mcp-reader-{self.server_name}",
            daemon=True,
        )
        self._reader.start()
        # Drain stderr in background so it never blocks
        threading.Thread(
            target=self._drain_stderr,
            name=f"mcp-stderr-{self.server_name}",
            daemon=True,
        ).start()
        log.info(f"[{self.server_name}] MCP process started (pid {self._proc.pid})")
        # MCP protocol requires initialize → initialized before any tool calls
        try:
            self.send("initialize", {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "edith", "version": "1.0"},
            }, timeout=10)
            notif = json.dumps({"jsonrpc": "2.0", "method": "initialized", "params": {}}) + "\n"
            self._proc.stdin.write(notif)
            self._proc.stdin.flush()
            log.info(f"[{self.server_name}] MCP handshake complete")
        except Exception as e:
            # Servers that need credentials (cloudflare, gdrive) fail here when
            # tokens aren't configured — log at debug to avoid startup spam.
            _CREDENTIAL_SERVERS = {"cloudflare", "gdrive", "brave-search"}
            if self.server_name in _CREDENTIAL_SERVERS:
                log.debug(f"[{self.server_name}] MCP handshake skipped (credentials not configured): {e}")
            else:
                log.warning(f"[{self.server_name}] MCP initialize handshake failed: {e}")

    def stop(self) -> None:
        """Terminate the subprocess."""
        self._dead = True
        if self._proc:
            try:
                self._proc.terminate()
                self._proc.wait(timeout=5)
            except Exception:
                try:
                    self._proc.kill()
                    self._proc.wait(timeout=5)
                except Exception as e:
                    # Force reap even if kill failed
                    try:
                        self._proc.wait(timeout=2)
                    except Exception:
                        pass
            self._proc = None
        # Unblock any waiting callers
        with self._pending_lock:
            for q in self._pending.values():
                q.put(None)
            self._pending.clear()

    def is_alive(self) -> bool:
        return (
            self._proc is not None
            and self._proc.poll() is None
            and not self._dead
        )

    # ── I/O ──

    def _read_loop(self) -> None:
        """Read stdout line-by-line and route JSON responses to waiting queues."""
        try:
            for line in self._proc.stdout:
                line = line.strip()
                if not line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    log.debug(f"[{self.server_name}] non-JSON stdout: {line[:80]}")
                    continue
                req_id = obj.get("id")
                with self._pending_lock:
                    q = self._pending.get(req_id)
                if q is not None:
                    q.put(obj)
                else:
                    log.debug(f"[{self.server_name}] unsolicited message id={req_id}")
        except Exception as e:
            if not self._dead:
                log.error(f"[{self.server_name}] reader thread crashed: {e}")
        finally:
            # Signal all waiting callers that the process is gone
            self._dead = True
            # Reap the zombie so the PID is released immediately
            if self._proc:
                try:
                    # Try graceful shutdown first
                    if self._proc.poll() is None:
                        self._proc.terminate()
                        self._proc.wait(timeout=2)
                except Exception:
                    # Force kill if terminate fails
                    try:
                        self._proc.kill()
                        self._proc.wait(timeout=2)
                    except Exception:
                        pass
            with self._pending_lock:
                for q in self._pending.values():
                    q.put(None)
                self._pending.clear()

    def _drain_stderr(self) -> None:
        try:
            for line in self._proc.stderr:
                line = line.strip()
                if line:
                    log.debug(f"[{self.server_name}] stderr: {line[:120]}")
        except Exception:
            pass

    # ── RPC ──

    def send(self, method: str, params: dict, timeout: float = MCP_TIMEOUT) -> dict:
        """
        Send one JSON-RPC request and block until response or timeout.
        Thread-safe; multiple callers can use the same process concurrently.
        Raises RuntimeError on timeout or process death.
        """
        with self.lock:
            self._req_counter += 1
            req_id = self._req_counter

        payload = {
            "jsonrpc": "2.0",
            "id": req_id,
            "method": method,
            "params": params,
        }

        resp_queue: queue.Queue = queue.Queue(maxsize=1)
        with self._pending_lock:
            self._pending[req_id] = resp_queue

        try:
            line = json.dumps(payload) + "\n"
            self._proc.stdin.write(line)
            self._proc.stdin.flush()
        except Exception as e:
            with self._pending_lock:
                self._pending.pop(req_id, None)
            raise RuntimeError(f"Failed to write to MCP process stdin: {e}") from e

        try:
            result = resp_queue.get(timeout=timeout)
        except queue.Empty:
            with self._pending_lock:
                self._pending.pop(req_id, None)
            raise RuntimeError(f"MCP server timed out after {timeout}s (method={method})")

        with self._pending_lock:
            self._pending.pop(req_id, None)

        if result is None:
            raise RuntimeError(f"MCP process died while waiting for response (method={method})")

        return result


# ── Process registry ──

_processes: dict[str, _MCPProcess] = {}
_proc_lock = threading.Lock()

# Startup timeout — how long to wait for the process to become ready
_STARTUP_TIMEOUT = 120  # node server cold-start (tools/list)


def _get_process(server_name: str) -> _MCPProcess:
    """
    Return a running _MCPProcess for server_name, starting it if needed.
    Restarts automatically if the process has died.
    """
    with _proc_lock:
        proc = _processes.get(server_name)
        if proc and proc.is_alive():
            return proc
        # Dead or missing — (re)start
        if proc:
            log.warning(f"[{server_name}] Process dead, restarting...")
            proc.stop()

        cfg = _get_server_cfg(server_name)
        if cfg is None:
            raise RuntimeError(f"Server '{server_name}' not in config")
        if not cfg.get("enabled", False):
            raise RuntimeError(f"Server '{server_name}' is disabled")

        new_proc = _MCPProcess(server_name, cfg)
        new_proc.start()
        _processes[server_name] = new_proc
        return new_proc


def _stop_all_processes() -> None:
    """Terminate all running MCP subprocesses (called on config reload)."""
    with _proc_lock:
        for name, proc in list(_processes.items()):
            log.info(f"Stopping MCP process: {name}")
            proc.stop()
        _processes.clear()


# ──────────────────────────────────────────────
# Tracking
# ──────────────────────────────────────────────
_last_called: dict[str, float] = {}
_tool_cache:  dict[str, list]  = {}


def _log_mcp_call(server_name: str, tool_name: str, success: bool, detail: str = "") -> None:
    """Append structured entry to mcp.log."""
    try:
        ts     = time.strftime("%Y-%m-%d %H:%M:%S")
        status = "OK" if success else "ERR"
        entry  = f"{ts} [{status}] server={server_name} tool={tool_name} {detail}\n"
        with open(MCP_LOG_PATH, "a") as f:
            f.write(entry)
    except Exception as e:
        log.warning(f"Could not write to mcp.log: {e}")


def _extract_text(result: Any) -> str:
    """Pull text out of an MCP tool result (content list or raw)."""
    if isinstance(result, dict):
        content = result.get("content", [])
        if isinstance(content, list):
            parts = []
            for item in content:
                if isinstance(item, dict):
                    parts.append(item.get("text", str(item)))
                else:
                    parts.append(str(item))
            return "\n".join(parts) if parts else str(result)
        return str(content) if content else str(result)
    return str(result)


# ──────────────────────────────────────────────
# Privacy Guard
# ──────────────────────────────────────────────
_BLOCKED_INTENTS = {"vault", "shell"}


def _check_privacy(context_intent: str | None) -> str | None:
    if context_intent and context_intent.lower() in _BLOCKED_INTENTS:
        return (
            "⚠️ Privacy Guard: MCP tools cannot be used from vault or shell contexts. "
            "Sensitive operations must stay local."
        )
    return None


def _check_allowed_intent(server_name: str, tool_name: str, server_cfg: dict, context_intent: str | None) -> None:
    """Enforce per-server allowed_intents metadata when an intent is supplied."""
    allowed = server_cfg.get("allowed_intents") or []
    if not allowed or not context_intent:
        return

    intent = context_intent.lower()
    normalized_allowed = {str(item).lower() for item in allowed}
    if intent not in normalized_allowed:
        message = f"MCP tool '{tool_name}' not allowed for intent '{intent}'"
        _log_mcp_call(server_name, tool_name, False, f"permission={message}")
        log.warning(message)
        raise PermissionError(message)


# ──────────────────────────────────────────────
# Public API
# ──────────────────────────────────────────────

def call_mcp_server(
    server_name: str,
    tool_name: str,
    arguments: dict[str, Any],
    *,
    context_intent: str | None = None,
) -> str:
    """
    Call a tool on a named MCP server using the persistent subprocess.

    The process is started on first use and kept alive for subsequent calls.
    Auto-restarts if the process dies between calls.
    """
    guard = _check_privacy(context_intent)
    if guard:
        return guard

    cfg = _get_server_cfg(server_name)
    if cfg is None:
        return f"MCP server '{server_name}' not found in config."
    _check_allowed_intent(server_name, tool_name, cfg, context_intent)
    if not cfg.get("enabled", False):
        return f"MCP server '{server_name}' is disabled. Enable it in mcp_config.json."

    log.info(f"MCP call: {server_name}/{tool_name} args={list(arguments.keys())}")

    try:
        proc     = _get_process(server_name)
        response = proc.send("tools/call", {"name": tool_name, "arguments": arguments})
        _last_called[server_name] = time.time()

        if "error" in response:
            err = response["error"]
            msg = err.get("message", str(err)) if isinstance(err, dict) else str(err)
            _log_mcp_call(server_name, tool_name, False, f"rpc_error={msg[:80]}")
            log.error(f"MCP RPC error [{server_name}/{tool_name}]: {msg}")
            return f"MCP error: {msg}"

        text_result = _extract_text(response.get("result", {}))
        _log_mcp_call(server_name, tool_name, True, f"len={len(text_result)}")
        return text_result

    except PermissionError:
        raise
    except RuntimeError as e:
        _last_called[server_name] = time.time()
        _log_mcp_call(server_name, tool_name, False, f"err={str(e)[:80]}")
        log.error(f"MCP call failed [{server_name}/{tool_name}]: {e}")
        return f"MCP call failed: {e}"
    except Exception as e:
        _log_mcp_call(server_name, tool_name, False, f"unexpected={str(e)[:80]}")
        log.error(f"Unexpected MCP error [{server_name}/{tool_name}]: {e}")
        return "Something went wrong communicating with the MCP server, Boss."


def list_mcp_tools(server_name: str) -> list[dict]:
    """
    Query the persistent MCP server process for available tools.
    Result cached for the lifetime of the process.
    """
    if server_name in _tool_cache:
        return _tool_cache[server_name]

    cfg = _get_server_cfg(server_name)
    if cfg is None or not cfg.get("enabled", False):
        return []

    try:
        proc     = _get_process(server_name)
        response = proc.send("tools/list", {}, timeout=_STARTUP_TIMEOUT)
        tools    = response.get("result", {}).get("tools", [])
        _tool_cache[server_name] = tools if isinstance(tools, list) else []
        log.info(f"MCP tools listed for {server_name}: {len(_tool_cache[server_name])} tools")
        return _tool_cache[server_name]
    except Exception as e:
        _CREDENTIAL_SERVERS = {"cloudflare", "gdrive", "brave-search"}
        if server_name in _CREDENTIAL_SERVERS:
            log.debug(f"list_mcp_tools skipped [{server_name}]: credentials not configured")
        else:
            log.warning(f"list_mcp_tools failed [{server_name}]: {e}")
        return []


def get_enabled_servers() -> list[str]:
    """Return names of servers marked enabled in config."""
    servers = _load_config().get("servers", {})
    return [name for name, cfg in servers.items() if cfg.get("enabled", False)]


def get_mcp_status() -> dict:
    """Return status dict: {server_name: {enabled, description, tool_count, last_called, running}}."""
    servers = _load_config().get("servers", {})
    status  = {}
    for name, cfg in servers.items():
        tool_count = len(_tool_cache.get(name, []))
        last_ts    = _last_called.get(name)
        last_str   = (
            time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(last_ts))
            if last_ts else "never"
        )
        with _proc_lock:
            proc    = _processes.get(name)
            running = proc is not None and proc.is_alive()
        status[name] = {
            "enabled":         cfg.get("enabled", False),
            "description":     cfg.get("description", ""),
            "tool_count":      tool_count,
            "last_called":     last_str,
            "allowed_intents": cfg.get("allowed_intents", []),
            "running":         running,
        }
    return status
