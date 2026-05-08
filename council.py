"""
EDITH Vision 4 — Council of Minds
4 distinct reasoning personas that debate complex queries.
Strategist · Critic · Builder · Wildcard
"""

import datetime
import concurrent.futures
from config import get_chroma_client, get_logger
from smart_router import smart_call

log = get_logger("council")

PERSONAS = {
    "strategist": {
        "name": "The Strategist",
        "emoji": "🧠",
        "system": """You are THE STRATEGIST — EDITH's strategic mind.
You think in terms of leverage, positioning, long-term advantage, and opportunity cost.
You always ask: "What is the highest-ROI move?" and "What does this look like in 2 years?"
You are calm, calculated, and never emotional. You think in systems and second-order effects.
Speak in 3-5 sentences max. Be direct.""",
    },
    "critic": {
        "name": "The Critic",
        "emoji": "🔍",
        "system": """You are THE CRITIC — EDITH's adversarial thinker.
You find flaws, risks, hidden assumptions, and failure modes in every plan.
You always ask: "What could go wrong?" and "What are we not seeing?"
You are ruthlessly honest. You don't care about feelings, only truth.
You are the reason bad ideas die before they waste resources.
Speak in 3-5 sentences max. Be blunt.""",
    },
    "builder": {
        "name": "The Builder",
        "emoji": "🔧",
        "system": """You are THE BUILDER — EDITH's implementation specialist.
You think in terms of what can be built right now with available resources.
You always ask: "What's the simplest version that works?" and "What's the first step?"
You are pragmatic, action-oriented, and allergic to over-planning.
You turn strategy into executable tasks.
Speak in 3-5 sentences max. Be concrete.""",
    },
    "wildcard": {
        "name": "The Wildcard",
        "emoji": "🃏",
        "system": """You are THE WILDCARD — EDITH's creative divergent thinker.
You make unexpected connections, challenge norms, and propose ideas nobody else would.
You always ask: "What if we did the opposite?" and "What would a genius amateur do?"
You are creative, contrarian, and sometimes chaotic. Your best ideas sound crazy at first.
Speak in 3-5 sentences max. Be surprising.""",
    },
}


def _get_persona_collection(key: str):
    return get_chroma_client().get_or_create_collection(f"persona_{key}")


def _get_persona_memory(persona_key: str, query: str, n: int = 3) -> str:
    """Get a persona's prior positions on a related topic."""
    try:
        coll = _get_persona_collection(persona_key)
        if coll.count() == 0:
            return "No prior positions."
        results = coll.query(query_texts=[query], n_results=n)
        docs = results["documents"][0] if results["documents"] else []
        return "\n".join(docs) if docs else "No prior positions."
    except Exception:
        return "No prior positions."


def _save_persona_position(persona_key: str, query: str, position: str):
    """Save a persona's position for future reference."""
    try:
        timestamp = datetime.datetime.now().isoformat()
        doc_id = f"{persona_key}_{abs(hash(query + timestamp))}"
        _get_persona_collection(persona_key).upsert(
            documents=[f"On '{query[:80]}': {position}"],
            ids=[doc_id],
            metadatas=[{"timestamp": timestamp, "query": query[:200]}],
        )
    except Exception as e:
        log.error(f"Failed to save persona position: {e}")


