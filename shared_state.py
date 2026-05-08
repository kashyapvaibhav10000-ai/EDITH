"""
M9: Shared state module to avoid circular imports between chat_server.py and voice.py
Centralizes _widget_history and related conversation tracking
"""

import threading
from collections import OrderedDict

# Conversation history tracking (10-turn sliding window)
_widget_history = OrderedDict()
_widget_history_lock = threading.Lock()


def add_to_history(role: str, content: str) -> None:
    """Add a message to conversation history."""
    with _widget_history_lock:
        msg_id = len(_widget_history)
        _widget_history[msg_id] = {"role": role, "content": content}
        # Keep only last 10 turns to prevent memory bloat
        if len(_widget_history) > 10:
            oldest = list(_widget_history.keys())[0]
            del _widget_history[oldest]


def get_history() -> OrderedDict:
    """Get current conversation history."""
    with _widget_history_lock:
        return OrderedDict(_widget_history)


def clear_history() -> None:
    """Clear conversation history."""
    with _widget_history_lock:
        _widget_history.clear()


def get_recent_context(max_items: int = 2) -> list:
    """Get recent messages for STT/TTS context."""
    with _widget_history_lock:
        items = list(_widget_history.values())
        return items[-max_items:] if max_items > 0 else items
