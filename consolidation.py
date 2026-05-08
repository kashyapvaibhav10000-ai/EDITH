"""
EDITH Memory Consolidation — "Dream State"

Triggered when EDITH detects idle time (no user input for 15+ minutes).
Reviews ChromaDB profile observations and merges redundant/conflicting
entries into concise "Core Truth" observations.

This mimics how human sleep consolidates short-term memory into long-term memory.
"""

import datetime
import threading
import config
from config import get_chroma_client, get_logger
from smart_router import smart_call

log = get_logger("consolidation")
_consol_lock = threading.Lock()  # Protects _last_consolidation from concurrent read/write


def _get_profile_collection():
    return get_chroma_client().get_or_create_collection("edith_user_profile")

# Track when consolidation last ran
_last_consolidation = None
CONSOLIDATION_COOLDOWN_HOURS = 12  # Don't run more than twice a day


def _needs_consolidation() -> bool:
    """Check if enough time has passed since the last consolidation."""
    # Caller must hold _consol_lock
    if _last_consolidation is None:
        return True
    elapsed = (datetime.datetime.now() - _last_consolidation).total_seconds() / 3600
    return elapsed >= CONSOLIDATION_COOLDOWN_HOURS


def _get_all_observations() -> list:
    """Retrieve all profile observations with their IDs and metadata."""
    try:
        data = _get_profile_collection().get()
        if not data["documents"]:
            return []
        entries = []
        for doc, doc_id, meta in zip(data["documents"], data["ids"], data["metadatas"]):
            entries.append({
                "id": doc_id,
                "text": doc,
                "timestamp": meta.get("timestamp", ""),
                "type": meta.get("type", "observation"),
            })
        return entries
    except Exception as e:
        log.error(f"Failed to get observations: {e}")
        return []


def run_consolidation() -> str:
    """
    Run memory consolidation.

    1. Fetch all profile observations.
    2. Ask the LLM to identify redundant/conflicting entries.
    3. Merge them into "Core Truth" observations.
    4. Delete the old entries and store the new consolidated ones.

    Returns a status string.
    """
    global _last_consolidation

    if config.IS_VOICE_ACTIVE:
        log.info("Consolidation skipped — voice session active.")
        return "Consolidation skipped (voice active)."

    with _consol_lock:
        if not _needs_consolidation():
            return "Consolidation skipped (ran recently)."

    observations = _get_all_observations()
    if len(observations) < 5:
        log.info("Too few observations for consolidation.")
        return "Not enough observations to consolidate."

    log.info(f"Starting memory consolidation ({len(observations)} observations)...")

    # Format all observations for the LLM
    obs_text = "\n".join(
        f"[{i+1}] {e['text']}" for i, e in enumerate(observations)
    )

    prompt = f"""You are EDITH's memory consolidation system.

Below are {len(observations)} observations about the user Vaibhav, collected over time.
Many may be redundant, outdated, or conflicting.

OBSERVATIONS:
{obs_text}

YOUR TASK:
1. Identify groups of observations that are about the same topic.
2. For each group, write ONE consolidated "Core Truth" that captures the latest, most accurate understanding.
3. List which observation numbers (from the [N] tags) were merged into each Core Truth.
4. Keep any unique, standalone observations as-is.

FORMAT (respond ONLY in this format):
CORE_TRUTH: [consolidated observation text]
MERGED: [comma-separated numbers that were merged]

CORE_TRUTH: [another consolidated observation]
MERGED: [comma-separated numbers]

KEEP: [comma-separated numbers of observations to keep as-is]

Rules:
- Maximum 10 Core Truths.
- Be concise but preserve important nuance.
- If observations conflict, keep the most recent one's perspective.
- Do NOT invent new information."""

    try:
        result = smart_call(prompt, intent="reason")
    except Exception as e:
        log.error(f"Consolidation LLM call failed: {e}")
        return f"Consolidation failed: {e}"

    # Parse the response
    core_truths = []
    merged_ids = set()
    keep_ids = set()

    for line in result.strip().split("\n"):
        line = line.strip()

        if line.startswith("CORE_TRUTH:"):
            truth = line[len("CORE_TRUTH:"):].strip()
            core_truths.append(truth)

        elif line.startswith("MERGED:"):
            nums_str = line[len("MERGED:"):].strip()
            for num in nums_str.replace(",", " ").split():
                try:
                    idx = int(num.strip()) - 1  # Convert to 0-indexed
                    if 0 <= idx < len(observations):
                        merged_ids.add(observations[idx]["id"])
                except ValueError:
                    continue

        elif line.startswith("KEEP:"):
            nums_str = line[len("KEEP:"):].strip()
            for num in nums_str.replace(",", " ").split():
                try:
                    idx = int(num.strip()) - 1
                    if 0 <= idx < len(observations):
                        keep_ids.add(observations[idx]["id"])
                except ValueError:
                    continue

    # Apply consolidation
    deleted_count = 0
    added_count = 0

    # Delete merged observations
    if merged_ids:
        try:
            _get_profile_collection().delete(ids=list(merged_ids))
            deleted_count = len(merged_ids)
            log.info(f"Deleted {deleted_count} merged observations")
        except Exception as e:
            log.error(f"Failed to delete merged observations: {e}")

    # Add core truths
    timestamp = datetime.datetime.now().isoformat()
    for i, truth in enumerate(core_truths):
        doc_id = f"core_truth_{abs(hash(truth + timestamp))}_{i}"
        try:
            _get_profile_collection().upsert(
                documents=[truth],
                ids=[doc_id],
                metadatas=[{
                    "timestamp": timestamp,
                    "type": "core_truth",
                    "session": "consolidation",
                }],
            )
            added_count += 1
        except Exception as e:
            log.error(f"Failed to add core truth: {e}")

    with _consol_lock:
        _last_consolidation = datetime.datetime.now()

    status = (
        f"Memory consolidation complete.\n"
        f"  📥 Processed: {len(observations)} observations\n"
        f"  🗑️  Merged/deleted: {deleted_count}\n"
        f"  ✨ Core truths created: {added_count}\n"
        f"  📌 Kept as-is: {len(keep_ids)}"
    )
    log.info(status)
    return status


if __name__ == "__main__":
    print("[EDITH Consolidation] Testing...")
    result = run_consolidation()
    print(result)
