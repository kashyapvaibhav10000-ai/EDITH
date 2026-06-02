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
    """Retrieve all profile observations from SmartMemoryManager (primary) with ChromaDB fallback."""
    entries = []

    # Primary: SmartMemoryManager (where cognitive_profile.py now writes)
    try:
        from config import MEMORY_ARCHIVE_PATH, SMART_MEMORY_MAX_RAM_ITEMS, SMART_MEMORY_MAX_RAM_MB
        from smart_memory import SmartMemoryManager
        profile_mem = SmartMemoryManager(
            db_path=MEMORY_ARCHIVE_PATH,
            max_ram_items=SMART_MEMORY_MAX_RAM_ITEMS,
            max_ram_mb=SMART_MEMORY_MAX_RAM_MB,
        )
        all_memories = profile_mem.get_all(category="user_profile", limit=100)
        for i, mem in enumerate(all_memories):
            value = mem.get("value", mem) if isinstance(mem, dict) else mem
            key = mem.get("key", f"sm_{i}") if isinstance(mem, dict) else f"sm_{i}"
            entries.append({
                "id": key,
                "text": str(value),
                "timestamp": "",
                "type": "observation",
                "source": "smart_memory",
            })
    except Exception as e:
        log.warning(f"SmartMemory profile read failed: {e}")

    # Fallback: ChromaDB (legacy entries written before the migration)
    try:
        data = _get_profile_collection().get()
        if data["documents"]:
            for doc, doc_id, meta in zip(data["documents"], data["ids"], data["metadatas"]):
                entries.append({
                    "id": doc_id,
                    "text": doc,
                    "timestamp": meta.get("timestamp", ""),
                    "type": meta.get("type", "observation"),
                    "source": "chromadb",
                })
    except Exception as e:
        log.warning(f"ChromaDB profile read failed: {e}")

    return entries


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

    # Delete merged observations from both stores
    chroma_ids_to_delete = [mid for mid in merged_ids
                             if any(e["id"] == mid and e.get("source") == "chromadb"
                                    for e in observations)]
    sm_keys_to_delete = [mid for mid in merged_ids
                          if any(e["id"] == mid and e.get("source") == "smart_memory"
                                 for e in observations)]

    if chroma_ids_to_delete:
        try:
            _get_profile_collection().delete(ids=chroma_ids_to_delete)
            deleted_count += len(chroma_ids_to_delete)
            log.info(f"Deleted {len(chroma_ids_to_delete)} ChromaDB observations")
        except Exception as e:
            log.error(f"Failed to delete ChromaDB observations: {e}")

    if sm_keys_to_delete:
        try:
            from config import MEMORY_ARCHIVE_PATH, SMART_MEMORY_MAX_RAM_ITEMS, SMART_MEMORY_MAX_RAM_MB
            from smart_memory import SmartMemoryManager
            profile_mem = SmartMemoryManager(
                db_path=MEMORY_ARCHIVE_PATH,
                max_ram_items=SMART_MEMORY_MAX_RAM_ITEMS,
                max_ram_mb=SMART_MEMORY_MAX_RAM_MB,
            )
            for key in sm_keys_to_delete:
                profile_mem.delete(key)
            deleted_count += len(sm_keys_to_delete)
            log.info(f"Deleted {len(sm_keys_to_delete)} SmartMemory observations")
        except Exception as e:
            log.error(f"Failed to delete SmartMemory observations: {e}")

    # Add core truths to SmartMemoryManager (primary store)
    timestamp = datetime.datetime.now().isoformat()
    try:
        from config import MEMORY_ARCHIVE_PATH, SMART_MEMORY_MAX_RAM_ITEMS, SMART_MEMORY_MAX_RAM_MB
        from smart_memory import SmartMemoryManager
        profile_mem = SmartMemoryManager(
            db_path=MEMORY_ARCHIVE_PATH,
            max_ram_items=SMART_MEMORY_MAX_RAM_ITEMS,
            max_ram_mb=SMART_MEMORY_MAX_RAM_MB,
        )
        for i, truth in enumerate(core_truths):
            doc_id = f"core_truth_{abs(hash(truth + timestamp))}_{i}"
            profile_mem.remember(key=doc_id, value=truth, category="user_profile")
            added_count += 1
            log.info(f"Core truth stored: {truth[:60]}")
    except Exception as e:
        log.error(f"Failed to add core truths to SmartMemory: {e}")

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
