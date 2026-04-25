"""
EDITH Vision 1 — Cognitive Profile
Maintains a growing model of the user: goals, patterns, blind spots.
Detects drift between stated goals and actual behavior.
Uses SmartMemoryManager for efficient storage.
"""

import datetime
from config import MEMORY_ARCHIVE_PATH, SMART_MEMORY_MAX_RAM_ITEMS, SMART_MEMORY_MAX_RAM_MB, get_chroma_client, get_logger
from smart_router import smart_call
from smart_memory import SmartMemoryManager

log = get_logger("cognitive_profile")


def _get_profile_collection():
    return get_chroma_client().get_or_create_collection("edith_user_profile")


def _get_query_log_collection():
    return get_chroma_client().get_or_create_collection("edith_query_log")

# Smart Memory for profile observations (efficient hot/cold storage)
profile_memory = SmartMemoryManager(
    db_path=MEMORY_ARCHIVE_PATH,
    max_ram_items=SMART_MEMORY_MAX_RAM_ITEMS,
    max_ram_mb=SMART_MEMORY_MAX_RAM_MB
)

# ──────────────────────────────────────────────
# Prime Directive — the north star
# ──────────────────────────────────────────────
import json
import os
import threading
from config import EDITH_PATH

PRIME_DIRECTIVE_FILE = os.path.join(EDITH_PATH, "prime_directive.json")
DEFAULT_PRIME_DIRECTIVE = """Build a career in AI/ML and software engineering.
Ship real products (AyurStock Pro, EDITH).
Stay focused, stay learning, stay building."""

_directive_lock = threading.Lock()


def _load_prime_directive() -> str:
    # Try vault first (encrypted), fall back to JSON file, then default
    try:
        import vault
        stored = vault.get_secret("PRIME_DIRECTIVE")
        if stored:
            return stored
    except Exception:
        pass
    if os.path.exists(PRIME_DIRECTIVE_FILE):
        try:
            with open(PRIME_DIRECTIVE_FILE, 'r') as f:
                return json.load(f).get("directive", DEFAULT_PRIME_DIRECTIVE)
        except Exception as e:
            log.warning(f"Failed to load prime directive: {e}")
    return DEFAULT_PRIME_DIRECTIVE

PRIME_DIRECTIVE = _load_prime_directive()


def set_prime_directive(new_directive: str):
    """Update the prime directive. Persists to vault (encrypted) with JSON fallback."""
    global PRIME_DIRECTIVE
    with _directive_lock:
        PRIME_DIRECTIVE = new_directive
    # Persist to vault
    try:
        import vault
        if not vault.set_secret("PRIME_DIRECTIVE", new_directive):
            # Vault unavailable — fall back to JSON file
            with open(PRIME_DIRECTIVE_FILE, 'w') as f:
                json.dump({"directive": new_directive}, f)
    except Exception as e:
        log.warning(f"Failed to persist prime directive: {e}")
        try:
            with open(PRIME_DIRECTIVE_FILE, 'w') as f:
                json.dump({"directive": new_directive}, f)
        except Exception:
            pass
    update_profile(f"PRIME DIRECTIVE UPDATED: {new_directive}", "system")
    log.info(f"Prime directive updated: {new_directive}")


def get_prime_directive() -> str:
    with _directive_lock:
        return PRIME_DIRECTIVE


# ──────────────────────────────────────────────
# Profile Management
# ──────────────────────────────────────────────
def update_profile(observation: str, session_id: str):
    """Add an observation to the user's cognitive profile using SmartMemoryManager."""
    timestamp = datetime.datetime.now().isoformat()
    doc_id = f"profile_{session_id}_{abs(hash(observation + timestamp))}"

    # Store in smart memory (primary)
    profile_memory.remember(
        key=doc_id,
        value=observation,
        category="user_profile"
    )

    # Legacy ChromaDB write removed in Phase 6 hardening
    # Old data is still available via query_profile fallback

    log.info(f"Profile updated: {observation[:60]}...")


