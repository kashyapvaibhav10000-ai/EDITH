"""
EDITH Dispatch Context — shared dataclass passed to all intent handlers.

This eliminates circular imports between chat_server, orchestrator, and handlers.
Every handler receives a DispatchContext instead of raw (intent, user_input).
"""

from dataclasses import dataclass, field
from typing import Any, Optional, Callable


@dataclass
class DispatchContext:
    """Immutable-ish context object threaded through the dispatch pipeline."""
    user_input: str
    intent: str
    session_id: str = ""
    device: str = "unknown"
    source: str = "widget"        # "widget" | "telegram" | "terminal" | "voice"
    user_profile: dict = field(default_factory=dict)
    pending_action: dict = field(default_factory=dict)
    confirm_callback: Optional[Callable] = None   # HITL confirmation hook
    chat_fn: Optional[Callable] = None            # LLM chat function (breaks circular import)
    chat_stream_fn: Optional[Callable] = None     # LLM streaming function
    emotion: str = "neutral"                       # detected emotion from ml_router
    urgency: str = "LOW"                           # detected urgency: LOW / MEDIUM / HIGH
    memory_context: str = ""                       # recalled memories injected before dispatch
    metadata: dict = field(default_factory=dict)   # arbitrary extra data
