"""
EDITH Model Manager — Phase 3.3

Model lifecycle: switch, pre-warm, list loaded, per-intent override.
Pre-warm loads model into RAM without generating tokens (fast first-call).
"""

import subprocess
import time
import threading
from config import MODELS, OLLAMA_URL, get_logger

log = get_logger("model_manager")


class ModelManager:
    def __init__(self):
        self.current_model = None
        self._warm_models = set()    # Models already loaded in RAM
        self._overrides = {}         # Per-intent overrides: {"code": "deepseek-coder"}
        self._lock = threading.Lock()

    def switch(self, role: str) -> str:
        target = self._overrides.get(role, MODELS.get(role))
        if not target:
            raise ValueError(f"Unknown role: {role}")
        if self.current_model == target:
            return target
        if self.current_model:
            subprocess.run(["ollama", "stop", self.current_model], capture_output=True)
            time.sleep(1)
        self.current_model = target
        log.info(f"Switched to {target}")
        return target

    def current(self) -> str:
        return self.current_model or MODELS["chat"]

    # ──────────────────────────────────────────────
    # Phase 3.3: Pre-warmer
    # ──────────────────────────────────────────────
    def prewarm(self, model: str = None):
        """Pre-warm a model by loading it into RAM without generating.

        This sends a tiny prompt to Ollama to trigger model loading.
        """
        target = model or MODELS.get("chat")
        if target in self._warm_models:
            return

        try:
            import requests
            resp = requests.post(
                f"{OLLAMA_URL}/api/generate",
                json={"model": target, "prompt": ".", "stream": False,
                      "options": {"num_predict": 1}},
                timeout=120
            )
            if resp.status_code == 200:
                self._warm_models.add(target)
                log.info(f"Pre-warmed model: {target}")
            else:
                log.warning(f"Pre-warm failed for {target}: {resp.status_code}")
        except Exception as e:
            log.error(f"Pre-warm error for {target}: {e}")

    def prewarm_all(self):
        """Pre-warm all configured models in background."""
        unique_models = set(self._overrides.values()) | set(MODELS.values())
        for model in unique_models:
            try:
                self.prewarm(model)
            except Exception:
                pass

    def prewarm_async(self):
        """Pre-warm all models in a background thread."""
        t = threading.Thread(target=self.prewarm_all, daemon=True)
        t.start()

    # ──────────────────────────────────────────────
    # Phase 3.3: Per-intent override
    # ──────────────────────────────────────────────
    def set_override(self, intent: str, model: str):
        """Override the model for a specific intent.

        Example: manager.set_override("code", "deepseek-coder:6.7b")
        """
        with self._lock:
            self._overrides[intent] = model
            log.info(f"Model override set: {intent} → {model}")

    def clear_override(self, intent: str):
        """Remove a per-intent override."""
        with self._lock:
            self._overrides.pop(intent, None)
            log.info(f"Model override cleared: {intent}")

    def get_model_for_intent(self, intent: str) -> str:
        """Get the current model for an intent (respects overrides)."""
        return self._overrides.get(intent, MODELS.get(intent, MODELS.get("chat")))

    # ──────────────────────────────────────────────
    # Status
    # ──────────────────────────────────────────────
    def list_loaded(self) -> list:
        """List models currently loaded in Ollama."""
        try:
            import requests
            resp = requests.get(f"{OLLAMA_URL}/api/tags", timeout=5)
            if resp.status_code == 200:
                return [m["name"] for m in resp.json().get("models", [])]
        except Exception:
            pass
        return []

    def get_status(self) -> dict:
        return {
            "current": self.current_model,
            "warm_models": list(self._warm_models),
            "overrides": dict(self._overrides),
            "configured": dict(MODELS),
        }


# Global instance
manager = ModelManager()


if __name__ == "__main__":
    print(f"Status: {manager.get_status()}")
    print(f"Loaded models: {manager.list_loaded()}")
    print(f"Model for chat: {manager.get_model_for_intent('chat')}")
    print(f"Model for code: {manager.get_model_for_intent('code')}")