def query_profile(query: str, n: int = 5) -> list:
    """Retrieve relevant profile observations from SmartMemoryManager."""
    # Try SmartMemoryManager first (faster for recent data)
    results = profile_memory.recall(query, n=n)
    if results:
        return results

    # Fallback to ChromaDB
    try:
        chroma_results = _get_profile_collection().query(query_texts=[query], n_results=n)
        return chroma_results["documents"][0] if chroma_results["documents"] else []
    except Exception:
        return []


def get_full_profile() -> str:
    """Get all profile entries as a formatted string from SmartMemoryManager."""
    try:
        # Get from smart memory
        all_memories = profile_memory.get_all(category="user_profile", limit=20)

        if not all_memories:
            # Fallback to ChromaDB
            all_docs = _get_profile_collection().get()
            if not all_docs["documents"]:
                return "No profile data yet."
            entries = []
            for doc, meta in zip(all_docs["documents"], all_docs["metadatas"]):
                entries.append(f"[{meta.get('timestamp', '?')}] {doc}")
            return "\n".join(entries[-20:])

        # Format smart memory results
        entries = []
        for memory in all_memories:
            value = memory.get("value", memory)
            entries.append(f"[smart] {value}")

        return "\n".join(entries) if entries else "No profile data yet."
    except Exception as e:
        log.error(f"Error getting full profile: {e}")
        return "No profile data yet."


# ──────────────────────────────────────────────
# Query Logging (for drift detection)
# ──────────────────────────────────────────────
def log_query(user_input: str, session_id: str):
    """Log a user query for drift analysis in SmartMemoryManager."""
    timestamp = datetime.datetime.now().isoformat()
    doc_id = f"query_{abs(hash(user_input + timestamp))}"

    # Store in smart memory
    profile_memory.remember(
        key=doc_id,
        value=user_input,
        category="user_query_log"
    )

    # Also keep in ChromaDB for backward compatibility
    try:
        _get_query_log_collection().upsert(
            documents=[user_input],
            ids=[doc_id],
            metadatas=[{"session": session_id, "timestamp": timestamp}]
        )
    except Exception as e:
        log.warning(f"ChromaDB query log failed (using SmartMemory): {e}")


def get_recent_queries(n: int = 20) -> list:
    """Get the most recent user queries from SmartMemoryManager."""
    try:
        # Try SmartMemoryManager first
        results = profile_memory.get_all(category="user_query_log", limit=n)

        if results:
            return [r.get("value", r) if isinstance(r, dict) else r for r in results]

        # Fallback to ChromaDB
        all_docs = _get_query_log_collection().get()
        if not all_docs["documents"]:
            return []
        # Sort by timestamp and return last n
        paired = list(zip(all_docs["documents"], all_docs["metadatas"]))
        paired.sort(key=lambda x: x[1].get("timestamp", ""), reverse=True)
        return [doc for doc, _ in paired[:n]]

    except Exception:
        return []


# ──────────────────────────────────────────────
# Drift Detection
# ──────────────────────────────────────────────
def detect_drift() -> str:
    """Detect if user's recent behavior drifts from their prime directive."""
    recent = get_recent_queries(15)
    if len(recent) < 3:
        return "Not enough data for drift analysis yet."

    joined = "\n".join(f"- {q}" for q in recent)
    prompt = f"""You are EDITH, an AI that monitors the user's focus alignment.

PRIME DIRECTIVE (the user's north star goal):
{PRIME_DIRECTIVE}

RECENT USER QUERIES (last {len(recent)} interactions):
{joined}

TASK:
1. Are the queries aligned with the prime directive? (YES/NO)
2. If drifting, what is the drift pattern? (1-2 sentences)
3. Suggest one corrective action. (1 sentence)
4. Rate alignment: X/10

Be honest and direct. The user wants truth, not comfort."""

    return smart_call(prompt, intent="profile")


