# EDITH Dependency Audit
Generated: 2026-05-07

## A) requirements.txt
**274 entries** (275 lines; 1 commented: `# pywhispercpp==1.4.1  # replaced by faster-whisper`)

## B) Installed in edith-env
**278 packages**

Deviations from requirements.txt:
| Package | Status |
|---------|--------|
| `pywhispercpp 1.4.1` | Installed but commented out — stale, remove |
| `rapidfuzz 3.14.5` | Installed but missing from requirements.txt — add it |

## C) External Imports Actually Used in Source

### Core runtime
| Package | Used in |
|---------|---------|
| `argon2`, `bcrypt`, `cryptography` | vault.py |
| `fastapi`, `uvicorn`, `starlette` | chat_server.py |
| `chromadb` | rag.py, code_rag.py |
| `llama_index` | rag.py, code_rag.py |
| `networkx` | graph_memory.py |
| `ollama` | smart_router.py, model_manager.py |
| `vosk` | wake_listener.py |
| `faster_whisper` | voice.py |
| `PyQt6` | edith_widget.py |
| `python_telegram_bot` | telegram_bot.py |
| `imapclient` | email_reader.py |
| `google-api-python-client`, `google-auth-oauthlib` | calendar_reader.py, edith_email.py |
| `pynput`, `evdev` | voice.py, wake_listener.py |
| `pytesseract`, `pillow` | ocr.py |
| `pandas`, `matplotlib`, `openpyxl` | data_analyst.py |
| `psutil` | monitor.py, background_daemon.py |
| `docker` | sandbox.py |
| `schedule` | background_daemon.py |
| `requests` | multiple |
| `python-dotenv` | config.py |
| `aiosqlite`, `SQLAlchemy` | episodic_memory.py, session.py |
| `piper_tts`, `sounddevice`, `soundfile`, `PyAudio`, `webrtcvad` | voice.py |
| `yt_dlp` | video_summarizer.py |
| `simplenote` | devlog.py |
| `semantic_router` | ml_router.py |
| `requests` | multiple |

## D) Dead Weight — Installed, ZERO Imports in Source
Remove these to slim env:

| Package(s) | Notes |
|------------|-------|
| `langchain`, `langchain-community`, `langchain-core`, `langchain-text-splitters`, `langchain-classic` | Heavy, unused |
| `langgraph`, `langgraph-checkpoint`, `langgraph-prebuilt`, `langgraph-sdk`, `langsmith` | Heavy, unused |
| `litellm` | Heavy, unused |
| `kubernetes` | Unused |
| `numba`, `llvmlite` | Unused |
| `jupyter_client`, `jupyter_core`, `jupyterlab_pygments`, `nbclient`, `nbconvert`, `nbformat` | Notebook stack, unused |
| `ipython` | Unused |
| `aurelio-sdk` | Unused |
| `banks` | Unused |

## E) chatterbox-env
Not found at `/home/vaibhav/chatterbox-env`. `chatterbox_worker.py` spawned via subprocess from main edith-env.

## F) npm Globals (MCP Servers)
| Package | Version |
|---------|---------|
| `@cloudflare/mcp-server-cloudflare` | 0.2.0 |
| `@modelcontextprotocol/server-brave-search` | 0.6.2 |
| `@modelcontextprotocol/server-filesystem` | 2026.1.14 |
| `@modelcontextprotocol/server-gdrive` | 2025.1.14 |
| `@modelcontextprotocol/server-github` | 2025.4.8 |
| `obsidian-mcp` | 1.0.6 |

No `package.json` in EDITH dir — all global, not project-scoped.

## G) System Binaries Required
| Binary | Used by | Notes |
|--------|---------|-------|
| `aplay` | voice.py | audio playback |
| `curl` | circuit_breaker.py, monitor.py | Ollama health check |
| `firejail` | sandbox.py | optional sandboxing |
| `kdeconnect-cli` | phone.py | KDE Connect bridge |
| `ollama` | model_manager.py | model lifecycle |
| `pgrep` / `pkill` | background_daemon.py, voice.py | process management |
| `sudo ufw` | monitor.py | firewall status |
| `tesseract` | ocr.py | OCR engine |
| `xdg-open` | dashboard.py, tools.py | open files/URLs |

## Action Items
1. `pip uninstall pywhispercpp` — stale, replaced by faster-whisper
2. Add `rapidfuzz` to requirements.txt — installed but undocumented
3. Purge dead stack: langchain/langgraph/litellm/kubernetes/numba/jupyter — major size reduction
