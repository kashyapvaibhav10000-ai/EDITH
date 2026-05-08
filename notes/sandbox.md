# sandbox.py

## Purpose
Unsafe command isolation layer — runs untrusted code inside Docker containers (network-disabled, memory-capped)

## Key Functions
- `run_code_in_sandbox(code, language)` — HITL-gated execution of Python or Bash in Docker; returns stdout or error string

## Imports From
- `docker` (docker-py SDK)
- `tools.confirm` (HITL gate)

## Imported By
- `orchestrator.py` (`from sandbox import run_code_in_sandbox`)

## Status
WARN — Requires Docker. Broken without it.

## Notes
Check if Docker daemon running before invoking. Falls back to nothing if absent.
Docker client lazy-init on first call. Images used: `python:3.11-slim` (Python), `alpine:latest` (Bash).
Containers run with `network_disabled=True`, `mem_limit="256m"`, `remove=True`.
