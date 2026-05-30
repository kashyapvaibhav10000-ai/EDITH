"""
handlers/system.py — System/session intent handlers (wake, session_end, system_health)
"""

from errors import Result
from context import DispatchContext


def _handle_wake(ctx: DispatchContext) -> Result:
    return Result.success("I'm here, Boss. What do you need?")


def _handle_session_end(ctx: DispatchContext) -> Result:
    return Result.success(
        "Session noted. Goodbye, Boss. All conversation history has been saved. 👋"
    )


def _handle_system_health(ctx: DispatchContext) -> Result:
    try:
        from validator import validate_all, format_health_report
        results = validate_all()
        return Result.success(format_health_report(results))
    except Exception as e:
        return Result.from_exception(e)


def handle(intent: str, ctx: DispatchContext) -> str:
    handlers = {
        "wake":          _handle_wake,
        "session_end":   _handle_session_end,
        "system_health": _handle_system_health,
    }
    fn = handlers.get(intent)
    if fn is None:
        return f"Unknown system intent: {intent}"
    result = fn(ctx)
    if isinstance(result, Result):
        return str(result.value) if result.ok else str(result.error)
    return str(result)
