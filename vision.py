"""
EDITH Vision Module — Screenshot + Image Analysis

Supports multiple screenshot tools (KDE Spectacle, gnome-screenshot, scrot, ImageMagick).
Graceful error handling — never exposes raw tracebacks to the user.
"""

import subprocess
import os
import json
import datetime
import vault
import time
import base64
from config import MODELS, get_logger, EDITH_PATH
from errors import Result

log = get_logger("vision")

_VISION_LOG_DIR = os.path.join(EDITH_PATH, "vision")


def _log_vision_analysis(image_path: str, description: str, ocr_text: str = ""):
    """Persist vision analysis to JSON sidecar + ChromaDB."""
    try:
        os.makedirs(_VISION_LOG_DIR, exist_ok=True)
        ts = datetime.datetime.now()
        fname = ts.strftime("%Y%m%d_%H%M%S") + ".json"
        record = {
            "timestamp": ts.isoformat(),
            "image_path": image_path,
            "description": description,
            "ocr_text": ocr_text,
        }
        with open(os.path.join(_VISION_LOG_DIR, fname), "w") as f:
            json.dump(record, f, indent=2)
    except Exception as e:
        log.warning(f"Vision log write failed: {e}")

SCREENSHOT_PATH = "/tmp/edith_screenshot.png"

# Screenshot tools in priority order (KDE → GNOME → Generic → ImageMagick)
SCREENSHOT_COMMANDS = [
    # KDE Spectacle (Wayland + X11)
    ["spectacle", "--background", "--nonotify", "--fullscreen", "--output", SCREENSHOT_PATH],
    # GNOME Screenshot
    ["gnome-screenshot", "-f", SCREENSHOT_PATH],
    # scrot (X11 only)
    ["scrot", SCREENSHOT_PATH],
    # ImageMagick import (X11 only)
    ["import", "-window", "root", SCREENSHOT_PATH],
]


def take_screenshot():
    """Try multiple screenshot tools until one works."""
    # Remove old screenshot if exists
    if os.path.exists(SCREENSHOT_PATH):
        try:
            os.remove(SCREENSHOT_PATH)
        except Exception:
            pass

    for cmd in SCREENSHOT_COMMANDS:
        tool_name = cmd[0]
        try:
            # Check if tool exists
            which = subprocess.run(["which", tool_name], capture_output=True, timeout=5)
            if which.returncode != 0:
                continue

            result = subprocess.run(cmd, capture_output=True, text=True, timeout=10)
            # Give it a moment to write the file
            time.sleep(0.3)

            if result.returncode == 0 and os.path.exists(SCREENSHOT_PATH):
                file_size = os.path.getsize(SCREENSHOT_PATH)
                if file_size > 100:  # Valid image should be > 100 bytes
                    log.info(f"Screenshot taken with {tool_name} ({file_size} bytes)")
                    return SCREENSHOT_PATH
                else:
                    log.warning(f"{tool_name} produced empty/tiny file ({file_size} bytes)")
            else:
                log.warning(f"{tool_name} failed: returncode={result.returncode}, stderr={result.stderr[:100] if result.stderr else 'none'}")
        except subprocess.TimeoutExpired:
            log.warning(f"{tool_name} timed out")
        except Exception as e:
            log.warning(f"{tool_name} error: {e}")
            continue

    log.error("All screenshot tools failed")
    return None


def _check_vision_model():
    """Check if the vision model is available in Ollama."""
    try:
        import ollama
        models = ollama.list(timeout=60)
        model_list = models.get("models", []) if isinstance(models, dict) else getattr(models, "models", [])
        model_names = []
        for m in model_list:
            if isinstance(m, dict):
                model_names.append(m.get("name", ""))
            else:
                model_names.append(str(getattr(m, "model", "")))
        target = MODELS.get("vision", "llava-phi3:latest")
        # Check partial match (e.g., "gemma4:e2b" matches "gemma4:e2b")
        for name in model_names:
            if target.split(":")[0] in str(name):
                return True
        log.warning(f"Vision model '{target}' not found. Available: {model_names[:5]}")
        return False
    except Exception as e:
        log.error(f"Cannot check Ollama models: {e}")
        return False


