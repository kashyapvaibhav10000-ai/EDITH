"""
handlers/email.py — Email intent handlers (email, unread_email)
"""

from errors import Result
from context import DispatchContext


def _handle_email(ctx: DispatchContext) -> Result:
    try:
        from email_reader import check_inbox
        return check_inbox(limit=5, unread_only=False)
    except Exception as e:
        return Result.from_exception(e)


def _handle_unread_email(ctx: DispatchContext) -> Result:
    try:
        from email_reader import check_inbox
        return check_inbox(limit=5, unread_only=True)
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
