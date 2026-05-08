# ml_router.py
## Purpose
Emotion/urgency detection and response style routing based on query tone.
## Key Functions
- `detect_emotion_urgency(text)` — return (emotion, urgency) tuple from text analysis
- `get_response_style(emotion, urgency)` — map emotion/urgency to style dict
- `route_query(user_input)` — emotion detect → style → inject into prompt context
## Imports From
config
## Imported By
orchestrator, smart_router
## Status
OK
## Notes
Lightweight — uses small Ollama model or heuristics. Not the main routing layer (that's smart_router).
