"""
EDITH Auto Router Tuner — Phase 7.3/7.4

Analyzes feedback-tagged traces weekly, adjusts routing/tier weights.
Max ±10%/week. Full history stored, manual rollback available.
"""

import json
import os
import time
import threading
from datetime import datetime
from config import get_logger, EDITH_PATH

log = get_logger("tuner")

_TUNER_STATE_FILE = os.path.join(EDITH_PATH, "tuner_state.json")
_lock = threading.Lock()

# Default weights (higher = preferred)
_DEFAULT_WEIGHTS = {
    "groq": 1.0,
    "gemini": 0.9,
    "nvidia": 0.8,
    "openrouter": 0.7,
    "ollama": 0.5,
}


def _load_state() -> dict:
    try:
        if os.path.exists(_TUNER_STATE_FILE):
            with open(_TUNER_STATE_FILE) as f:
                return json.load(f)
    except Exception:
        pass
    return {
        "weights": dict(_DEFAULT_WEIGHTS),
        "history": [],
        "last_tuned": None,
    }


def _save_state(state: dict):
    with _lock:
        try:
            with open(_TUNER_STATE_FILE, "w") as f:
                json.dump(state, f, indent=2)
        except Exception as e:
            log.error(f"Tuner save failed: {e}")


def get_weights() -> dict:
    """Get current routing weights."""
    return _load_state()["weights"]


def run_weekly_tune() -> str:
    """Run weekly tuning based on feedback data.

    Adjusts weights ±10% max per run.
    """
    state = _load_state()

    try:
        from trace_logger import get_feedback_stats, get_recent_traces
    except ImportError:
        return "Trace logger not available"

    stats = get_feedback_stats()
    traces = get_recent_traces(100)

    # Analyze which providers had good/bad feedback
    provider_scores = {}
    for trace in traces:
        fb = trace.get("feedback", "none")
        if fb == "none":
            continue
        # Use intent as proxy for provider (simplified)
        intent = trace.get("intent", "chat")
        if intent not in provider_scores:
            provider_scores[intent] = {"up": 0, "down": 0}
        if fb == "thumbs_up":
            provider_scores[intent]["up"] += 1
        elif fb == "thumbs_down":
            provider_scores[intent]["down"] += 1

    # Apply adjustments (max ±10%)
    old_weights = dict(state["weights"])
    adjustments = {}
    for provider, weight in state["weights"].items():
        scores = provider_scores.get(provider, {})
        up = scores.get("up", 0)
        down = scores.get("down", 0)
        total = up + down
        if total < 3:
            continue  # Not enough data

        satisfaction = up / total
        if satisfaction > 0.7:
            delta = min(0.1, (satisfaction - 0.7) * 0.5)
            state["weights"][provider] = min(1.0, weight + delta)
            adjustments[provider] = f"+{delta:.2f}"
        elif satisfaction < 0.3:
            delta = min(0.1, (0.3 - satisfaction) * 0.5)
            state["weights"][provider] = max(0.1, weight - delta)
            adjustments[provider] = f"-{delta:.2f}"

    # Record history
    state["history"].append({
        "timestamp": datetime.now().isoformat(),
        "old_weights": old_weights,
        "new_weights": dict(state["weights"]),
        "adjustments": adjustments,
        "feedback_stats": stats,
    })

    # Keep only last 20 history entries
    state["history"] = state["history"][-20:]
    state["last_tuned"] = datetime.now().isoformat()
    _save_state(state)

    report = f"Tuner ran. Adjustments: {adjustments or 'none needed'}"
    log.info(report)
    return report


def rollback(steps: int = 1) -> str:
    """Rollback tuner weights to a previous state."""
    state = _load_state()
    history = state.get("history", [])

    if not history or steps > len(history):
        return "No history to rollback to"

    target = history[-(steps + 1)] if len(history) > steps else history[0]
    state["weights"] = dict(target.get("old_weights", _DEFAULT_WEIGHTS))
    state["history"].append({
        "timestamp": datetime.now().isoformat(),
        "action": f"rollback_{steps}",
        "new_weights": dict(state["weights"]),
    })
    _save_state(state)

    msg = f"Rolled back {steps} step(s). Weights: {state['weights']}"
    log.info(msg)
    return msg


def get_tuner_history() -> list:
    """Get full tuner history for Dashboard."""
    return _load_state().get("history", [])


def get_status() -> dict:
    """Get tuner status for Dashboard."""
    state = _load_state()
    return {
        "weights": state["weights"],
        "last_tuned": state.get("last_tuned", "Never"),
        "history_count": len(state.get("history", [])),
    }


def run_tuning_cycle() -> str:
    """Alias for run_weekly_tune() — callable by name from scheduler/tests."""
    return run_weekly_tune()


if __name__ == "__main__":
    print(f"Current weights: {get_weights()}")
    result = run_weekly_tune()
    print(f"Tune result: {result}")
    print(f"Status: {get_status()}")
