# EDITH Cleanup Action Plan

Updated: 2026-05-22

## Completed In This Pass

- Fixed the API auth bypass in `chat_server.py`: `/` no longer makes every route public, and `X-API-Key` / bearer auth are both supported.
- Expanded `.gitignore` for runtime DBs, WAL/SHM files, logs, WAVs, local backups, generated caches, and malformed historical scratch files.
- Removed generated/runtime artifacts from git tracking with `git rm --cached`; local copies remain on disk.
- Registered `repos/ayurstock` as a real submodule in `.gitmodules`.
- Split dependency intent into `requirements-core.txt`, `requirements-local.txt`, and `requirements-dev.txt`.
- Added `pytest.ini` markers so default `pytest` skips integration and live-service tests.
- Marked voice endpoint tests as `live_service` and the current integration suite as `integration`.
- Restored local/cloud daemon boundaries: local Telegram alerts are suppressed, and cloud KDE heartbeat is not scheduled.

## Manual Security Follow-Up

- Rotate/revoke the Google OAuth client/token that previously existed in the working tree as `credentials.json`, `token.json`, and `token.pickle`.
- If this repository was pushed anywhere, purge secret history before sharing it further.
- Recreate OAuth credentials locally after rotation; these files are now ignored and should stay untracked.

## Verification Commands

```bash
python -m pytest --collect-only -q
python -m pytest -q
python -m pytest -m integration test/test_integration.py -q
python -m pytest -m live_service tests/test_voice_pipeline.py -q
```

Use `/home/vaibhav/edith-env/bin/python` for the installed service environment. The repo-local `./edith-env` is stale and should be removed once service scripts are standardized.

## Next Plan: Items 6-8

### 6. Split Large Modules

Goal: shrink the five hardest-to-maintain files without changing behavior first.

Order:
1. `chat_server.py`: extract `api_auth.py`, `voice_routes.py`, `mcp_routes.py`, `repo_routes.py`, and `dashboard_routes.py`.
2. `intent_dispatch.py`: extract `system_handlers.py`, `file_handlers.py`, `communication_handlers.py`, `memory_handlers.py`, and keep only the dispatch registry in the root file.
3. `dashboard.py`: separate HTML/template serving from backend status collection.
4. `orchestrator.py`: split history/session management, prompt assembly, and streaming into separate modules.
5. `smart_router.py`: separate provider clients, routing policy, circuit breaker/cost logging, and cache.

Safe method:
- Move one route/handler group at a time.
- Keep old public function names as thin wrappers during the transition.
- After each move, run import checks plus the relevant marked test subset.

### 7. Replace `shell=True` Surfaces

Goal: centralize command execution and remove ad-hoc shell strings from handlers.

Order:
1. Create `command_runner.py` with an allowlist, path jail, timeout, output cap, and structured result object.
2. Convert read-only diagnostics first: CPU, memory, disk, process list, network status.
3. Convert file operations next using Python stdlib where possible instead of shell commands.
4. Keep destructive/mutating actions behind explicit human confirmation.
5. Delete dead cloud-only guarded shell handlers after local behavior is covered.

Acceptance checks:
- `rg "shell=True" --glob "*.py"` should only show explicitly justified legacy callsites.
- Path inputs must resolve inside the configured home/workspace jail.
- Every command path has a timeout and output length cap.

### 8. Move Hardcoded Paths Into Config

Goal: make EDITH portable across local, cloud, and future machines.

Order:
1. Add config values for `EDITH_HOME`, `USER_HOME`, `SERVICE_VENV`, `LOCAL_BRIDGE_URL`, `CHAT_SERVER_URL`, `MCP_NODE_BIN`, and OAuth/token paths.
2. Replace direct `/home/vaibhav/...` literals in service files, tests, MCP config, and scripts.
3. Generate local-only config files from examples rather than committing machine-specific paths.
4. Add a startup validation command that prints which paths are being used and which are missing.

Acceptance checks:
- `rg "/home/vaibhav" --glob "*.py" --glob "*.sh" --glob "*.service" --glob "*.json"` should return only examples/docs or explicitly local defaults.
- CI should run without needing Vaibhav-specific paths.
