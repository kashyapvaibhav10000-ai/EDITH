"""
EDITH Vision 2 — Self-Improvement Loop
Reads ArXiv abstracts, proposes module rewrites and prompt upgrades.
"""

import requests
import xml.etree.ElementTree as ET
import datetime
from config import get_logger
from smart_router import smart_call

log = get_logger("self_improve")

ARXIV_API = "http://export.arxiv.org/api/query"
UPGRADE_LOG = []


def fetch_arxiv_abstracts(query: str = "large language model agent", max_results: int = 3) -> list:
    """Fetch the latest ArXiv abstracts on a topic (free API, no key needed)."""
    try:
        params = {
            "search_query": f"all:{query}",
            "start": 0,
            "max_results": max_results,
            "sortBy": "submittedDate",
            "sortOrder": "descending",
        }
        response = requests.get(ARXIV_API, params=params, timeout=15)
        root = ET.fromstring(response.text)
        ns = {"atom": "http://www.w3.org/2005/Atom"}

        papers = []
        for entry in root.findall("atom:entry", ns):
            title = entry.find("atom:title", ns).text.strip().replace("\n", " ")
            abstract = entry.find("atom:summary", ns).text.strip().replace("\n", " ")[:500]
            published = entry.find("atom:published", ns).text[:10]
            link = entry.find("atom:id", ns).text.strip()
            papers.append({
                "title": title,
                "abstract": abstract,
                "date": published,
                "url": link,
            })
        log.info(f"Fetched {len(papers)} ArXiv papers on '{query}'")
        return papers
    except Exception as e:
        log.error(f"ArXiv fetch failed: {e}")
        return []


def propose_upgrade(papers: list) -> str:
    """Given recent papers, propose one concrete upgrade to EDITH."""
    if not papers:
        return "No papers fetched — cannot propose upgrade."

    paper_text = ""
    for i, p in enumerate(papers, 1):
        paper_text += f"\n{i}. {p['title']} ({p['date']})\n   {p['abstract'][:300]}...\n"

    prompt = f"""You are EDITH's self-improvement engine. You have read these recent AI research papers:

{paper_text}

EDITH is a local-first personal AI assistant running on:
- System: Manjaro Linux, Python, Intel CPU, Local network
- ChromaDB for memory, pywhispercpp + vosk for STT, Piper for TTS
- Modules: intent routing, agent, RAG, vision, email, calendar, vault, sandbox

Based on these papers, propose exactly ONE concrete improvement to EDITH.

Format your response EXACTLY like this:
PROPOSED UPGRADE: [what to change]
REASON: [which paper inspired this and why]
EXPECTED GAIN: [what improves and by how much]
IMPLEMENTATION: [2-3 concrete steps]
DIFFICULTY: [Easy / Medium / Hard]

Be realistic — this runs on CPU with 1.5B params. No GPU-heavy suggestions."""

    result = smart_call(prompt, intent="self_improve")
    UPGRADE_LOG.append({
        "date": datetime.datetime.now().isoformat(),
        "papers": [p["title"] for p in papers],
        "proposal": result,
    })
    return result


def run_self_improvement():
    """Full self-improvement cycle: fetch papers → propose upgrade."""
    print("\n[EDITH Self-Improvement] Reading latest AI research...\n")

    topics = ["large language model agent", "retrieval augmented generation", "local AI assistant"]
    import random
    topic = random.choice(topics)
    print(f"  📚 Topic: {topic}")

    papers = fetch_arxiv_abstracts(topic, max_results=3)
    if not papers:
        print("  ❌ Could not fetch papers (check internet)")
        return None

    for i, p in enumerate(papers, 1):
        print(f"\n  [{i}] {p['title']}")
        print(f"      {p['date']} — {p['url']}")

    print("\n[EDITH] Analyzing papers for upgrade opportunities...\n")
    proposal = propose_upgrade(papers)
    print(proposal)
    return proposal


def get_upgrade_history() -> list:
    """Return history of proposed upgrades."""
    return UPGRADE_LOG


# ──────────────────────────────────────────────
# Phase 7.5: Persistent Upgrade Log
# ──────────────────────────────────────────────
import os
import json

_UPGRADE_LOG_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "upgrade_proposals.json")


def _save_upgrade_log():
    """Persist upgrade proposals to disk."""
    try:
        with open(_UPGRADE_LOG_FILE, "w") as f:
            json.dump(UPGRADE_LOG, f, indent=2)
    except Exception as e:
        log.error(f"Upgrade log save failed: {e}")


def _load_upgrade_log():
    """Load upgrade proposals from disk."""
    global UPGRADE_LOG
    try:
        if os.path.exists(_UPGRADE_LOG_FILE):
            with open(_UPGRADE_LOG_FILE) as f:
                UPGRADE_LOG = json.load(f)
    except Exception:
        UPGRADE_LOG = []


def score_proposal(proposal: str) -> float:
    """Score a proposal for relevance and actionability (0.0-1.0)."""
    score = 0.3  # Base
    lower = proposal.lower()

    # Actionability keywords
    action_words = ["implement", "add", "replace", "upgrade", "integrate",
                    "optimize", "use", "switch", "adopt"]
    score += min(0.3, sum(0.1 for w in action_words if w in lower))

    # EDITH-specific keywords
    edith_words = ["memory", "intent", "router", "agent", "voice", "context",
                   "privacy", "performance", "latency"]
    score += min(0.3, sum(0.1 for w in edith_words if w in lower))

    # Length penalty (too short or too long)
    words = len(proposal.split())
    if words < 20:
        score -= 0.1
    elif words > 500:
        score -= 0.1

    return round(max(0.0, min(1.0, score)), 2)


def run_scheduled_improvement() -> str:
    """Run self-improvement as a scheduled background task.

    Called by background_daemon at configured time.
    Returns a summary string.
    """
    _load_upgrade_log()

    papers = fetch_arxiv_abstracts(max_results=2)
    if not papers:
        return "No papers found"

    proposal = propose_upgrade(papers)
    score = score_proposal(proposal)

    entry = {
        "timestamp": datetime.datetime.now().isoformat(),
        "papers": [p["title"] for p in papers],
        "proposal": proposal[:500],
        "score": score,
        "status": "proposed",
    }
    UPGRADE_LOG.append(entry)
    _save_upgrade_log()

    log.info(f"Self-improvement ran: score={score}, papers={len(papers)}")

    # Publish to event bus → proactive.py picks up → Telegram push
    if score >= 0.4:
        try:
            from event_bus import bus, Topic
            bus.publish(Topic.SELF_IMPROVE_PROPOSAL, {
                "proposal": proposal[:500],
                "score": score,
                "papers": [p["title"] for p in papers],
            })
        except Exception as e:
            log.warning(f"Event bus publish failed: {e}")

    return f"Analyzed {len(papers)} papers, score: {score:.0%}\n{proposal[:200]}"


def get_upgrade_stats() -> dict:
    """Get upgrade statistics for Dashboard."""
    _load_upgrade_log()
    return {
        "total_proposals": len(UPGRADE_LOG),
        "avg_score": round(sum(e.get("score", 0) for e in UPGRADE_LOG) / max(len(UPGRADE_LOG), 1), 2),
        "last_run": UPGRADE_LOG[-1]["timestamp"] if UPGRADE_LOG else "Never",
    }


# Load on import
_load_upgrade_log()


if __name__ == "__main__":
    run_self_improvement()

