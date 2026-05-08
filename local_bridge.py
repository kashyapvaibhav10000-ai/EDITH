"""
Local Bridge — FastAPI service running on LOCAL_IP:8002
Exposes hardware access (voice I/O, mic control) to cloud via HTTP.
Secured with X-Bridge-Token header authentication.
"""

import os
import sys
import logging
from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

# Ensure EDITH directory is in path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from config import get_logger

log = get_logger("local_bridge")

app = FastAPI(title="EDITH Local Bridge", version="1.0.0")

# ────────────────────────────────────────────────────
# Authentication
# ────────────────────────────────────────────────────
BRIDGE_SECRET = os.getenv("BRIDGE_SECRET", "")

def verify_bridge_token(supplied_token: str) -> bool:
    """Verify X-Bridge-Token header against BRIDGE_SECRET."""
    if not BRIDGE_SECRET:
        log.warning("BRIDGE_SECRET not set — all requests will fail auth")
        return False
    return supplied_token == BRIDGE_SECRET


@app.middleware("http")
async def auth_middleware(request: Request, call_next):
    """Require X-Bridge-Token for all endpoints."""
    supplied_token = request.headers.get("X-Bridge-Token", "")
    if not verify_bridge_token(supplied_token):
        log.warning(f"Auth failed for {request.method} {request.url.path}")
        return JSONResponse(
            status_code=401,
            content={"error": "Unauthorized: missing or invalid X-Bridge-Token"}
        )
    return await call_next(request)


# ────────────────────────────────────────────────────
# Request Models
# ────────────────────────────────────────────────────
class SpeakRequest(BaseModel):
    text: str


# ────────────────────────────────────────────────────
# Endpoints
# ────────────────────────────────────────────────────

@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "ok", "service": "local-bridge"}


@app.post("/speak")
async def speak_endpoint(req: SpeakRequest):
    """
    Speak text using local voice pipeline (aplay/Piper/Chatterbox).
    
    Request body:
        {
            "text": "Hello, world!"
        }
    """
    if not req.text or not req.text.strip():
        return JSONResponse(
            status_code=400,
            content={"error": "text field is required and must not be empty"}
        )
    
    try:
        from voice import speak
        speak(req.text)
        log.info(f"Spoke: {req.text[:80]}")
        return {"status": "ok", "text": req.text}
    except ImportError as e:
        log.error(f"Failed to import speak from voice: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": "voice.speak not available"}
        )
    except Exception as e:
        log.error(f"speak() failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.post("/mic/pause")
async def mic_pause_endpoint():
    """
    Pause wake_listener mic capture.
    Prevents simultaneous mic access between wake listener and browser input.
    """
    try:
        import wake_listener
        wake_listener.pause()
        log.info("Mic paused")
        return {"status": "paused"}
    except ImportError:
        log.error("wake_listener module not found")
        return JSONResponse(
            status_code=500,
            content={"error": "wake_listener not available"}
        )
    except Exception as e:
        log.error(f"mic/pause failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


@app.post("/mic/resume")
async def mic_resume_endpoint():
    """
    Resume wake_listener mic capture.
    Re-enables always-on voice detection.
    """
    try:
        import wake_listener
        wake_listener.resume()
        log.info("Mic resumed")
        return {"status": "resumed"}
    except ImportError:
        log.error("wake_listener module not found")
        return JSONResponse(
            status_code=500,
            content={"error": "wake_listener not available"}
        )
    except Exception as e:
        log.error(f"mic/resume failed: {e}")
        return JSONResponse(
            status_code=500,
            content={"error": str(e)}
        )


if __name__ == "__main__":
    import uvicorn
    
    host = "0.0.0.0"
    port = int(os.getenv("LOCAL_BRIDGE_PORT", "8002"))
    
    if not BRIDGE_SECRET:
        log.error("BRIDGE_SECRET env var not set — refusing to start")
        sys.exit(1)
    
    log.info(f"Starting Local Bridge on {host}:{port}")
    uvicorn.run(app, host=host, port=port)
