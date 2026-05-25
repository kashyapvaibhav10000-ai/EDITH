"""
Provider Configuration & API Key Management for the Smart Router.

Handles:
- API key validation from the vault.
- Provider model mappings.
- PII (Personally Identifiable Information) detection for privacy-aware routing.
- Routing chain configuration.
- Query complexity scoring.
"""

import os
import re
from config import get_logger, MODELS, get_routing_chains
import vault

log = get_logger("provider_config")

# ──────────────────────────────────────────────
# API Keys (loaded from vault)
# ──────────────────────────────────────────────

GROQ_KEY = vault.get_secret("GROQ_API_KEY")
GEMINI_KEY = vault.get_secret("GEMINI_API_KEY")
NVIDIA_KEY = vault.get_secret("NVIDIA_API_KEY")
OPENROUTER_KEY = vault.get_secret("OPENROUTER_API_KEY")


def _require_key(key_value: str, key_name: str) -> str:
    """Raise a clear error if a vault key is missing."""
    if not key_value:
        raise RuntimeError(f"{key_name} not found in vault. Run: python vault.py set {key_name} <value>")
    return key_value

# ──────────────────────────────────────────────
# Provider Models
# ──────────────────────────────────────────────

PROVIDER_MODELS = {
    "groq":       "llama-3.3-70b-versatile",
    "gemini":     "gemini-2.0-flash",
    "nvidia":     "meta/llama-3.1-70b-instruct",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
    "ollama":     MODELS.get("reason", "qwen2.5:1.5b"),
}

# ──────────────────────────────────────────────
# Privacy Classification & Intent Routing
# ──────────────────────────────────────────────

LOCAL_ONLY_INTENTS = {
    "email", "unread_email",
    "create_file",
    "vault",
    "shell",
    "rag",
    "phone",
    "call",
    "sms",
}

_IS_CLOUD_NODE = os.getenv("EDITH_NODE_TYPE", "").lower() == "cloud"

# ──────────────────────────────────────────────
# PII Detection
# ──────────────────────────────────────────────

_PII_PATTERNS = [
    re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),  # Email
    re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'),    # Phone number
    re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),             # SSN
    re.compile(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b'),  # Credit card
    re.compile(r'\b(password|passwd|secret|api.key|token)\s*[:=]\s*\S+', re.IGNORECASE),
    re.compile(r'\b(aadhaar|aadhar)\s*[:=]?\s*\d{4}\s*\d{4}\s*\d{4}\b', re.IGNORECASE),  # Indian Aadhaar
]


def detect_pii(text: str) -> dict:
    """Scan text for PII patterns.

    Returns: {'has_pii': bool, 'types': list[str]}
    """
    types = []
    labels = ["email", "phone", "ssn", "credit_card", "credential", "aadhaar"]
    for pattern, label in zip(_PII_PATTERNS, labels):
        if pattern.search(text):
            types.append(label)
    return {"has_pii": len(types) > 0, "types": types}


def _score_complexity(query: str) -> str:
    """Returns 'low', 'medium', or 'high' complexity for routing decisions."""
    q = query.lower().strip()
    word_count = len(q.split())
    low_signals = ["what time", "weather", "reminder", "timer", "hello",
                   "thanks", "ok", "yes", "no", "stop", "play", "pause"]
    if any(s in q for s in low_signals) or word_count < 8:
        return "low"
    high_signals = ["explain", "analyze", "compare", "debug", "review",
                    "architecture", "plan", "research", "summarize", "write"]
    if any(s in q for s in high_signals) or word_count > 40:
        return "high"
    return "medium"


def _has_key(provider: str) -> bool:
    """Check if the API key exists for a provider."""
    keys = {"groq": GROQ_KEY, "gemini": GEMINI_KEY,
            "nvidia": NVIDIA_KEY, "openrouter": OPENROUTER_KEY}
    if provider == "ollama":
        return True
    return bool(keys.get(provider, ""))


def _routing_chains() -> dict:
    """Get task-type routing chains from config."""
    return get_routing_chains()

