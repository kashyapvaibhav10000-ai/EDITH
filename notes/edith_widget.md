# edith_widget.py
## Purpose
PyQt6 system tray widget with floating chat overlay and hotkey activation.
## Key Functions
- `EdithWidget` class — main QWidget with chat history, input box, send button
- `HotkeyListener(QObject)` — pynput keyboard listener, emits hotkey signal
- `ApiWorker(QObject)` — background thread: HTTP POST to chat_server, emit response
- `VoiceWorker(QObject)` — background thread: mic capture → transcription → send
## Imports From
voice, wake_listener
## Imported By
background_daemon (spawns as subprocess via edith-widget.service)
## Status
OK
## Notes
Requires PyQt6 + pynput. MIC_IN_USE flag shared with voice module to prevent overlap.
