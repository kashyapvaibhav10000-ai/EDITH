# Compatibility shim — real module is core/smart_router.py
from core.smart_router import *  # noqa: F401, F403
# Explicitly re-export private names used by routes/dashboard.py
from core.smart_router import (
    _daily_calls,
    _has_key,
    _is_provider_cooled_down,
    _is_under_daily_limit,
    _provider_latencies,
    DAILY_LIMITS,
    smart_call,
    smart_stream,
    get_last_call_stats,
    router_status,
)

# Sync generator alias — orchestrator.py calls `for token in smart_call_stream(...)`
# Must be a sync generator (def + yield), NOT async def.
# DO NOT replace with async def — that breaks the sync for-loop in chat_stream().
def smart_call_stream(prompt: str, intent: str = "chat", system: str = ""):
    """Sync generator streaming wrapper. Delegates to smart_stream (core/smart_router.py)."""
    yield from smart_stream(prompt, intent=intent, system=system)
