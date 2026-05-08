# patch_devpanel.py
## Purpose
One-shot script to patch devpanel endpoints into dashboard.py (with backup).
## Key Functions
- `devpanel_modules()` — FastAPI endpoint: return module list
- `devpanel_query(req)` — FastAPI endpoint: run LLM query
## Imports From
none (standalone patch script)
## Imported By
none (run once)
## Status
OK
## Notes
Creates dashboard.py.bak before patching. Run once during setup.
