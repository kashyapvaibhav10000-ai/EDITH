# errors.py
## Purpose
Shared Result dataclass — typed OK/error return pattern used across all modules.
## Key Functions
- `Result` dataclass — fields: ok (bool), value (Any), error (str)
## Imports From
none
## Imported By
config, agent, calendar_reader, circuit_breaker, compound_dag, data_analyst, db_pool, email_reader, event_bus, intent_dispatch, phone, proactive, rag, search, validator, vision, weather
## Status
OK
## Notes
Avoids exception-based control flow for expected failures. Check `result.ok` before using `result.value`.
