# search.py
## Purpose
Multi-provider web search with daily quota tracking — SearXNG/Serper/Exa/Tavily/DDG.
## Key Functions
- `web_search(query, num_results)` — route to best available provider, return Result
- `_search_searxng/serper/exa/tavily/duckduckgo(query, num_results)` — provider implementations
- `classify_search_query(query)` — detect query type (news/academic/general)
- `format_results(results)` — format result list for display
- `get_search_status()` — provider availability + usage stats
- `_check_quota(provider)` / `_track_usage(provider)` — daily limit enforcement
- `_reset_daily_if_needed()` — reset counters at midnight
## Imports From
vault, config, errors
## Imported By
orchestrator, intent_dispatch
## Status
OK
## Notes
Quota limits in SEARCH_DAILY_LIMITS config. SearXNG preferred (local, no quota). DDG always-available fallback.
