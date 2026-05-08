# wake_listener.py
## Purpose
Always-on Vosk wake-word listener — detects "Hey EDITH" and triggers voice session.
## Key Functions
- `listen_loop()` — continuous Vosk STT loop, check each utterance for wake word
- `is_fuzzy_match(recognized_text)` — SequenceMatcher check against wake word variants
- `_trigger_wake_sequence()` — play chime + start voice session
- `pause()` / `resume()` — suspend/resume listener (during active voice session)
## Imports From
config, voice
## Imported By
edith_widget, background_daemon (spawns as subprocess)
## Status
OK
## Notes
Vosk model path from VOSK_MODEL_PATH config. Pauses during TTS/STT to prevent echo. MIC_IN_USE flag coordination with voice.py.
