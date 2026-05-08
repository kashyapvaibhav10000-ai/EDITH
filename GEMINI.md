# EDITH - Personal AI Assistant
- Python project
- Venv at: /home/vaibhav/edith-env
- Run with: /home/vaibhav/edith-env/bin/python /home/vaibhav/EDITH/edith.py
- Uses Vosk (wake word), pywhispercpp (transcription), piper TTS, webrtcvad, Ollama (Qwen 2.5 1.5B)
- Multi-provider AI: Groq → Gemini → NVIDIA → OpenRouter

# Project Type: Python (NOT Java, NOT Android)
# Ignore all Java warnings — whisper.cpp folder is a compiled binary dependency, do not index it.

# Architecture
- Hub-and-spoke: orchestrator.py is the central brain
- config.py: all paths, models, logging, safe Ollama wrappers
- intent.py: regex-based intent classification (21 intents)
- session.py: session lifecycle + query tracking

# Vision System (Cognitive AI)
- cognitive_profile.py: ChromaDB user profiling + drift detection
- self_improve.py: ArXiv paper fetch + upgrade proposals
- life_os.py: 5-branch decision simulation + weekly briefings + persistent open loops
- council.py: 4-persona roundtable (Strategist, Critic, Builder, Wildcard) with memory
- telegram_bot.py: full intent routing + scheduled briefing + drift alerts