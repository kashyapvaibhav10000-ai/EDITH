# agent.py
## Purpose
State machine execution loop for multi-step agentic tasks with SQLite persistence.
## Key Functions
- `run_agent(task, context)` — execute full planning→executing→validating→done loop
- `dry_run_agent(task, context)` — preview plan without executing
- `format_dry_run(run)` — format dry run output for display
- `_persist(run)` — save AgentRun state to SQLite agent_runs table
- `_load_run(task_id)` — reload interrupted run from DB
- `compute_confidence(cmd, step)` — score command safety confidence
- `interrupt_agent()` / `clear_interrupt()` — signal mid-run stop
- `AgentState` enum — PLANNING/EXECUTING/VALIDATING/REPLANNING/DONE/FAILED
## Imports From
config, errors, event_bus
## Imported By
orchestrator
## Status
OK
## Notes
Uses `is_dangerous()` + DANGEROUS_PATTERNS from config for command safety gate.
