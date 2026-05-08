# voice.py
## Purpose
STT (Whisper/Groq/Sarvam) + TTS (Piper/Groq Orpheus/Chatterbox) with language detection.
## Key Functions
- `transcribe(wav_path)` — STT: try Groq → Sarvam → local Whisper fallback
- `speak(text)` / `speak_stream(text_gen)` — TTS dispatch to best available engine
- `speak_piper(text)` — Piper local TTS
- `speak_groq_orpheus(text)` — Groq Orpheus TTS API
- `speak_chatterbox(text)` — Chatterbox worker subprocess TTS
- `listen()` — mic capture → WAV → transcribe
- `detect_language_hint(audio_data)` — detect Hindi/English for Sarvam routing
- `TranscriptStabilizer` — smooth noisy transcriptions across frames
- `FuzzyCorrector` — fix common mishearings
- `MIC_IN_USE` flag — shared state preventing concurrent mic capture
## Imports From
config
## Imported By
orchestrator, chat_server, edith_widget, wake_listener
## Status
OK
## Notes
`_split_sentences()` used by orchestrator for streaming TTS. `set_last_intent()` / `get_last_intent()` for voice context.