def analyze_image(image_path, question="What do you see in this image?"):
    """Analyze an image using the vision model (gemma4 multimodal via chat API)."""
    try:
        import ollama
        # gemma4 uses chat API with image content
        result = ollama.chat(
            model=MODELS["vision"],
            messages=[{
                "role": "user",
                "content": question,
                "images": [image_path],
            }],
            options={"num_predict": 512},
            timeout=60,
        )
        response = ""
        if isinstance(result, dict):
            response = result.get("message", {}).get("content", "").strip()
        else:
            response = str(getattr(result, "message", {}).get("content", "")).strip() if hasattr(result, "message") else ""
        if response:
            return response
        return "I analyzed the image but couldn't generate a description. Try asking a more specific question."
    except Exception as e:
        error_str = str(e).lower()
        if "timeout" in error_str or "timed out" in error_str:
            return "Vision analysis taking too long — the model might be loading. Try again in a moment."
        if "connection" in error_str or "refused" in error_str:
            # Try Gemini cloud fallback
            cloud_result = _cloud_vision_fallback(image_path, question)
            if cloud_result:
                return cloud_result
            return "Ollama isn't running. Start it with `ollama serve` and try again."
        if "not found" in error_str or "does not exist" in error_str:
            return f"Vision model ({MODELS['vision']}) isn't installed. Run `ollama pull {MODELS['vision']}` to set it up."
        log.error(f"Vision analysis failed: {e}")
        # Try cloud fallback on any error
        cloud_result = _cloud_vision_fallback(image_path, question)
        if cloud_result:
            return cloud_result
        return "Ran into an issue analyzing that image. Want me to try again?"


def _cloud_vision_fallback(image_path, question):
    """Fallback: use Gemini API for vision when Ollama fails."""
    try:
        from dotenv import load_dotenv
        load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
        api_key = vault.get_secret("GEMINI_API_KEY", os.getenv("GEMINI_API_KEY", ""))
        if not api_key:
            return None

        import requests
        with open(image_path, "rb") as f:
            image_data = base64.b64encode(f.read()).decode("utf-8")

        # Detect MIME type
        ext = os.path.splitext(image_path)[1].lower()
        mime = {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
                '.gif': 'image/gif', '.webp': 'image/webp'}.get(ext, 'image/png')

        resp = requests.post(
            f"https://generativelanguage.googleapis.com/v1beta/models/gemini-2.0-flash:generateContent?key={api_key}",
            headers={"Content-Type": "application/json"},
            json={"contents": [{"parts": [
                {"inline_data": {"mime_type": mime, "data": image_data}},
                {"text": question}
            ]}]},
            timeout=30,
        )
        resp.raise_for_status()
        data = resp.json()
        text = data["candidates"][0]["content"]["parts"][0]["text"]
        log.info("Vision: used Gemini cloud fallback")
        return text
    except Exception as e:
        log.warning(f"Cloud vision fallback failed: {e}")
        return None


def analyze_screenshot(question="What is on my screen right now?") -> Result:
    """Take a screenshot and analyze it. Returns Result[str]."""
    try:
        if not _check_vision_model():
            return Result.success(
                f"I can't analyze your screen right now — the vision model ({MODELS['vision']}) "
                f"isn't loaded in Ollama. Run `ollama pull {MODELS['vision']}` to install it."
            )
        path = take_screenshot()
        if path:
            log.info("Screenshot captured, analyzing...")
            description = analyze_image(path, question)
            _log_vision_analysis(path, description)
            return Result.success(description)
        return Result.success(
            "Couldn't capture your screen. No screenshot tool found. "
            "Install one: `sudo pacman -S spectacle` (KDE) or `sudo pacman -S scrot` (generic)."
        )
    except Exception as e:
        return Result.from_exception(e)


def analyze_photo(image_path, question="What do you see in this image?"):
    """Analyze a user-provided image file."""
    if not os.path.exists(image_path):
        return f"I can't find that file: {image_path}. Double-check the path and try again."

    if not _check_vision_model():
        return f"The vision model ({MODELS['vision']}) isn't loaded. Run `ollama pull {MODELS['vision']}` first."

    log.info(f"Analyzing photo: {image_path}")
    description = analyze_image(image_path, question)
    _log_vision_analysis(image_path, description)
    return description


if __name__ == "__main__":
    print("EDITH Vision Test")
    print("1. Analyze screenshot")
    print("2. Analyze photo")
    choice = input("Choose (1/2): ").strip()
    if choice == "1":
        q = input("What do you want to know about your screen? ").strip()
        result = analyze_screenshot(q)
        print(f"\nEDITH sees: {result}")
    elif choice == "2":
        path = input("Enter image path: ").strip()
        q = input("What do you want to know? ").strip()
        result = analyze_photo(path, q)
        print(f"\nEDITH sees: {result}")
