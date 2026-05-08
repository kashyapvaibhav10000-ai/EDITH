"""
EDITH Episodic Memory — Session Timelines

Stores entire session conversations as "episodes" so EDITH can recall
not just isolated facts, but the full context of past interactions.

Example: "What did we discuss yesterday about the network setup?"
→ Returns the relevant session transcript, not just a single fact.
"""

import datetime
from config import get_chroma_client, get_logger

log = get_logger("episodic_memory")


def _get_episodic_collection():
    return get_chroma_client().get_or_create_collection("edith_episodic")


def save_episode(session_id: str, queries: list, summary: str = ""):
    """
    Save a session's conversation as an episode.

    Args:
        session_id: The unique session identifier.
        queries: List of user queries from the session.
        summary: Optional LLM-generated summary of the session.
    """
    if not queries:
        log.info("No queries to save as episode.")
        return

    timestamp = datetime.datetime.now().isoformat()

    # Build the episode document
    transcript = "\n".join(f"- {q}" for q in queries)
    episode_text = f"Session {session_id} ({timestamp})\n"
    if summary:
        episode_text += f"Summary: {summary}\n"
    episode_text += f"Queries:\n{transcript}"

    doc_id = f"episode_{session_id}"

    _get_episodic_collection().upsert(
        documents=[episode_text],
        ids=[doc_id],
        metadatas=[{
            "session_id": session_id,
            "timestamp": timestamp,
            "query_count": len(queries),
            "type": "episode",
        }],
    )
    log.info(f"Episode saved: {session_id} ({len(queries)} queries)")


def recall_episodes(query: str, n: int = 3) -> list:
    """
    Retrieve the most relevant past session episodes.

    Args:
        query: The search query to match against past episodes.
        n: Number of episodes to return.

    Returns:
        List of episode transcript strings.
    """
    try:
        count = _get_episodic_collection().count()
        if count == 0:
            return []
        results = _get_episodic_collection().query(
            query_texts=[query],
            n_results=min(n, count),
        )
        return results["documents"][0] if results["documents"] else []
    except Exception as e:
        log.error(f"Episodic recall failed: {e}")
        return []


def get_episode_count() -> int:
    """Return the total number of stored episodes."""
    try:
        return _get_episodic_collection().count()
    except Exception:
        return 0


def get_recent_episodes(n: int = 5) -> list:
    """Get the most recent episodes by timestamp."""
    try:
        all_docs = _get_episodic_collection().get()
        if not all_docs["documents"]:
            return []
        paired = list(zip(all_docs["documents"], all_docs["metadatas"]))
        paired.sort(key=lambda x: x[1].get("timestamp", ""), reverse=True)
        return [doc for doc, _ in paired[:n]]
    except Exception:
        return []


if __name__ == "__main__":
    print("[EDITH Episodic Memory] Testing...")

    # Save a test episode
    save_episode("test_001", [
        "How do I fix this Python error?",
        "Search for best ML frameworks 2026",
        "What is my schedule today?",
    ], summary="User debugged Python, researched ML, checked calendar.")

    # Recall
    results = recall_episodes("Python error debugging")
    print(f"Recall results: {results}")
    print(f"Total episodes: {get_episode_count()}")
    print("Done.")
