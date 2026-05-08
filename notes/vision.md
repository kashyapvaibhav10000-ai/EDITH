# vision.py
## Purpose
Image analysis via llava-phi3 (local) with cloud fallback — screenshots and photo analysis.
## Key Functions
- `analyze_screenshot(question)` — take screenshot → analyze with vision model → Result
- `analyze_image(image_path, question)` — analyze arbitrary image file
- `analyze_photo(image_path, question)` — alias for user-provided photos
- `take_screenshot()` — scrot/gnome-screenshot capture
- `_check_vision_model()` — verify llava-phi3 loaded in Ollama
- `_cloud_vision_fallback(image_path, question)` — Gemini Vision API fallback
- `_log_vision_analysis(image_path, description, ocr_text)` — persist to ChromaDB
## Imports From
vault, config, errors
## Imported By
orchestrator, intent_dispatch
## Status
OK
## Notes
Cloud fallback uses Gemini Vision API key from vault. OCR text injected alongside visual description.
