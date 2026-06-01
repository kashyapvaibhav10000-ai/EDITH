"""
EDITH chat_server.py — thin app factory.

Route logic lives in routes/:
  routes/chat.py      — /api/chat, /api/chat/stream
  routes/dashboard.py — /dashboard, /api/status, /api/monitor_schedule, /api/stats, /api/costs
  routes/memory.py    — /api/last-memory, /api/traces/recent, /api/recent_traces, /api/feedback
  routes/logs.py      — /api/logs/stream
  routes/health.py    — /api/health-check, /api/phone, /api/weather-status
  routes/mcp.py       — /api/mcp/*
  routes/sessions.py  — /api/sessions/*, /api/devpanel/*, /webhook/*, /tg_webhook
  routes/repo.py      — /api/repo/*
Voice routes registered via voice_routes.register_voice_routes(app).
"""

import gc
import glob
import os
import sys
import threading

import psutil
import uvicorn
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles

sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import get_logger
from intent_dispatch import get_pending_action  # noqa: F401 — re-exported for routes

log = get_logger("chat_server")

# ── App init ───────────────────────────────────
app = FastAPI()

# ── Shutdown ───────────────────────────────────
@app.on_event("startup")
async def startup_event():
    import threading
    def _warmup():
        try:
            from voice import _get_chatterbox_worker
            _get_chatterbox_worker()
            log.info("Chatterbox warmed up on startup")
        except Exception as e:
            log.warning(f"Chatterbox warmup skipped: {e}")
    threading.Thread(target=_warmup, daemon=True, name="chatterbox-startup-warmup").start()

@app.on_event("shutdown")
async def shutdown_event():
    for f in glob.glob("/tmp/edith_*.lock") + glob.glob("/tmp/edith_*.pid"):
        try:
            os.remove(f)
        except Exception:
            pass
    pid_file = "/tmp/edith_daemon.pid"
    if os.path.exists(pid_file):
        try:
            with open(pid_file) as f:
                pid = int(f.read())
            os.kill(pid, 15)
        except Exception:
            pass
    log.info("EDITH shutdown complete")

# ── Middleware ─────────────────────────────────
from middleware.logging import logging_middleware
from middleware.rate_limit import rate_limit_middleware

app.add_middleware(logging_middleware)
app.add_middleware(rate_limit_middleware)

_ALLOWED_ORIGINS = [
    o.strip()
    for o in os.getenv("EDITH_ALLOWED_ORIGINS", "http://localhost:8001,http://127.0.0.1:8001").split(",")
    if o.strip()
]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_ALLOWED_ORIGINS,
    allow_methods=["POST", "GET"],
    allow_headers=["Content-Type", "X-API-Key", "Authorization", "X-Admin-Token"],
    allow_credentials=False,
)

# ── Static files ───────────────────────────────
_STATIC_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static")
if os.path.isdir(_STATIC_DIR):
    app.mount("/static", StaticFiles(directory=_STATIC_DIR), name="static")

# ── Voice routes (legacy registration) ────────
from voice_routes import register_voice_routes
register_voice_routes(app)

# ── Routers ────────────────────────────────────
from routes.chat import router as chat_router
from routes.dashboard import router as dashboard_router
from routes.memory import router as memory_router
from routes.logs import router as logs_router
from routes.health import router as health_router
from routes.mcp import router as mcp_router
from routes.sessions import router as sessions_router
from routes.repo import router as repo_router

app.include_router(chat_router)
app.include_router(dashboard_router)
app.include_router(memory_router)
app.include_router(logs_router)
app.include_router(health_router)
app.include_router(mcp_router)
app.include_router(sessions_router)
app.include_router(repo_router)

# ── Root redirect ──────────────────────────────
@app.get("/", response_class=HTMLResponse)
def index():
    return RedirectResponse(url="/dashboard")

# ── Repo DNA event bus (module-level shared state for routes/repo.py) ─────────
_adapt_results: dict = {}
_adapt_meta: dict = {}

try:
    from repo_dna import mark_adapted as _mark_adapted
    from event_bus import bus as _bus, Topic as _Topic

    def _on_agent_done(payload: dict) -> None:
        tid = payload.get("task_id", "")
        _adapt_results[tid] = {"status": "done", "summary": payload.get("summary", "")}
        if len(_adapt_results) > 200:
            _adapt_results.pop(next(iter(_adapt_results)))
        meta = _adapt_meta.pop(tid, None)
        if meta:
            try:
                _mark_adapted(meta["repo_url"], meta["capability"], meta["target_file"])
            except Exception as _me:
                log.warning(f"[repo_adapt] mark_adapted failed: {_me}")

    def _on_agent_error(payload: dict) -> None:
        tid = payload.get("task_id", "")
        _adapt_results[tid] = {"status": "failed", "error": payload.get("error", "")}
        if len(_adapt_results) > 200:
            _adapt_results.pop(next(iter(_adapt_results)))
        _adapt_meta.pop(tid, None)

    _bus.subscribe_fn(_Topic.AGENT_DONE, _on_agent_done)
    _bus.subscribe_fn(_Topic.AGENT_ERROR, _on_agent_error)
except Exception:
    pass

# ── Background helpers ─────────────────────────
def _memory_monitor():
    import time
    process = psutil.Process(os.getpid())
    while True:
        try:
            time.sleep(300)
            memory_mb = process.memory_info().rss / 1024 / 1024
            log.info(f"Memory usage: {memory_mb:.2f} MB")
            if memory_mb > 500:
                log.warning(f"High memory ({memory_mb:.2f} MB). Running GC.")
                gc.collect()
                log.info(f"After GC: {process.memory_info().rss / 1024 / 1024:.2f} MB")
        except Exception as e:
            log.error(f"Memory monitor error: {e}")


def _graceful_shutdown():
    log.info("Graceful shutdown initiated — flushing data...")
    try:
        from devlog import _sync_to_simplenote
        t = threading.Thread(target=_sync_to_simplenote, daemon=True)
        t.start()
        t.join(timeout=3.0)
    except Exception as e:
        log.error(f"DevLog flush failed: {e}")
    try:
        from config import get_chroma_client
        client = get_chroma_client()
        if hasattr(client, "persist"):
            client.persist()
    except Exception:
        pass
    try:
        from session import _persist_session
        _persist_session()
    except Exception as e:
        log.error(f"Session save failed: {e}")

# ── Entry point ────────────────────────────────
if __name__ == "__main__":
    import atexit
    import signal

    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    atexit.register(_graceful_shutdown)

    from devlog import start_devlog
    start_devlog()
    log.info("DevLog sync thread started from chat_server.")

    threading.Thread(target=_memory_monitor, daemon=True).start()
    log.info("Starting EDITH chat_server on http://127.0.0.1:8001")
    uvicorn.run(app, host="127.0.0.1", port=8001)
