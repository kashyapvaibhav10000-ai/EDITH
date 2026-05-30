"""
routes/health.py — Phone, weather, and cost health-check endpoints.
  GET /api/phone
  GET /api/weather-status
  GET /api/costs          (also in dashboard.py — kept here for health grouping)
  GET /api/health-check
"""

import asyncio

from fastapi import APIRouter
from config import get_logger

log = get_logger("routes.health")
router = APIRouter()


@router.get("/api/health-check")
async def api_health_check():
    """Run full system validation and return health report as JSON."""
    from validator import validate_all
    results = validate_all(emit_events=False)
    return results


@router.get("/api/phone")
async def api_phone():
    """KDE Connect battery + last notification. Returns offline if unavailable."""
    try:
        from phone import get_battery, get_notifications, phone_status

        def _fetch():
            battery_raw = get_battery()
            notifs_raw = get_notifications()
            status = phone_status()
            return battery_raw, notifs_raw, status

        battery_raw, notifs_raw, status = await asyncio.to_thread(_fetch)

        if any(kw in status.lower() for kw in ("not connected", "not installed", "unavailable")):
            return {"battery": None, "status": "offline", "last_notification": None}

        import re as _re
        battery_match = _re.search(r"(\d+)", battery_raw or "")
        battery = int(battery_match.group(1)) if battery_match else None

        notif_lines = [l.strip() for l in (notifs_raw or "").splitlines() if l.strip()]
        last_notif = notif_lines[0] if notif_lines else None

        return {"battery": battery, "status": "online", "last_notification": last_notif}
    except Exception as e:
        return {"battery": None, "status": "offline", "last_notification": None, "error": str(e)}


@router.get("/api/weather-status")
async def api_weather_status():
    """Return current weather from weather.py get_current_weather()."""
    try:
        from weather import get_current_weather
        result = await asyncio.to_thread(get_current_weather)
        if result is None:
            return {"error": "Weather unavailable"}
        return result
    except Exception as e:
        return {"error": str(e)}
