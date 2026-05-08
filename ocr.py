"""
EDITH OCR Module — Phase 5.2

Extracts text from images using Tesseract OCR.
Feeds extracted text into the main EDITH pipeline.

Install: sudo apt install tesseract-ocr
"""

import os
import subprocess
import tempfile
from config import get_logger

log = get_logger("ocr")


def is_tesseract_available() -> bool:
    """Check if tesseract is installed."""
    try:
        result = subprocess.run(["tesseract", "--version"],
                                capture_output=True, text=True, timeout=5)
        return result.returncode == 0
    except Exception:
        return False


def extract_text(image_path: str, lang: str = "eng") -> str:
    """Extract text from image using Tesseract.

    Args:
        image_path: path to image file (png, jpg, bmp, tiff)
        lang: Tesseract language code (default: eng)

    Returns:
        Extracted text or error message
    """
    if not os.path.exists(image_path):
        return f"❌ File not found: {image_path}"

    if not is_tesseract_available():
        return "❌ Tesseract not installed. Run: sudo apt install tesseract-ocr"

    try:
        result = subprocess.run(
            ["tesseract", image_path, "stdout", "-l", lang],
            capture_output=True, text=True, timeout=30
        )
        text = result.stdout.strip()
        if not text:
            return "⚠️ No text detected in image."
        log.info(f"OCR extracted {len(text)} chars from {os.path.basename(image_path)}")
        return text
    except subprocess.TimeoutExpired:
        return "❌ OCR timeout (image may be too large)"
    except Exception as e:
        log.error(f"OCR failed: {e}")
        return f"❌ OCR error: {e}"


def extract_from_screenshot() -> str:
    """Take a screenshot and extract text from it."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            screenshot_path = f.name

        subprocess.run(
            ["scrot", screenshot_path],
            capture_output=True, timeout=10
        )

        text = extract_text(screenshot_path)
        os.unlink(screenshot_path)
        return text
    except Exception as e:
        return f"❌ Screenshot OCR failed: {e}"


def extract_from_clipboard() -> str:
    """Extract text from clipboard image."""
    try:
        with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
            clipboard_path = f.name

        result = subprocess.run(
            ["xclip", "-selection", "clipboard", "-t", "image/png", "-o"],
            capture_output=True, timeout=5
        )
        if result.returncode != 0:
            return "⚠️ No image in clipboard"

        with open(clipboard_path, "wb") as f:
            f.write(result.stdout)

        text = extract_text(clipboard_path)
        os.unlink(clipboard_path)
        return text
    except Exception as e:
        return f"❌ Clipboard OCR failed: {e}"


if __name__ == "__main__":
    print(f"Tesseract available: {is_tesseract_available()}")
    import sys
    if len(sys.argv) > 1:
        print(extract_text(sys.argv[1]))
    else:
        print("Usage: python ocr.py <image_path>")