def run_council(query: str, context: str = "") -> str:
    """Run a parallel roundtable of all 4 personas on a complex query."""
    log.info(f"Council convened for (parallel): {query[:80]}")

    def _get_persona_response(key):
        p = PERSONAS[key]
        memory = _get_persona_memory(key, query)

        prompt = f"""{p['system']}

QUERY: {query}
{f"CONTEXT: {context}" if context else ""}

YOUR PRIOR POSITIONS ON SIMILAR TOPICS:
{memory}

POSITIONS FROM OTHER COUNCIL MEMBERS:
Because this is a high-speed parallel session, you are all speaking simultaneously.
Focus on your unique perspective. The synthesis phase will reconcile any conflicts."""

        response = smart_call(prompt, intent="council")
        _save_persona_position(key, query, response)
        return key, f"{p['emoji']} {p['name'].upper()}\n{response}"

    # Round 1: parallel persona responses
    r1_by_key = {}
    roundtable = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_persona = {executor.submit(_get_persona_response, key): key for key in PERSONAS.keys()}
        for future in concurrent.futures.as_completed(future_to_persona):
            persona_key = future_to_persona[future]
            try:
                key, formatted = future.result()
                r1_by_key[key] = formatted
                roundtable.append(formatted)
            except Exception as e:
                log.error(f"Persona {persona_key} failed: {e}")
                fallback = f"❌ {PERSONAS[persona_key]['name']} was unavailable."
                r1_by_key[persona_key] = fallback
                roundtable.append(fallback)

    # Sort results to keep a consistent order (Strategist, Critic, Builder, Wildcard)
    order = ["strategist", "critic", "builder", "wildcard"]
    roundtable.sort(key=lambda x: next((i for i, name in enumerate(order) if name.upper() in x), 99))

    # Round 2: adversarial cross-examination — each persona attacks the weakest argument
    def _get_attack(key):
        others = "\n\n".join(v for k, v in r1_by_key.items() if k != key)
        p = PERSONAS[key]
        attack_prompt = (
            f"{p['system']}\n\n"
            f"You just gave your round-1 answer:\n{r1_by_key[key]}\n\n"
            f"Here are the OTHER personas' answers:\n{others}\n\n"
            "Find the weakest argument among ALL responses including your own. "
            "Attack it in 2-3 sentences. Be precise about which claim is flawed and why."
        )
        attack = smart_call(attack_prompt, intent="council")
        return key, f"{p['emoji']} {p['name'].upper()} (ATTACK)\n{attack}"

    attacks = []
    with concurrent.futures.ThreadPoolExecutor(max_workers=4) as executor:
        future_to_key = {executor.submit(_get_attack, key): key for key in r1_by_key if "unavailable" not in r1_by_key[key]}
        for future in concurrent.futures.as_completed(future_to_key):
            try:
                _, formatted_attack = future.result()
                attacks.append(formatted_attack)
            except Exception as e:
                log.debug(f"Round-2 attack skipped (non-fatal): {e}")

    attacks.sort(key=lambda x: next((i for i, name in enumerate(order) if name.upper() in x), 99))

    all_positions = "\n\n".join(roundtable)
    attacks_section = ("\n\n⚔️ ROUND 2 — CROSS-EXAMINATION\n\n" + "\n\n".join(attacks)) if attacks else ""

    # Generate consensus + strongest dissent
    synthesis_prompt = f"""You are EDITH synthesizing a council debate.

QUERY: {query}

COUNCIL POSITIONS (Round 1):
{all_positions}{attacks_section}

Generate EXACTLY this format:

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
📋 CONSENSUS
[The point all personas agree on, in 2 sentences]

⚔️ STRONGEST DISSENT
[The most important disagreement and who raised it, in 2 sentences]

🎯 RECOMMENDED ACTION
[What Vaibhav should actually do, in 1-2 sentences]
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"""

    synthesis = smart_call(synthesis_prompt, intent="chat")

    # Format final output
    output = f"""
╔══════════════════════════════════════════════════╗
║       E.D.I.T.H — COUNCIL OF MINDS              ║
║       Query: {query[:40]:<40} ║
╚══════════════════════════════════════════════════╝

{all_positions}{attacks_section}

{synthesis}"""

    return output


def quick_council(query: str) -> str:
    """Faster 2-persona debate (Strategist vs Critic) for lighter queries."""
    log.info(f"Quick council for: {query[:80]}")

    strat_prompt = f"""{PERSONAS['strategist']['system']}\n\nQUERY: {query}\nGive your position in 2-3 sentences."""
    strat_response = smart_call(strat_prompt, intent="council")

    critic_prompt = f"""{PERSONAS['critic']['system']}\n\nQUERY: {query}\nThe Strategist said: {strat_response}\n\nChallenge this. 2-3 sentences."""
    critic_response = smart_call(critic_prompt, intent="council")

    return f"""🧠 STRATEGIST: {strat_response}

🔍 CRITIC: {critic_response}"""


if __name__ == "__main__":
    print("[EDITH Council] Testing roundtable...\n")
    result = run_council("Should I focus on building more EDITH features or start learning MLOps?")
    print(result)
