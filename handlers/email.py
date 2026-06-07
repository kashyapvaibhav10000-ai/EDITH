"""
handlers/email.py — Email intent handlers (email, unread_email)
"""

import re
from errors import Result
from context import DispatchContext


def _parse_limit(user_input: str, memory_context: str, default: int = 5) -> int:
    """Extract email count from user_input first, then memory_context, then default."""
    for text in (user_input, memory_context):
        m = re.search(r'\b(\d+)\b', text or "")
        if m:
            val = int(m.group(1))
            if 1 <= val <= 50:   # sanity-clamp: 1–50 is a reasonable email range
                return val
    return default


def _handle_email(ctx: DispatchContext) -> Result:
    try:
        from email_reader import check_inbox
        limit = _parse_limit(ctx.user_input, ctx.memory_context, default=5)
        return check_inbox(limit=limit, unread_only=False)
    except Exception as e:
        return Result.from_exception(e)


def _handle_unread_email(ctx: DispatchContext) -> Result:
    try:
        from email_reader import check_inbox
        limit = _parse_limit(ctx.user_input, ctx.memory_context, default=5)
        return check_inbox(limit=limit, unread_only=True)
    except Exception as e:
        return Result.from_exception(e)


def handle(intent: str, ctx: DispatchContext) -> str:
    handlers = {
        "email":        _handle_email,
        "unread_email": _handle_unread_email,
    }
    fn = handlers.get(intent)
    if fn is None:
        return f"Unknown email intent: {intent}"
    result = fn(ctx)
    if isinstance(result, Result):
        return str(result.value) if result.ok else str(result.error)
    return str(result)
