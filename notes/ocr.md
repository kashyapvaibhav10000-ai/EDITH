# ocr.py
## Purpose
Tesseract OCR wrapper — extract text from images, screenshots, or clipboard.
## Key Functions
- `extract_text(image_path, lang)` — run Tesseract on image file, return text
- `extract_from_screenshot()` — take screenshot then OCR
- `extract_from_clipboard()` — read image from clipboard then OCR
- `is_tesseract_available()` — check Tesseract binary exists
## Imports From
config
## Imported By
vision.py (OCR fallback), intent_dispatch
## Status
OK
## Notes
Phase 5.2. Degrades gracefully if Tesseract not installed.
