"""
EDITH Feedback Tagger — Phase 7.2

Links 👍👎 to the trace entry's context: tier used, agents fired,
cache hit/miss, which layer. Feeds into tuner.
"""

import time
from config import get_logger
from trace_logger import set_feedback, get_trace, log_layer

log = get_logger("feedback_tagger")


def tag_feedback(trace_id: str, feedback_type: str, reason: str = ""):
    """Tag a trace with explicit feedback.

    Args:
        trace_id: the TRACE_ID from the request
        feedback_type: 'thumbs_up' or 'thumbs_down'
        reason: optional reason for the feedback
    """
    set_feedback(trace_id, feedback_type)

    # Store feedback signal for tuner (thumbs_down only — negative signals drive weight adjustment)
    if feedback_type == "thumbs_down":
        try:
            import sqlite3 as _sql, time as _time
            from config import MEMORY_ARCHIVE_PATH
            from trace_logger import get_trace
            _trace = get_trace(trace_id) or {}
            _intent = _trace.get("intent", "unknown")
            _provider = _trace.get("provider", "unknown")
            _conn = _sql.connect(MEMORY_ARCHIVE_PATH)
            _conn.execute("""
                CREATE TABLE IF NOT EXISTS feedback_signals (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    trace_id TEXT,
                    intent TEXT,
                    provider TEXT,
                    timestamp REAL,
                    was_negative INTEGER DEFAULT 1
                )
            """)
            _conn.execute(
                "INSERT INTO feedback_signals (trace_id, intent, provider, timestamp, was_negative) VALUES (?,?,?,?,1)",
                (trace_id, _intent, _provider, _time.time())
            )
            _conn.commit()
            _conn.close()
        except Exception as _e:
            log.debug(f"feedback_signals write failed (non-fatal): {_e}")

    # Log the feedback as a layer in the trace
    log_layer(
        trace_id, "feedback",
        input_summary=f"User feedback: {feedback_type}",
        output_summary=reason or "No reason given",
        confidence=1.0 if feedback_type == "thumbs_up" else 0.0,
        status="ok",
        metadata={"type": feedback_type, "reason": reason, "timestamp": time.time()}
    )

    log.info(f"Feedback tagged: {trace_id} → {feedback_type}")


def detect_implicit_feedback(trace_id: str, follow_up: str) -> str:
    """Detect implicit feedback from user follow-up behavior.

    Returns: 'correction', 'ignored', 'satisfied', or 'unknown'
    """
    lower = follow_up.lower()

    # Correction patterns
    correction_words = ["no ", "wrong", "that's not", "i meant", "actually",
                        "not what i asked", "try again", "incorrect"]
    if any(w in lower for w in correction_words):
        tag_feedback(trace_id, "thumbs_down", reason="implicit_correction")
        return "correction"

    # Satisfaction patterns
    satisfied_words = ["thanks", "perfect", "great", "exactly", "good"]
    if any(w in lower for w in satisfied_words):
        tag_feedback(trace_id, "thumbs_up", reason="implicit_satisfaction")
        return "satisfied"

    # If user just moves on to a completely different topic — neutral
    return "unknown"


def get_feedback_context(trace_id: str) -> dict:
    """Get the full context of a feedback-tagged trace for tuner analysis."""
    trace = get_trace(trace_id)
    if not trace:
        return {}

    layers = trace.get("layers", [])
    return {
        "trace_id": trace_id,
        "intent": trace.get("intent", ""),
        "feedback": trace.get("feedback", "none"),
        "device": trace.get("device", "unknown"),
        "layers_used": [l["layer"] for l in layers],
        "avg_confidence": sum(l.get("confidence", 0) for l in layers) / max(len(layers), 1),
        "had_errors": any(l.get("status") == "error" for l in layers),
    }


if __name__ == "__main__":
    from trace_logger import new_trace, complete_trace
    tid = new_trace("test query", intent="chat")
    complete_trace(tid)
    tag_feedback(tid, "thumbs_up", "Good answer")
    print(f"Context: {get_feedback_context(tid)}")
