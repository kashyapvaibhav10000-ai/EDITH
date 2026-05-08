# video_summarizer.py
## Purpose
YouTube video summarizer — download audio, Whisper transcribe, LLM summarize.
## Key Functions
- `summarize_video()` — interactive flow: get URL → download → transcribe → summarize
- `download_audio(url)` — yt-dlp download to DOWNLOADS_DIR as MP3
- `transcribe_audio(audio_path)` — Whisper transcription via local model
- `summarize_with_qwen(transcript, title)` — LLM summary of transcript
## Imports From
config, smart_router
## Imported By
orchestrator, intent_dispatch
## Status
OK
## Notes
Requires yt-dlp installed. Uses whisper.cpp at path from config.
