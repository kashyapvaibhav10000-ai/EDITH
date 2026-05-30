"""
handlers/memory_handler.py — Memory/knowledge intent handlers (rag, profile, briefing)
"""

import re

from errors import Result
from context import DispatchContext


def _handle_rag(ctx: DispatchContext) -> Result:
    try:
        from rag import build_index, query_rag
        idx_r = build_index()
        if not idx_r.ok:
            return Result.success(f"📚 {idx_r.error}")
        r = query_rag(ctx.user_input, idx_r.value)
        return r
    except Exception as e:
        return Result.from_exception(e)


def _handle_profile(ctx: DispatchContext) -> Result:
    try:
        from cognitive_profile import (
            get_full_profile, detect_drift, get_prime_directive, set_prime_directive,
        )
        lower = ctx.user_input.lower()
        if "drift" in lower:
            return Result.success(f"🧭 Drift Check:\n\n{detect_drift()}")
        if "prime directive" in lower or "north star" in lower:
            if "set" in lower or "change" in lower:
                new = re.sub(
                    r"(set|change|update|my)\s*(prime directive|north star)\s*(to|as)?\s*",
                    "", ctx.user_input, flags=re.IGNORECASE
                ).strip()
                if new:
                    set_prime_directive(new)
                    return Result.success(f"🎯 Prime directive updated to: {new}")
                return Result.success("🎯 What should the new prime directive be?")
            return Result.success(f"🎯 Prime Directive: {get_prime_directive()}")
        return Result.success(f"📊 Cognitive Profile:\n\n{get_full_profile()}")
    except Exception as e:
        return Result.from_exception(e)


def _handle_briefing(ctx: DispatchContext) -> Result:
    try:
        from life_os import weekly_briefing
        return Result.success(f"📋 Weekly Briefing:\n\n{weekly_briefing()}")
    except Exception as e:
        return Result.from_exception(e)


def handle(intent: str, ctx: DispatchContext) -> str:
    handlers = {
        "rag":      _handle_rag,
        "profile":  _handle_profile,
        "briefing": _handle_briefing,
    }
    fn = handlers.get(intent)
    if fn is None:
        return f"Unknown memory intent: {intent}"
    result = fn(ctx)
    if isinstance(result, Result):
        return str(result.value) if result.ok else str(result.error)
    return str(result)
