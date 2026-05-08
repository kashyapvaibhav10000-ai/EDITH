"""
EDITH Vision 3 — Life OS
Decision simulation (5 branches), weekly briefings, persistent open loop tracking.
"""

import datetime
import hashlib
import time
from config import MODELS, get_chroma_client, get_logger
from smart_router import smart_call
from cognitive_profile import get_prime_directive, query_profile, get_recent_queries

log = get_logger("life_os")


def _get_loop_collection():
    return get_chroma_client().get_or_create_collection("edith_open_loops")


def simulate_decision(decision: str, context: str = "") -> str:
    """Run 5 thoughtful life simulation branches for a major decision."""
    prime = get_prime_directive()
    profile = "\n".join(query_profile(decision, n=5))

    prompt = f"""You are EDITH, a life simulation engine for Vaibhav.

PRIME DIRECTIVE: {prime}

USER PROFILE CONTEXT:
{profile if profile else "No prior context."}

ADDITIONAL CONTEXT: {context if context else "None"}

DECISION TO SIMULATE: {decision}

Run exactly 5 sequential life simulation branches. For each branch, think 6-12 months ahead.

FORMAT:
🔮 BRANCH 1 — MOST LIKELY PATH
What probably happens if Vaibhav does the obvious default choice.
Outcome: [1 sentence]
Risk: [1 sentence]

🏆 BRANCH 2 — BEST CASE PATH
The optimistic scenario where everything goes right.
Outcome: [1 sentence]
Key requirement: [1 sentence]

😌 BRANCH 3 — REGRET-MINIMISED PATH
The choice that minimises future regret regardless of outcome.
Outcome: [1 sentence]
Why low regret: [1 sentence]

🃏 BRANCH 4 — CONTRARIAN PATH
The unconventional choice that most people would not consider.
Outcome: [1 sentence]
Upside if right: [1 sentence]

🪨 BRANCH 5 — DO-NOTHING PATH
What happens if Vaibhav takes no action at all.
Outcome: [1 sentence]
Cost of inaction: [1 sentence]

──────────────
RECOMMENDATION: [Which branch and why, in 2 sentences]

Be specific to Vaibhav's situation. No generic advice."""

    return smart_call(prompt, intent="decision")


def weekly_briefing() -> str:
    """Generate EDITH's weekly briefing."""
    prime = get_prime_directive()
    recent = get_recent_queries(20)
    recent_text = "\n".join(f"- {q}" for q in recent) if recent else "No recent queries."
    today = datetime.datetime.now().strftime("%A, %d %B %Y")
    loops = get_open_loops()
    loop_text = "\n".join(f"- {l['description']}" for l in loops) if loops else "None"

    prompt = f"""You are EDITH generating a weekly briefing for Vaibhav.
Today is {today}.

PRIME DIRECTIVE: {prime}

RECENT ACTIVITY (last queries):
{recent_text}

OPEN LOOPS ({len(loops)} total):
{loop_text}

Generate a weekly briefing in this EXACT format:

═══════════════════════════════════════
  EDITH WEEKLY BRIEFING — {today}
═══════════════════════════════════════

🎯 TOP PRIORITY
[The single most important thing Vaibhav should focus on this week, based on prime directive]

⚡ LEVERAGE ACTIONS (3 max)
1. [Highest-ROI action this week]
2. [Second highest]
3. [Third]

⚠️ DRIFT ALERTS
[Any signs that recent behavior is drifting from prime directive. Say "No drift detected" if aligned]

🔄 OPEN LOOPS
[Unfinished threads that need closure. List max 5]

💡 INSIGHT
[One non-obvious observation about Vaibhav's patterns]

🧬 THIS WEEK'S UPGRADE PROPOSAL
[One proposed improvement to EDITH herself]

Be direct, specific, and honest. No fluff."""

    return smart_call(prompt, intent="briefing")


# ──────────────────────────────────────────────
# Open Loop Tracker (ChromaDB-persistent)
# ──────────────────────────────────────────────
def add_open_loop(description: str):
    """Track an unfinished item — persists across sessions."""
    uid = hashlib.md5(f"{description}{time.time()}".encode()).hexdigest()[:8]
    _get_loop_collection().add(
        documents=[description],
        ids=[uid],
        metadatas=[{"added": datetime.datetime.now().isoformat(), "closed": "false"}]
    )
    log.info(f"Open loop added: {description}")


def close_open_loop(loop_text: str):
    """Close an open loop by matching text."""
    try:
        if _get_loop_collection().count() == 0:
            print("No open loops to close.")
            return
        results = _get_loop_collection().query(query_texts=[loop_text], n_results=1)
        if results["ids"][0]:
            _get_loop_collection().delete(ids=[results["ids"][0][0]])
            log.info(f"Open loop closed: {loop_text[:60]}")
            print(f"Loop closed: {loop_text[:60]}")
    except Exception as e:
        log.error(f"Failed to close loop: {e}")


def get_open_loops() -> list:
    """Get all open loops."""
    try:
        if _get_loop_collection().count() == 0:
            return []
        all_data = _get_loop_collection().get()
        loops = []
        for doc, meta in zip(all_data["documents"], all_data["metadatas"]):
            if meta.get("closed") != "true":
                loops.append({"description": doc, "added": meta.get("added", "?")})
        return loops
    except Exception:
        return []


def format_open_loops() -> str:
    """Format open loops for display."""
    loops = get_open_loops()
    if not loops:
        return "No open loops."
    lines = []
    for i, loop in enumerate(loops):
        lines.append(f"  {i+1}. {loop['description']} (since {loop['added'][:10]})")
    return "\n".join(lines)


if __name__ == "__main__":
    print("[EDITH Life OS] Testing...")
    print(f"\nOpen loops: {format_open_loops()}")
    print("\n--- Decision Simulation ---")
    result = simulate_decision("Should I learn Rust or keep deepening Python?")
    print(result)
    print("\n--- Weekly Briefing ---")
    briefing = weekly_briefing()
    print(briefing)
