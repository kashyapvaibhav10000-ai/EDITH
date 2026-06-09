"""
routes/dashboard.py — Dashboard UI and system-status endpoints.
  GET  /dashboard
  GET  /api/system-status   (legacy redirect)
  GET  /api/status
  GET  /api/monitor_schedule
  GET  /api/stats
  GET  /api/provider-latencies
  GET  /api/costs
"""

import asyncio
import datetime as _dt
import os

from fastapi import APIRouter
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse

from config import get_logger

log = get_logger("routes.dashboard")
router = APIRouter()

_DASHBOARD_HTML_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
    "edith_dashboard_v3.html",
)


@router.get("/dashboard", response_class=HTMLResponse)
async def dashboard():
    try:
        with open(_DASHBOARD_HTML_PATH, "r") as f:
            return f.read()
    except Exception as e:
        return HTMLResponse(f"<h1>UI error: {e}</h1>", status_code=500)


@router.get("/api/system-status")
async def api_status_legacy():
    """Legacy redirect to combined /api/status."""
    return RedirectResponse(url="/api/status")


@router.get("/api/status")
async def api_status_combined():
    """Combined system, active provider, and circuit breaker status."""
    try:
        from circuit_breaker import get_all_status
        from smart_router import (
            DAILY_LIMITS, _daily_calls, _has_key,
            _is_provider_cooled_down, _is_under_daily_limit,
        )
        from monitor import check_ram, check_disk, check_cpu
        from search import get_search_status

        cb_states = get_all_status()
        sys_data = await asyncio.to_thread(lambda: {
            "ram": check_ram(),
            "disk": check_disk(),
            "cpu": check_cpu(),
        })

        providers = {}
        for p in ["groq", "gemini", "nvidia", "openrouter"]:
            providers[p] = {
                "has_key": _has_key(p),
                "cooled_down": _is_provider_cooled_down(p),
                "under_limit": _is_under_daily_limit(p),
                "daily_calls": _daily_calls.get(p, 0),
                "daily_limit": DAILY_LIMITS.get(p, 999),
                "circuit": cb_states.get(p, {}).get("state", "CLOSED"),
            }

        active_provider = "unknown"
        for p in ["groq", "gemini", "nvidia", "openrouter"]:
            if (providers[p]["has_key"] and providers[p]["cooled_down"]
                    and providers[p]["under_limit"]
                    and providers[p]["circuit"] != "OPEN"):
                active_provider = p
                break

        return {
            "system": sys_data,
            "active_provider": active_provider,
            "circuit_breakers": cb_states,
            "providers": providers,
            "search_providers": get_search_status(),
            "timestamp": _dt.datetime.now().isoformat(),
        }
    except Exception as e:
        log.error(f"Status API failed: {e}")
        return {"error": str(e)}


@router.get("/api/monitor_schedule")
async def api_monitor_schedule():
    """Return last maintenance timestamps + static schedule."""
    from monitor import _load_maintenance_state
    state = await asyncio.to_thread(_load_maintenance_state)
    return {
        "last_maintenance": state.get("last_maintenance"),
        "last_backup": state.get("last_backup"),
        "static_schedule": [
            {"time": "02:30", "job": "Idle Memory Consolidation", "freq": "daily"},
            {"time": "03:00", "job": "Nightly Backup + Cleanup", "freq": "daily"},
            {"time": "07:00", "job": "Weather Pre-fetch", "freq": "daily"},
            {"time": "08:00", "job": "Daily Report Pre-fetch", "freq": "daily"},
            {"time": "12:00", "job": "Graph Triple Extraction", "freq": "daily"},
            {"freq": "every 5m", "job": "KDE Connect Heartbeat"},
            {"freq": "every 10m", "job": "Proactive Checks"},
            {"time": "21:00", "job": "Weekly Briefing Prep", "freq": "sunday"},
        ],
    }


@router.get("/api/stats")
async def api_stats_proxy():
    """Proxy to dashboard stats."""
    try:
        import dashboard as _dash
        return await asyncio.to_thread(lambda: {
            "system": _dash.get_system_stats(),
            "model": _dash.get_active_model(),
            "logs": _dash.get_recent_logs(),
            "modules": _dash.get_edith_modules(),
            "mcp": _dash.get_mcp_status(),
            "time": __import__("datetime").datetime.now().strftime("%H:%M:%S"),
            "date": __import__("datetime").datetime.now().strftime("%A, %d %B %Y"),
        })
    except Exception as e:
        log.error(f"api/stats proxy error: {e}")
        return {"error": str(e)}


@router.get("/api/provider-latencies")
async def api_provider_latencies():
    """Return latest per-provider latency (seconds) from smart_router."""
    try:
        from smart_router import _provider_latencies
        return _provider_latencies
    except Exception as e:
        return {"error": str(e)}


@router.get("/api/costs")
async def api_costs():
    """Return last 7 days of API call costs grouped by provider."""
    try:
        import time as _t
        import db_pool
        from config import MEMORY_ARCHIVE_PATH
        from smart_router import _daily_calls, DAILY_LIMITS

        since = _t.time() - 7 * 86400
        with db_pool.connection(MEMORY_ARCHIVE_PATH) as conn:
            rows = conn.execute(
                "SELECT provider, SUM(input_tokens_est), SUM(output_tokens_est), COUNT(*) "
                "FROM api_costs WHERE timestamp > ? GROUP BY provider",
                (since,),
            ).fetchall()
        result = {}
        for provider, tin, tout, calls in rows:
            daily = _daily_calls.get(provider, 0)
            limit = DAILY_LIMITS.get(provider, 9999)
            result[provider] = {
                "calls_7d": calls,
                "input_tokens_est": tin or 0,
                "output_tokens_est": tout or 0,
                "cost_usd_est": 0.0,
                "today_calls": daily,
                "daily_limit": limit,
                "near_limit": daily >= limit * 0.8,
            }
        return result
    except Exception as e:
        return {"error": str(e)}
