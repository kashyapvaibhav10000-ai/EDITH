"""
handlers/calendar.py — Calendar intent handlers (calendar_today, calendar_week, calendar_create)
"""

from errors import Result
from context import DispatchContext


def _handle_calendar_today(ctx: DispatchContext) -> Result:
    try:
        from calendar_reader import get_today_briefing
        return get_today_briefing()
    except Exception as e:
        return Result.from_exception(e)


def _handle_calendar_week(ctx: DispatchContext) -> Result:
    try:
        from calendar_reader import get_week_briefing
        return get_week_briefing()
    except Exception as e:
        return Result.from_exception(e)


def _handle_calendar_create(ctx: DispatchContext) -> Result:
    from handlers.helpers import extract_date, extract_time, extract_event_title

    try:
        from calendar_reader import create_event
        date_str = extract_date(ctx.user_input)
        time_str = extract_time(ctx.user_input)
        title    = extract_event_title(ctx.user_input)
        r = create_event(title, date_str, time_str)
        return Result.success(f"📅 {r.value}") if r.ok else r
    except Exception as e:
        return Result.from_exception(e)


def handle(intent: str, ctx: DispatchContext) -> str:
    handlers = {
        "calendar_today":  _handle_calendar_today,
        "calendar_week":   _handle_calendar_week,
        "calendar_create": _handle_calendar_create,
    }
    fn = handlers.get(intent)
    if fn is None:
        return f"Unknown calendar intent: {intent}"
    result = fn(ctx)
    if isinstance(result, Result):
        return str(result.value) if result.ok else str(result.error)
    return str(result)
