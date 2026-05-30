"""
handlers/search.py — Search/lookup/weather intent handlers (search, lookup, weather)
"""

import re
import datetime

from config import get_logger
from errors import Result
from context import DispatchContext

log = get_logger("handlers.search")


def _handle_weather(ctx: DispatchContext) -> Result:
    try:
        from weather import get_current_weather, format_weather
        w = get_current_weather()
        if w.ok:
            return Result.success(format_weather(w.value))
        return Result.success("Couldn't fetch weather data right now.")
    except Exception as e:
        return Result.from_exception(e)


def _handle_search(ctx: DispatchContext) -> Result:
    from intent_dispatch import _run_local_exec

    try:
        # Always try local execution before web search
        _local = _run_local_exec(ctx.user_input)
        if _local:
            return Result.success(_local)

        from search import web_search, format_results
        _ist = datetime.timezone(datetime.timedelta(hours=5, minutes=30))
        _now = datetime.datetime.now(_ist)
        _original_query = ctx.user_input
        _search_query = (
            f"Today is {_now.strftime('%A %B %d %Y')}, India IST. {_original_query}"
            if not re.search(r'\b20\d{2}\b', _original_query)
            else _original_query
        )
        results_r = web_search(_search_query)
        results = results_r.value if results_r.ok else []
        search_text = format_results(results)
        if search_text and "error" not in search_text.lower() and "no results" not in search_text.lower():
            today_str = datetime.datetime.now().strftime('%A, %d %B %Y')
            prompt = (
                f"Current Date: {today_str}\n\nUser Query: {ctx.user_input}\n\n"
                f"Search results:\n{search_text}\n\n"
                f"IMPORTANT: Verify dates against Current Date! "
                f"Answer with EXACT facts. No fluff. Just the answer."
            )
            return Result.success(ctx.chat_fn(prompt, intent="search"))
        return Result.success(
            "I searched but couldn't find reliable results right now. "
            "Want me to try a different query, Boss?"
        )
    except Exception as e:
        return Result.from_exception(e)


# "lookup" is an alias for search
_handle_lookup = _handle_search


def handle(intent: str, ctx: DispatchContext) -> str:
    handlers = {
        "search":  _handle_search,
        "lookup":  _handle_lookup,
        "weather": _handle_weather,
    }
    fn = handlers.get(intent)
    if fn is None:
        return f"Unknown search intent: {intent}"
    result = fn(ctx)
    if isinstance(result, Result):
        return str(result.value) if result.ok else str(result.error)
    return str(result)
