# chatterbox_worker.py
## Purpose
Subprocess worker for Chatterbox TTS — runs in isolated process, reads from stdin.
## Key Functions
- `main()` — stdin JSON loop: receive text, synthesize, write audio to stdout
## Imports From
none (stdlib only, chatterbox pip package)
## Imported By
voice.py (spawns via subprocess)
## Status
OK
## Notes
Launched by `voice._get_chatterbox_worker()`. Kept alive as long-lived process to avoid reload cost.
