"""
EDITH Smart Router — 4-Tier Privacy-Aware AI Routing

Routes requests through: Groq → Gemini → NVIDIA → OpenRouter → Ollama (local)
Sensitive tasks are FORCED local (Ollama only). No exceptions.

Rate-limit memory: if a provider fails, skip it for 60 seconds.
"""

import os
import re as _re_top
import time
import json
import hashlib
import threading
import requests
import sqlite3
import datetime
import ollama as ollama_lib
from collections import OrderedDict, deque
from dotenv import load_dotenv
from config import get_logger, MODELS, CONTEXT_FINGERPRINT_ENABLED, MEMORY_ARCHIVE_PATH
import vault

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
log = get_logger("smart_router")

# ──────────────────────────────────────────────
# API Keys (loaded from .env)
# ──────────────────────────────────────────────

# EDITH FIX v3.0 — Lock Smart Router to EDITH Persona
EDITH_PERSONA_PREFIX = """You are EDITH — Vaibhav's personal AI, built by him for him.
You are sharp, warm, and direct. Talk like a brilliant friend, not a corporate bot.
Match his energy — casual when he's casual, deep when he's deep.
Never say Great question or Certainly. Just answer. No filler, no padding.
Be honest even when uncomfortable. Never break character."""
GROQ_KEY = vault.get_secret("GROQ_API_KEY")
GEMINI_KEY = vault.get_secret("GEMINI_API_KEY")
NVIDIA_KEY = vault.get_secret("NVIDIA_API_KEY")
OPENROUTER_KEY = vault.get_secret("OPENROUTER_API_KEY")


def _require_key(key_value: str, key_name: str) -> str:
    """Raise a clear error if a vault key is missing (called at use-time, not import-time)."""
    if not key_value:
        raise RuntimeError(f"{key_name} not found in vault. Run: python vault.py set {key_name} <value>")
    return key_value

# ──────────────────────────────────────────────
# Provider Models (free tier best picks)
# ──────────────────────────────────────────────
PROVIDER_MODELS = {
    "groq":       "llama-3.3-70b-versatile",
    "gemini":     "gemini-2.0-flash",
    "nvidia":     "meta/llama-3.1-70b-instruct",
    "openrouter": "meta-llama/llama-3.3-70b-instruct:free",
    "ollama":     MODELS.get("reason", "qwen2.5:1.5b"),
}

# ──────────────────────────────────────────────
# Privacy Classification
# ──────────────────────────────────────────────
# LOCAL_ONLY: These intents contain sensitive personal data.
#   → Forced to local Ollama. Air-gapped. Never touches the internet.
# CLOUD_OK: General knowledge tasks. Safe to send to cloud APIs.

LOCAL_ONLY_INTENTS = {
    "email", "unread_email",     # Private emails
    "create_file",               # Writing to user's filesystem
    "vault",                     # Password vault queries
    "shell",                     # System commands
    "rag",                       # User's personal notes
    "phone",                     # Phone operations
    "call",                      # Phone calls (private)
    "sms",                       # SMS messages (private)
}

