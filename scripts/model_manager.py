"""
EDITH Model Manager — Legacy stub

This module previously managed Ollama local model switching.
EDITH now uses cloud-only routing via core/smart_router.py.
Retained as a no-op stub to prevent import errors.
"""

import threading
from config import get_logger

log = get_logger("model_manager")

# PROVIDER_MODELS from smart_router is the source of truth now
PROVIDER_MODELS = {
    "groq":       "llama-3.3-70b-versatile",
    "gemini":     "gemini-2.0-flash",
    "nvidia":     "meta/llama-3.1-70b-instruct",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
}


class ModelManager:
    """Legacy model manager — no-op stub for cloud-only EDITH."""

    def __init__(self):
        self.current_model = "groq/llama-3.3-70b-versatile"
        self._overrides = {}
        self._lock = threading.Lock()

    def switch(self, role: str) -> str:
        log.debug(f"ModelManager.switch({role}) — cloud routing, no local switch needed")
        return self.current_model

    def current(self) -> str:
        return self.current_model

    def prewarm(self, model: str = None):
        log.debug("ModelManager.prewarm() — no-op in cloud mode")

    def prewarm_all(self):
        pass

    def prewarm_async(self):
        pass

    def set_override(self, intent: str, model: str):
        with self._lock:
            self._overrides[intent] = model

    def clear_override(self, intent: str):
        with self._lock:
            self._overrides.pop(intent, None)

    def get_model_for_intent(self, intent: str) -> str:
        return self._overrides.get(intent, self.current_model)

    def list_loaded(self) -> list:
        """Return cloud providers as 'loaded models'."""
        return list(PROVIDER_MODELS.keys())

    def get_status(self) -> dict:
        return {
            "current": self.current_model,
            "mode": "cloud-only",
            "overrides": dict(self._overrides),
            "providers": dict(PROVIDER_MODELS),
        }


# Global instance
manager = ModelManager()


if __name__ == "__main__":
    print(f"Status: {manager.get_status()}")
    print(f"Loaded providers: {manager.list_loaded()}")
    print(f"Model for chat: {manager.get_model_for_intent('chat')}")
