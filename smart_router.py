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
    get_last_call_stats,
    router_status,
)
