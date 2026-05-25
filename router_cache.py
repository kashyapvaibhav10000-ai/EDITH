"""
Smart Router Caching Layer

Implements semantic caching for LLM responses using context fingerprinting.
"""

import time
import hashlib
from collections import OrderedDict
from config import get_logger, CONTEXT_FINGERPRINT_ENABLED
import re as _re_top

log = get_logger("router_cache")

# ──────────────────────────────────────────────
# Response Cache (LRU, in-memory)
# ──────────────────────────────────────────────

_response_cache = OrderedDict()
CACHE_MAX = 100
CACHE_TTL = 3600  # 1 hour


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
    _response_cache[cache_key] = (response, time.time())
    if len(_response_cache) > CACHE_MAX:
        _response_cache.popitem(last=False)  # evict oldest


import time
import hashlib
from collections import OrderedDict
from config import get_logger, CONTEXT_FINGERPRINT_ENABLED
import re as _re_top

log = get_logger("router_cache")

# ──────────────────────────────────────────────
# Response Cache (LRU, in-memory)
# ──────────────────────────────────────────────

_response_cache = OrderedDict()
CACHE_MAX = 100
CACHE_TTL = 3600  # 1 hour


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
    _response_cache[cache_key] = (response, time.time())
    if len(_response_cache) > CACHE_MAX:
        _response_cache.popitem(last=False)  # evict oldest

