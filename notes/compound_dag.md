# compound_dag.py
## Purpose
Detects multi-step compound intents and executes sub-tasks in DAG topological order.
## Key Functions
- `detect_compound(text)` — returns True if text contains AND/then/after-that chains
- `split_into_tasks(text)` — parse compound sentence into ordered task list
- `DAGExecutor` class — builds NetworkX DAG, executes in topological sort order
## Imports From
config, errors
## Imported By
orchestrator (pre-dispatch compound check)
## Status
OK
## Notes
Phase 3.2. Uses dependency keywords to determine execution order.