# Phase 3.5: PII Tagger — force local routing if PII detected in prompt
import re as _re
_PII_PATTERNS = [
    _re.compile(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'),  # Email
    _re.compile(r'\b\d{3}[-.]?\d{3}[-.]?\d{4}\b'),    # Phone number
    _re.compile(r'\b\d{3}-\d{2}-\d{4}\b'),             # SSN
    _re.compile(r'\b\d{4}[- ]?\d{4}[- ]?\d{4}[- ]?\d{4}\b'),  # Credit card
    _re.compile(r'\b(password|passwd|secret|api.key|token)\s*[:=]\s*\S+', _re.IGNORECASE),
    _re.compile(r'\b(aadhaar|aadhar)\s*[:=]?\s*\d{4}\s*\d{4}\s*\d{4}\b', _re.IGNORECASE),  # Indian Aadhaar
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


CLOUD_OK_INTENTS = {
    "council", "decision", "briefing", "profile", "self_improve",
    "code", "reason", "lookup", "search", "chat",
    "calendar_today", "calendar_week", "calendar_create",
    "data_analysis", "agent", "vision", "session_end",
}

# ──────────────────────────────────────────────
# Task-Type Routing Chains
# ──────────────────────────────────────────────
# Each task type has a preferred provider order.
# The router tries them in sequence until one succeeds.

# T7: routing chains now config-driven — loaded at call time via get_routing_chains()
from config import get_routing_chains as _get_routing_chains

def _routing_chains() -> dict:
    return _get_routing_chains()

ROUTING_CHAINS = _routing_chains()  # module-level default; live calls use _routing_chains()

# Intent → Task Type mapping
INTENT_TASK_TYPE = {
    # System tasks
    "shell": "system", "phone": "system", "call": "system", "sms": "system",
    "create_file": "system",
    "calendar_today": "system", "calendar_week": "system", "calendar_create": "system",
    # Conversation tasks
    "chat": "conversation", "lookup": "conversation", "search": "conversation",
    "email": "conversation", "unread_email": "conversation",
    "briefing": "conversation", "profile": "conversation",
    # Coding tasks
    "code": "coding", "agent": "coding", "data_analysis": "coding",
    "rag": "coding", "vision": "coding",
    # Reasoning tasks (Council, Decisions, Self-Improvement)
    "council": "reasoning", "decision": "reasoning",
    "reason": "reasoning", "self_improve": "reasoning",
    # Session lifecycle
    "session_end": "conversation",
}

# ──────────────────────────────────────────────
# Rate Limit Memory + Exponential Backoff
# ──────────────────────────────────────────────
_router_lock = threading.Lock()  # Protects _provider_failures, _daily_calls, _response_cache

_provider_failures = {}    # {"groq": {"time": timestamp, "count": N}}

BASE_COOLDOWN = 60         # First failure: 60s cooldown
MAX_COOLDOWN = 300         # Max cooldown: 5 minutes

# Daily rate limit counters
_daily_calls = {"groq": 0, "gemini": 0, "nvidia": 0, "openrouter": 0, "ollama": 0}
DAILY_LIMITS = {"groq": 150, "gemini": 250, "nvidia": 80, "openrouter": 80, "ollama": 999999}

# Response cache (LRU, 100 entries, 1 hour TTL)
_response_cache = OrderedDict()
CACHE_MAX = 100
CACHE_TTL = 3600  # 1 hour

# Internet connectivity cache — checked at most once per 30s
_internet_ok: bool | None = None
_internet_check_time: float = 0.0
_INTERNET_CHECK_INTERVAL = 30.0

# Response latency tracking — rolling window of 20 samples per provider
_response_times: dict[str, deque] = {p: deque(maxlen=20) for p in ("groq", "gemini", "nvidia", "openrouter", "ollama")}

# Latest single latency per provider — exposed via /api/provider-latencies
_provider_latencies: dict[str, float] = {}


def _call_with_latency_track(provider_name: str, call_fn, *args, **kwargs):
    """Call a provider fn and record its latency. Slow (>3s) providers get a warning."""
    _t0 = time.time()
    try:
        result = call_fn(*args, **kwargs)
        latency = time.time() - _t0
        _provider_latencies[provider_name] = round(latency, 3)
        if latency > 3.0:
            log.warning(f"Provider {provider_name} slow: {latency:.1f}s")
        return result
    except Exception:
        _provider_latencies[provider_name] = 999.0
        raise

# Short query threshold — prefer Groq for snappy one-liners
_SHORT_QUERY_CHARS = 200


_last_call_stats: dict = {"provider": "", "tokens_in": 0, "tokens_out": 0, "cost_usd": 0.0}


def get_last_call_stats() -> dict:
    """Return stats from the most recent smart_call (provider, token estimates, cost)."""
    return dict(_last_call_stats)


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


def _has_internet() -> bool:
    global _internet_ok, _internet_check_time
    now = time.time()
    if _internet_ok is not None and (now - _internet_check_time) < _INTERNET_CHECK_INTERVAL:
        return _internet_ok
    import socket
    try:
        socket.setdefaulttimeout(2)
        socket.socket(socket.AF_INET, socket.SOCK_STREAM).connect(("8.8.8.8", 53))
        _internet_ok = True
    except Exception:
        _internet_ok = False
    _internet_check_time = now
    return _internet_ok


def _init_usage_db():
    """Initialize the API usage and api_costs tables in the archive DB."""
    try:
        import db_pool
        with db_pool.connection(MEMORY_ARCHIVE_PATH) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_usage (
                    provider TEXT PRIMARY KEY,
                    date TEXT,
                    call_count INTEGER
                )
            """)
            conn.execute("""
                CREATE TABLE IF NOT EXISTS api_costs (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    timestamp REAL NOT NULL,
                    provider TEXT NOT NULL,
                    model TEXT,
                    input_tokens_est INTEGER,
                    output_tokens_est INTEGER,
                    cost_usd_est REAL DEFAULT 0.0
                )
            """)
            conn.commit()
    except Exception as e:
        log.error(f"Failed to init usage DB: {e}")

_init_usage_db()


def _log_api_cost(provider: str, model: str, prompt: str, response: str):
    """J4 — log per-call token estimates to api_costs table."""
    try:
        input_est = int(len(prompt.split()) * 1.3)
        output_est = int(len(response.split()) * 1.3)
        import db_pool
        with db_pool.connection(MEMORY_ARCHIVE_PATH) as conn:
            conn.execute(
                "INSERT INTO api_costs (timestamp, provider, model, input_tokens_est, output_tokens_est, cost_usd_est) VALUES (?,?,?,?,?,?)",
                (time.time(), provider, model, input_est, output_est, 0.0)
            )
            conn.commit()
    except Exception as e:
        log.debug(f"api_cost log failed: {e}")

def _reset_daily_if_needed():
    """Reset daily call counters in DB if the day has changed."""
    global _daily_calls
    today = datetime.date.today().isoformat()
    try:
        import db_pool
        with db_pool.connection(MEMORY_ARCHIVE_PATH) as conn:
            row = conn.execute("SELECT date FROM api_usage LIMIT 1").fetchone()

            if not row or row[0] != today:
                log.info(f"New day ({today}) — resetting API usage in DB")
                for provider in DAILY_LIMITS:
                    conn.execute("""
                        INSERT OR REPLACE INTO api_usage (provider, date, call_count)
                        VALUES (?, ?, ?)
                    """, (provider, today, 0))
                    _daily_calls[provider] = 0
                conn.commit()
            else:
                rows = conn.execute("SELECT provider, call_count FROM api_usage").fetchall()
                for provider, count in rows:
                    _daily_calls[provider] = count
    except Exception as e:
        log.error(f"Failed to reset/sync usage DB: {e}")


def _get_fastest_provider(candidates: list[str]) -> str | None:
    """Return candidate with lowest avg latency (min 3 samples). None if no data."""
    best, best_avg = None, float("inf")
    for p in candidates:
        samples = _response_times.get(p)
        if samples and len(samples) >= 3:
            avg = sum(samples) / len(samples)
            if avg < best_avg:
                best, best_avg = p, avg
    return best


# L2: Provider latency leaderboard for auto-routing optimization
def get_provider_latency_stats() -> dict:
    """Return latency stats for all providers (min, avg, max, samples)."""
    stats = {}
    for provider, samples in _response_times.items():
        if samples:
            samples_list = list(samples)
            stats[provider] = {
                "samples": len(samples_list),
                "min": min(samples_list),
                "avg": sum(samples_list) / len(samples_list),
                "max": max(samples_list),
            }
    return stats


def get_provider_leaderboard() -> list[tuple]:
    """Return providers ranked by average latency (fastest first)."""
    stats = get_provider_latency_stats()
    if not stats:
        return []
    # Filter to providers with at least 3 samples
    candidates = [(p, data["avg"]) for p, data in stats.items() if data["samples"] >= 3]
    return sorted(candidates, key=lambda x: x[1])


def _log_latency_leaderboard():
    """Log provider latency leaderboard periodically for auto-routing tuning."""
    leaderboard = get_provider_leaderboard()
    if leaderboard:
        leaders = " > ".join([f"{p}({t:.2f}s)" for p, t in leaderboard])
        log.info(f"Latency Leaderboard: {leaders}")


def _get_tuner_weights() -> dict:
    """Load tuner-adjusted provider weights (soft preference, cached 5 min)."""
    try:
        from tuner import get_weights
        return get_weights()
    except Exception:
        return {}


def _apply_tuner_weights(chain: list[str]) -> list[str]:
    """Re-sort chain by tuner weights as a soft preference.

    Only reorders within the chain — never adds or removes providers.
    Ollama stays last (privacy fallback).
    """
    weights = _get_tuner_weights()
    if not weights:
        return chain
    non_ollama = [p for p in chain if p != "ollama"]
    non_ollama.sort(key=lambda p: weights.get(p, 0.5), reverse=True)
    result = non_ollama + (["ollama"] if "ollama" in chain else [])
    return result


def _is_provider_cooled_down(provider: str) -> bool:
    """Check if a provider has recovered from its last failure (exponential backoff)."""
    with _router_lock:
        if provider not in _provider_failures:
            return True
        info = _provider_failures[provider]
        cooldown = min(BASE_COOLDOWN * (2 ** (info["count"] - 1)), MAX_COOLDOWN)
        elapsed = time.time() - info["time"]
        if elapsed >= cooldown:
            del _provider_failures[provider]
            return True
        return False


def _mark_provider_failed(provider: str):
    """Mark a provider as temporarily failed with exponential backoff."""
    with _router_lock:
        if provider in _provider_failures:
            _provider_failures[provider]["count"] += 1
            _provider_failures[provider]["time"] = time.time()
        else:
            _provider_failures[provider] = {"time": time.time(), "count": 1}
        cooldown = min(BASE_COOLDOWN * (2 ** (_provider_failures[provider]["count"] - 1)), MAX_COOLDOWN)
        log.warning(f"Provider {provider} marked failed (cooldown {cooldown}s, attempt #{_provider_failures[provider]['count']})")


def _is_under_daily_limit(provider: str) -> bool:
    """Check if provider hasn't exceeded daily call limit."""
    with _router_lock:
        _reset_daily_if_needed()
        return _daily_calls.get(provider, 0) < DAILY_LIMITS.get(provider, 100)


def _track_call(provider: str):
    """Track a successful API call for rate limiting by updating DB."""
    with _router_lock:
        _reset_daily_if_needed()
        _daily_calls[provider] = _daily_calls.get(provider, 0) + 1

    today = datetime.date.today().isoformat()
    try:
        import db_pool
        with db_pool.connection(MEMORY_ARCHIVE_PATH) as conn:
            conn.execute("""
                UPDATE api_usage SET call_count = ? WHERE provider = ? AND date = ?
            """, (_daily_calls[provider], provider, today))
            conn.commit()
    except Exception as e:
        log.error(f"Failed to update usage DB: {e}")



def _context_fingerprint(prompt: str, intent: str) -> str:
    """Generate a context-aware cache key.

    Phase 2.5: Instead of simple md5(prompt::intent), includes:
      - Time bucket (hourly) so answers update with time
      - Top entity (first capitalized word or number)
      - Intent for routing context
    Falls back to simple hash if CONTEXT_FINGERPRINT_ENABLED is False.
    """
    if not CONTEXT_FINGERPRINT_ENABLED:
        return hashlib.md5(f"{prompt}::{intent}".encode()).hexdigest()

    # Time bucket: roll key every hour
    time_bucket = int(time.time() / 3600)

    # Top entity: extract first meaningful entity from prompt
    words = prompt.split()
    top_entity = ""
    for w in words[:20]:  # Only scan first 20 words
        clean = _re_top.sub(r'[^\w]', '', w)
        if clean and (clean[0].isupper() or clean.isdigit()) and len(clean) > 1:
            top_entity = clean.lower()
            break

    fingerprint = f"{prompt}::{intent}::{time_bucket}::{top_entity}"
    return hashlib.md5(fingerprint.encode()).hexdigest()


def _cache_get(prompt: str, intent: str):
    """Check response cache. Returns cached response or None."""
    cache_key = _context_fingerprint(prompt, intent)
    with _router_lock:
        if cache_key in _response_cache:
            resp, ts = _response_cache[cache_key]
            if time.time() - ts < CACHE_TTL:
                _response_cache.move_to_end(cache_key)  # refresh LRU position
                return resp
            else:
                del _response_cache[cache_key]
    return None


def _cache_set(prompt: str, intent: str, response: str):
    """Store response in cache."""
    cache_key = _context_fingerprint(prompt, intent)
    with _router_lock:
        _response_cache[cache_key] = (response, time.time())
        if len(_response_cache) > CACHE_MAX:
            _response_cache.popitem(last=False)  # evict oldest


def _has_key(provider: str) -> bool:
    """Check if the API key exists for a provider."""
    keys = {"groq": GROQ_KEY, "gemini": GEMINI_KEY,
            "nvidia": NVIDIA_KEY, "openrouter": OPENROUTER_KEY}
    if provider == "ollama":
        return True
    return bool(keys.get(provider, ""))


# ──────────────────────────────────────────────
# Provider API Calls
# ──────────────────────────────────────────────

def _call_groq(prompt: str, system: str = "") -> str:
    """Call Groq API (OpenAI-compatible)."""
    # EDITH FIX v3.0 — Persona Injection
    final_system = f"{EDITH_PERSONA_PREFIX}\n\n{system}" if system else EDITH_PERSONA_PREFIX
    messages = []
    messages.append({"role": "system", "content": final_system})
    messages.append({"role": "user", "content": prompt})

    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
        json={"model": PROVIDER_MODELS["groq"], "messages": messages, "temperature": 0.7, "max_tokens": 2048},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_gemini(prompt: str, system: str = "") -> str:
    """Call Gemini API (Google AI Studio) with Google Search Grounding for real-time access."""
    # EDITH FIX v3.0 — Persona Injection (Gemini exact format)
    final_system = f"{EDITH_PERSONA_PREFIX}\n\n{system}" if system else EDITH_PERSONA_PREFIX
    
    resp = requests.post(
        f"https://generativelanguage.googleapis.com/v1beta/models/{PROVIDER_MODELS['gemini']}:generateContent",
        headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY},
        json={
            "system_instruction": {"parts": [{"text": final_system}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {"temperature": 0.7, "maxOutputTokens": 2048}
        },
        timeout=10,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["candidates"][0]["content"]["parts"][0]["text"]


def _call_nvidia(prompt: str, system: str = "") -> str:
    """Call NVIDIA NIM API (OpenAI-compatible)."""
    # EDITH FIX v3.0 — Persona Injection
    final_system = f"{EDITH_PERSONA_PREFIX}\n\n{system}" if system else EDITH_PERSONA_PREFIX
    messages = []
    messages.append({"role": "system", "content": final_system})
    messages.append({"role": "user", "content": prompt})

    resp = requests.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"},
        json={"model": PROVIDER_MODELS["nvidia"], "messages": messages, "temperature": 0.7, "max_tokens": 2048},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_openrouter(prompt: str, system: str = "") -> str:
    """Call OpenRouter API (OpenAI-compatible, 29+ model fallback)."""
    # EDITH FIX v3.0 — Persona Injection
    final_system = f"{EDITH_PERSONA_PREFIX}\n\n{system}" if system else EDITH_PERSONA_PREFIX
    messages = []
    messages.append({"role": "system", "content": final_system})
    messages.append({"role": "user", "content": prompt})

    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
        json={"model": PROVIDER_MODELS["openrouter"], "messages": messages, "temperature": 0.7, "max_tokens": 2048},
        timeout=10,
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"]


def _call_ollama(prompt: str, system: str = "") -> str:
    """Call local Ollama (air-gapped, never leaves the machine)."""
    # EDITH FIX v3.0 — Persona Injection
    final_system = f"{EDITH_PERSONA_PREFIX}\n\n{system}" if system else EDITH_PERSONA_PREFIX
    messages = []
    messages.append({"role": "system", "content": final_system})
    messages.append({"role": "user", "content": prompt})
    response = ollama_lib.chat(model=PROVIDER_MODELS["ollama"], messages=messages)
    return response["message"]["content"]


# Provider function map
_PROVIDER_CALLS = {
    "groq": _call_groq,
    "gemini": _call_gemini,
    "nvidia": _call_nvidia,
    "openrouter": _call_openrouter,
    "ollama": _call_ollama,
}

def _call_groq_stream(prompt: str, system: str = ""):
    """Stream from Groq API."""
    final_system = f"{EDITH_PERSONA_PREFIX}\n\n{system}" if system else EDITH_PERSONA_PREFIX
    messages = [{"role": "system", "content": final_system}, {"role": "user", "content": prompt}]
    
    resp = requests.post(
        "https://api.groq.com/openai/v1/chat/completions",
        headers={"Authorization": f"Bearer {GROQ_KEY}", "Content-Type": "application/json"},
        json={"model": PROVIDER_MODELS["groq"], "messages": messages, "temperature": 0.7, "stream": True},
        stream=True, timeout=30
    )
    resp.raise_for_status()
    for line in resp.iter_lines():
        if line:
            line = line.decode('utf-8')
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str == "[DONE]": break
                try:
                    chunk = json.loads(data_str)
                    token = chunk["choices"][0]["delta"].get("content", "")
                    if token: yield token
                except (ValueError, KeyError): continue

def _call_gemini_stream(prompt: str, system: str = ""):
    """Stream from Gemini API."""
    final_system = f"{EDITH_PERSONA_PREFIX}\n\n{system}" if system else EDITH_PERSONA_PREFIX
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{PROVIDER_MODELS['gemini']}:streamGenerateContent?alt=sse"
    
    resp = requests.post(
        url, headers={"Content-Type": "application/json", "x-goog-api-key": GEMINI_KEY},
        json={
            "system_instruction": {"parts": [{"text": final_system}]},
            "contents": [{"parts": [{"text": prompt}]}],
            "tools": [{"googleSearch": {}}],
            "generationConfig": {"temperature": 0.7}
        },
        stream=True, timeout=30
    )
    resp.raise_for_status()
    for line in resp.iter_lines():
        if line:
            line = line.decode('utf-8')
            if line.startswith("data: "):
                try:
                    data = json.loads(line[6:])
                    token = data["candidates"][0]["content"]["parts"][0]["text"]
                    if token: yield token
                except (ValueError, KeyError): continue

def _call_nvidia_stream(prompt: str, system: str = ""):
    """Stream from NVIDIA NIM API (OpenAI-compatible SSE)."""
    final_system = f"{EDITH_PERSONA_PREFIX}\n\n{system}" if system else EDITH_PERSONA_PREFIX
    messages = [{"role": "system", "content": final_system}, {"role": "user", "content": prompt}]
    resp = requests.post(
        "https://integrate.api.nvidia.com/v1/chat/completions",
        headers={"Authorization": f"Bearer {NVIDIA_KEY}", "Content-Type": "application/json"},
        json={"model": PROVIDER_MODELS["nvidia"], "messages": messages, "temperature": 0.7, "stream": True},
        stream=True, timeout=30,
    )
    resp.raise_for_status()
    for line in resp.iter_lines():
        if line:
            line = line.decode("utf-8")
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    token = chunk["choices"][0]["delta"].get("content", "")
                    if token:
                        yield token
                except (ValueError, KeyError):
                    continue


def _call_openrouter_stream(prompt: str, system: str = ""):
    """Stream from OpenRouter API (OpenAI-compatible SSE)."""
    final_system = f"{EDITH_PERSONA_PREFIX}\n\n{system}" if system else EDITH_PERSONA_PREFIX
    messages = [{"role": "system", "content": final_system}, {"role": "user", "content": prompt}]
    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
        json={"model": PROVIDER_MODELS["openrouter"], "messages": messages, "temperature": 0.7, "stream": True},
        stream=True, timeout=30,
    )
    resp.raise_for_status()
    for line in resp.iter_lines():
        if line:
            line = line.decode("utf-8")
            if line.startswith("data: "):
                data_str = line[6:]
                if data_str == "[DONE]":
                    break
                try:
                    chunk = json.loads(data_str)
                    token = chunk["choices"][0]["delta"].get("content", "")
                    if token:
                        yield token
                except (ValueError, KeyError):
                    continue


def _call_ollama_stream(prompt: str, system: str = ""):
    """Stream from local Ollama."""
    final_system = f"{EDITH_PERSONA_PREFIX}\n\n{system}" if system else EDITH_PERSONA_PREFIX
    messages = [{"role": "system", "content": final_system}, {"role": "user", "content": prompt}]
    for chunk in ollama_lib.chat(model=PROVIDER_MODELS["ollama"], messages=messages, stream=True):
        token = chunk["message"]["content"]
        if token: yield token

_PROVIDER_STREAM_CALLS = {
    "groq": _call_groq_stream,
    "gemini": _call_gemini_stream,
    "nvidia": _call_nvidia_stream,
    "openrouter": _call_openrouter_stream,
    "ollama": _call_ollama_stream,
}


# ──────────────────────────────────────────────
# The Smart Router — Main Entry Point
# ──────────────────────────────────────────────

def smart_call(prompt: str, intent: str = "chat", system: str = "") -> str:
    """
    The main EDITH routing function. Replaces safe_ollama_call everywhere.

    Args:
        prompt: The user prompt / question.
        intent: The detected intent (e.g. "council", "email", "code").
        system: Optional system prompt.

    Returns:
        The AI-generated response string.

    Routing logic:
        1. If intent is in LOCAL_ONLY_INTENTS → force Ollama (air-gapped).
        2. Otherwise, determine task type → follow the provider chain.
        3. Skip providers that are on cooldown or missing API keys.
        4. Ollama is always the final fallback.
    """

    # ── Check cache first ──
    cached = _cache_get(prompt, intent)
    if cached:
        log.info(f"📦 Cache hit for [{intent}]")
        return cached

    # ── CoT injection: applied after cache check so cache keys stay stable ──
    _COT = "Think step by step. Be precise and direct. Show reasoning before giving final answer."
    system = f"{system}\n\n{_COT}" if system else _COT

    # ── Privacy Gate ──
    pii = detect_pii(prompt)
    force_local = intent in LOCAL_ONLY_INTENTS or pii["has_pii"]
    if force_local:
        if pii["has_pii"]:
            log.debug("PII detected — forcing local route")
        else:
            log.info(f"🔒 PRIVATE [{intent}] → forced local Ollama")
        try:
            result = _call_ollama(prompt, system)
            _track_call("ollama")
            _cache_set(prompt, intent, result)
            return result
        except Exception as e:
            log.error(f"Local Ollama failed: {e}")
            return f"[EDITH] Ollama is offline and this is a private task. Cannot use cloud APIs. Error: {e}"

    # ── Determine routing chain ──
    task_type = INTENT_TASK_TYPE.get(intent, "conversation")
    _live_chains = _routing_chains()
    chain = list(_live_chains.get(task_type, _live_chains["conversation"]))

    # ── Complexity routing: reorder chain based on query complexity ──
    complexity = _score_complexity(prompt)
    if complexity == "low" and "ollama" in chain:
        chain = ["ollama"] + [p for p in chain if p != "ollama"]
        log.debug(f"Low-complexity query → Ollama-first chain")
    elif complexity == "high" and "ollama" in chain:
        chain = [p for p in chain if p != "ollama"] + ["ollama"]
        log.debug(f"High-complexity query → cloud-first chain (Ollama last)")

    # ── Short query bias: put Groq first (fastest for short completions) ──
    if complexity != "low" and len(prompt) <= _SHORT_QUERY_CHARS and "groq" in chain and chain[0] != "groq":
        chain = ["groq"] + [p for p in chain if p != "groq"]
        log.debug(f"Short query ({len(prompt)}c) → Groq-first chain")

    # ── Auto-tune: if we have latency data, prefer fastest available provider ──
    fastest = _get_fastest_provider([p for p in chain if p != "ollama"])
    if fastest and fastest != chain[0]:
        chain = [fastest] + [p for p in chain if p != fastest]
        log.debug(f"Auto-tune: promoting {fastest} (lowest avg latency)")
    
    # L2: Log latency leaderboard periodically for visibility
    _log_latency_leaderboard()

    # J2: FORCE_DEEP_THINK → prefer Gemini (high context) and add reasoning suffix to prompt
    try:
        import config as _cfg
        if _cfg.FORCE_DEEP_THINK and "gemini" in chain and chain[0] != "gemini":
            chain = ["gemini"] + [p for p in chain if p != "gemini"]
            log.debug("FORCE_DEEP_THINK: promoting gemini to front of chain")
    except Exception:
        pass

    # ── Tuner weights: soft preference from feedback history ──
    chain = _apply_tuner_weights(chain)
    log.debug(f"Tuner-adjusted chain: {chain}")

    # Skip cloud providers when offline — go straight to Ollama
    if not _has_internet():
        log.warning("🔌 No internet — routing directly to Ollama")
        try:
            result = _call_ollama(prompt, system)
            _track_call("ollama")
            _cache_set(prompt, intent, result)
            return result
        except Exception as e:
            log.error(f"Ollama failed offline: {e}")
            return f"[EDITH] Offline and Ollama failed: {e}"

    log.info(f"🌐 CLOUD-OK [{intent}] → task_type={task_type} → chain={chain}")

    # ── Try each provider in the chain ──
    errors = []
    for provider in chain:
        # Skip if no API key
        if not _has_key(provider):
            continue
        # Skip if on cooldown
        if not _is_provider_cooled_down(provider):
            log.info(f"  ⏳ {provider} on cooldown, skipping")
            continue
        # Skip if daily limit exceeded
        if not _is_under_daily_limit(provider):
            log.info(f"  🚫 {provider} daily limit ({DAILY_LIMITS.get(provider)}) reached, skipping")
            continue

        try:
            log.info(f"  🔄 Trying {provider}...")
            _t0 = time.time()
            result = _call_with_latency_track(provider, _PROVIDER_CALLS[provider], prompt, system)
            _elapsed = time.time() - _t0
            _response_times[provider].append(_elapsed)
            log.info(f"  ✅ {provider} responded ({len(result)} chars, {_elapsed:.2f}s)")
            _track_call(provider)
            _cache_set(prompt, intent, result)
            _log_api_cost(provider, PROVIDER_MODELS.get(provider, "unknown"), prompt, result)
            _last_call_stats["provider"] = provider
            _last_call_stats["tokens_in"] = len(prompt) // 4
            _last_call_stats["tokens_out"] = len(result) // 4
            _last_call_stats["cost_usd"] = 0.0  # Groq/Gemini/NVIDIA free tier
            return result
        except Exception as e:
            error_msg = str(e)[:100]
            log.warning(f"  ❌ {provider} failed: {error_msg}")
            errors.append(f"{provider}: {error_msg}")
            if provider != "ollama":
                _mark_provider_failed(provider)

    # ── All providers failed ──
    log.error(f"All providers exhausted for [{intent}]")
    return f"[EDITH] All AI providers failed. Errors: {'; '.join(errors)}"


def smart_call_stream(prompt: str, intent: str = "chat", system: str = ""):
    """Streaming variant of smart_call. Yields tokens in real-time.

    Routing logic mirrors smart_call exactly: PII gate, complexity scoring,
    short-query Groq bias, auto-tune, tuner weights, FORCE_DEEP_THINK, internet check.
    """
    # ── CoT injection: mirrored from smart_call() ──
    _COT = "Think step by step. Be precise and direct. Show reasoning before giving final answer."
    system = f"{system}\n\n{_COT}" if system else _COT

    # ── Privacy Gate (PII + intent) ──
    pii = detect_pii(prompt)
    force_local = intent in LOCAL_ONLY_INTENTS or pii["has_pii"]
    if force_local:
        if pii["has_pii"]:
            log.debug("PII detected in stream — forcing local route")
        else:
            log.info(f"🔒 PRIVATE [{intent}] stream → forced local Ollama")
        try:
            for token in _call_ollama_stream(prompt, system):
                yield token
            _track_call("ollama")
        except Exception as e:
            yield f"[EDITH] Ollama is offline (Private Task). Error: {e}"
        return

    # ── Determine routing chain ──
    task_type = INTENT_TASK_TYPE.get(intent, "conversation")
    _live_chains = _routing_chains()
    chain = list(_live_chains.get(task_type, _live_chains["conversation"]))

    # ── Complexity routing ──
    complexity = _score_complexity(prompt)
    if complexity == "low" and "ollama" in chain:
        chain = ["ollama"] + [p for p in chain if p != "ollama"]
    elif complexity == "high" and "ollama" in chain:
        chain = [p for p in chain if p != "ollama"] + ["ollama"]

    # ── Short query bias: Groq first ──
    if complexity != "low" and len(prompt) <= _SHORT_QUERY_CHARS and "groq" in chain and chain[0] != "groq":
        chain = ["groq"] + [p for p in chain if p != "groq"]

    # ── Auto-tune: fastest provider first ──
    fastest = _get_fastest_provider([p for p in chain if p != "ollama"])
    if fastest and fastest != chain[0]:
        chain = [fastest] + [p for p in chain if p != fastest]

    # ── FORCE_DEEP_THINK: promote Gemini ──
    try:
        import config as _cfg
        if _cfg.FORCE_DEEP_THINK and "gemini" in chain and chain[0] != "gemini":
            chain = ["gemini"] + [p for p in chain if p != "gemini"]
    except Exception:
        pass

    # ── Tuner weights ──
    chain = _apply_tuner_weights(chain)

    # ── Skip cloud when offline ──
    if not _has_internet():
        log.warning("🔌 No internet — streaming directly via Ollama")
        try:
            for token in _call_ollama_stream(prompt, system):
                yield token
            _track_call("ollama")
        except Exception as e:
            yield f"[EDITH] Offline and Ollama failed: {e}"
        return

    log.info(f"🌐 CLOUD-OK [{intent}] stream → chain={chain}")

    for provider in chain:
        if not _has_key(provider):
            continue
        if not _is_provider_cooled_down(provider):
            log.info(f"  ⏳ {provider} on cooldown, skipping")
            continue
        if not _is_under_daily_limit(provider):
            log.info(f"  🚫 {provider} daily limit reached, skipping")
            continue
        if provider not in _PROVIDER_STREAM_CALLS:
            continue

        try:
            log.info(f"  🔄 Streaming {provider}...")
            full_response = ""
            for token in _PROVIDER_STREAM_CALLS[provider](prompt, system):
                full_response += token
                yield token
            _track_call(provider)
            _cache_set(prompt, intent, full_response)
            return
        except Exception as e:
            log.warning(f"  ❌ {provider} stream failed: {e}")
            if provider != "ollama":
                _mark_provider_failed(provider)

    yield "[EDITH] All streaming providers failed. Try a non-stream request."


# ──────────────────────────────────────────────
# Convenience wrappers
# ──────────────────────────────────────────────

def smart_chat(prompt: str, intent: str = "chat") -> str:
    """For general chat — no system prompt needed."""
    return smart_call(prompt, intent=intent)


def smart_reason(prompt: str, intent: str = "reason") -> str:
    """For deep reasoning tasks (Council, Decisions, etc.)."""
    return smart_call(prompt, intent=intent,
                      system="You are EDITH, a deeply analytical AI assistant. Think step by step. Be precise and direct.")


def smart_code(prompt: str) -> str:
    """For coding tasks."""
    return smart_call(prompt, intent="code",
                      system="You are EDITH, an expert software engineer. Write clean, production-quality code.")


# ──────────────────────────────────────────────
# Status & Diagnostics
# ──────────────────────────────────────────────

def router_status() -> str:
    """Show which providers are available and their status."""
    lines = ["EDITH Smart Router Status:", "─" * 40]
    providers = [
        ("Groq",       "groq",       GROQ_KEY),
        ("Gemini",     "gemini",     GEMINI_KEY),
        ("NVIDIA",     "nvidia",     NVIDIA_KEY),
        ("OpenRouter", "openrouter", OPENROUTER_KEY),
        ("Ollama",     "ollama",     "local"),
    ]
    for name, key, api_key in providers:
        has_key = "✅ Key set" if api_key else "❌ No key"
        cooldown = ""
        daily = ""
        if not _is_provider_cooled_down(key):
            info = _provider_failures.get(key, {})
            cd = min(BASE_COOLDOWN * (2 ** (info.get("count", 1) - 1)), MAX_COOLDOWN)
            remaining = int(cd - (time.time() - info.get("time", 0)))
            cooldown = f" (⏳ cooldown {remaining}s)"
        if key in _daily_calls and _daily_calls[key] > 0:
            daily = f" [{_daily_calls[key]}/{DAILY_LIMITS.get(key, '?')} today]"
        lines.append(f"  {name:<12} {has_key}{cooldown}{daily}")
    lines.append("─" * 40)

    # Show routing chains
    lines.append("\nRouting Chains:")
    for task_type, chain in _routing_chains().items():
        active = [p for p in chain if _has_key(p)]
        lines.append(f"  {task_type:<14} → {' → '.join(active)}")

    lines.append(f"\n🔒 Local-only intents: {', '.join(sorted(LOCAL_ONLY_INTENTS))}")
    lines.append(f"📦 Cache: {len(_response_cache)}/{CACHE_MAX} entries")
    return "\n".join(lines)


if __name__ == "__main__":
    print(router_status())
    print()
    # Quick test
    if any([GROQ_KEY, GEMINI_KEY, NVIDIA_KEY, OPENROUTER_KEY]):
        print("Testing smart_call with 'chat' intent...")
        result = smart_call("Say hello in one sentence.", intent="chat")
        print(f"Response: {result}")
    else:
        print("No API keys configured. Add them to .env and try again.")