# ──────────────────────────────────────────────
# Session-End Profile Update Proposal
# ──────────────────────────────────────────────
def propose_profile_update(session_queries: list) -> str:
    """At end of session, propose 1 update to the user profile."""
    existing = get_full_profile()
    joined = "\n".join(f"- {q}" for q in session_queries[-10:])

    prompt = f"""You are EDITH analyzing a session to learn more about your user Vaibhav.

EXISTING PROFILE:
{existing}

THIS SESSION'S QUERIES:
{joined}

Based on this session, propose exactly ONE new observation about the user.
Format: OBSERVATION: [your insight]
Examples:
- OBSERVATION: User tends to context-switch between projects when stuck.
- OBSERVATION: User prefers concise code over verbose documentation.
- OBSERVATION: User is currently focused on security hardening.

Be specific and actionable. One observation only."""

    return smart_call(prompt, intent="profile")


# ──────────────────────────────────────────────
# Phase 7.7: Enhanced Drift Detection
# ──────────────────────────────────────────────
import json as _json
import os as _os

_DRIFT_LOG_FILE = _os.path.join(_os.path.dirname(_os.path.abspath(__file__)), "drift_log.json")


def drift_score() -> float:
    """Compute quantitative drift score (0.0 = aligned, 1.0 = fully drifted).

    Based on: % of recent queries that don't match prime directive keywords.
    """
    try:
        recent = _get_query_log_collection().get(limit=20, include=["documents"])
        docs = recent.get("documents", [])
    except Exception:
        return 0.0

    if not docs:
        return 0.0

    directive_words = set(PRIME_DIRECTIVE.lower().split())
    # Remove filler words
    directive_words -= {"the", "a", "an", "to", "is", "and", "of", "in", "for", "with", "on"}

    aligned = 0
    for doc in docs:
        doc_words = set(str(doc).lower().split())
        overlap = len(directive_words & doc_words)
        if overlap >= 2:
            aligned += 1

    alignment_ratio = aligned / max(len(docs), 1)
    drift = 1.0 - alignment_ratio
    return round(drift, 2)


def save_drift_check(drift_value: float, summary: str = ""):
    """Persist drift check result to log."""
    import datetime
    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "drift_score": drift_value,
        "summary": summary[:200],
    }
    log_data = _load_drift_log()
    log_data.append(entry)
    # Keep last 50 entries
    log_data = log_data[-50:]
    try:
        with open(_DRIFT_LOG_FILE, "w") as f:
            _json.dump(log_data, f, indent=2)
    except Exception as e:
        log.error(f"Drift log save failed: {e}")


def _load_drift_log() -> list:
    try:
        if _os.path.exists(_DRIFT_LOG_FILE):
            with open(_DRIFT_LOG_FILE) as f:
                return _json.load(f)
    except Exception:
        pass
    return []


def get_drift_trend() -> dict:
    """Get drift trend for Dashboard."""
    history = _load_drift_log()
    current = drift_score()
    return {
        "current_drift": current,
        "trend": "stable" if not history else (
            "improving" if len(history) >= 2 and history[-1].get("drift_score", 0) < history[-2].get("drift_score", 0)
            else "drifting"
        ),
        "history_count": len(history),
        "last_check": history[-1]["timestamp"] if history else "Never",
    }


def run_scheduled_drift_check() -> str:
    """Run drift check as a background scheduled task."""
    score = drift_score()
    summary = detect_drift() if score > 0.5 else f"Alignment OK (drift: {score:.0%})"
    save_drift_check(score, summary)

    if score > 0.7:
        log.warning(f"HIGH DRIFT detected: {score:.0%}")
        return f"⚠️ HIGH DRIFT: {score:.0%} — {summary[:100]}"
    elif score > 0.5:
        log.info(f"Moderate drift: {score:.0%}")
        return f"🔄 Moderate drift: {score:.0%}"
    else:
        return f"✅ Aligned (drift: {score:.0%})"


if __name__ == "__main__":
    print("[EDITH Cognitive Profile] Testing...")
    print(f"Prime Directive: {get_prime_directive()}")
    update_profile("Test observation: user is building EDITH", "test_session")
    print(f"Profile query: {query_profile('what is the user building')}")
    print(f"Drift score: {drift_score()}")
    print(f"Drift trend: {get_drift_trend()}")
    print("Done.")

