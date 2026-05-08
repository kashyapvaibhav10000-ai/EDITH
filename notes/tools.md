# tools.py
## Purpose
Human-in-the-loop (HITL) file and shell operations — confirm before destructive actions.
## Key Functions
- `confirm(action_description)` — prompt user Y/N before proceeding
- `read_file(path)` — safe file read with error handling
- `write_file(path, content, interactive)` — write with optional confirm
- `delete_file(path, interactive)` — delete with confirm gate
- `move_file(src, dst)` — move with confirm
- `list_dir(path)` — directory listing
- `run_shell(command)` — shell exec with confirm
## Imports From
none
## Imported By
orchestrator, sandbox, agent
## Status
OK
## Notes
All destructive ops gated by `confirm()`. `interactive=False` bypasses confirm for automated flows.
