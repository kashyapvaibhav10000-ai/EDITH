# circuit_breaker.py
## Purpose
Per-service circuit breaker (CLOSED/OPEN/HALF_OPEN) for Ollama, SearXNG, cloud providers.
## Key Functions
- `CircuitBreaker` class — tracks failure counts, trip threshold, cooldown
- `get_breaker(service)` — get or create breaker for named service
- `is_service_available(service)` — check if service circuit is closed
- `record_success/failure(service)` — update breaker state
- `check_ollama_health()` — ping Ollama and return Result
- `check_searxng_health()` — ping SearXNG and return Result
- `pre_flight_check()` — run all health checks, return status dict
- `get_all_status()` — snapshot all breaker states
## Imports From
config, errors
## Imported By
smart_router (pre-flight before routing)
## Status
OK
## Notes
Phase 4.7. Prevents cascading failures from repeated calls to dead services.
