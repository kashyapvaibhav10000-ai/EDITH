# image_gen.py
## Purpose
AI image generation via Pollinations.ai API with Qwen prompt enhancement.
## Key Functions
- `image_generator()` — interactive flow: get prompt → enhance → generate → save
- `generate_image(prompt)` — HTTP GET to Pollinations, save PNG to IMAGES_DIR
- `enhance_prompt_with_qwen(raw_prompt)` — LLM expands terse prompt into detailed art prompt
## Imports From
config
## Imported By
orchestrator, intent_dispatch
## Status
OK
## Notes
No API key needed (Pollinations free tier). Images saved to IMAGES_DIR with timestamp filenames.
