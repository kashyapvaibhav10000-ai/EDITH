# security_audit.py
## Purpose
System security audit — checks file permissions, open ports, exposed secrets, outdated packages.
## Key Functions
- `audit()` — run full audit suite, return findings report
- `run(cmd)` — safe subprocess wrapper for audit commands
## Imports From
config
## Imported By
edith.py (manual run), background_daemon (nightly)
## Status
OK
## Notes
Read-only — no modifications. Reports only. Uses shlex.split for safe command construction.
