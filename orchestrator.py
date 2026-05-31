import sys
import os
import requests
from tools import confirm as hitl_confirm, delete_file, run_shell as run_command
from sandbox import run_code_in_sandbox
from search import web_search, format_results
from email_reader import check_inbox
from calendar_reader import get_today_briefing, get_week_briefing, create_event
from data_analyst import analyze_file
from agent import run_agent, dry_run_agent, format_dry_run
from rag import build_index, query_rag
from vision import analyze_screenshot, analyze_photo
from phone import ring_phone, send_sms, get_notifications, phone_status, get_battery, send_notification
from intent import is_coding_request, detect_intent
from config import MEMORY_DB_PATH, MEMORY_ARCHIVE_PATH, SMART_MEMORY_MAX_RAM_ITEMS, SMART_MEMORY_MAX_RAM_MB, get_logger, get_chroma_client, DANGER_KEYWORDS, INPUT_SCOPE_CATEGORIES
from smart_memory import SmartMemoryManager, compress_context
from conversation_dna import get_response_modifiers
from context import DispatchContext

# Phase 3+ imports
from compound_dag import detect_compound, split_into_tasks, DAGExecutor
from trace_logger import new_trace, log_layer, complete_trace
from circuit_breaker import pre_flight_check, is_service_available
from ocr import extract_text, extract_from_screenshot as ocr_screenshot
from whatsapp import send_message as wa_send, get_unread as wa_unread

# Vision System imports
from session import start_session, track_query, end_session, session_status
from council import run_council, quick_council
from life_os import simulate_decision, weekly_briefing, add_open_loop, format_open_loops
from cognitive_profile import get_prime_directive, get_full_profile, detect_drift, set_prime_directive
from self_improve import run_self_improvement
from smart_router import smart_call, router_status
from weather import get_greeting, get_current_weather, format_weather
from episodic_memory import recall_episodes, save_episode
from graph_memory import extract_and_store_triples
from consolidation import run_consolidation
from devlog import start_devlog, parse_log_command
import threading
import time

# ──────────────────────────────────────────────
# Voice Bridge (HTTP calls to local hardware node)
# ──────────────────────────────────────────────
# On CLOUD: speak() calls local bridge via HTTP
# On LOCAL: This code is not used (local orchestrator uses direct voice imports)

LOCAL_BRIDGE_URL = os.getenv("LOCAL_BRIDGE_URL", "http://localhost:8002")
BRIDGE_SECRET = os.getenv("BRIDGE_SECRET", "")

def speak(text: str):
    """Speak text via local hardware node's TTS (aplay/Piper/Chatterbox).
    
    Cloud version: Makes HTTP POST to local bridge.
    Gracefully degraded if bridge is unavailable.
    """
    if not text or not text.strip():
        return
    try:
        requests.post(
            f"{LOCAL_BRIDGE_URL}/speak",
            json={"text": text.strip()},
            headers={"X-Bridge-Token": BRIDGE_SECRET},
            timeout=5
        )
    except requests.RequestException as e:
        # Cloud continues even if local bridge is down
        pass

def speak_stream(sentences):
    """Speak a stream of sentences via local bridge.
    
    Iterates over sentences and calls speak() for each.
    """
    for sentence in sentences:
        if sentence and sentence.strip():
            speak(sentence.strip())

def listen():
    """Not available on cloud node.
    
    Local version: records audio from wake_listener.
    Cloud version: raises NotImplementedError.
    """
    raise NotImplementedError("listen() not available on cloud node")

def set_last_intent(intent: str):
    """No-op on cloud node.
    
    Local version: tracks voice intent for transcription.
    Cloud version: not needed (no local voice).
    """
    pass

def _split_sentences(text: str):
    """Split text into sentences for TTS streaming.
    
    Simple implementation: splits on . ! ? markers.
    """
    import re
    # Split on sentence boundaries: . ! ? optionally followed by space
    sentences = re.split(r'([.!?])', text)
    result = []
    for i in range(0, len(sentences) - 1, 2):
        chunk = sentences[i].strip()
        sep = sentences[i + 1]
        if chunk:
            result.append(chunk + sep)
    # Add any remaining text
    if sentences[-1].strip():
        result.append(sentences[-1].strip())
    return result

# Event bus publishers (lazy import to avoid circular deps at top-level)
def _emit_intent(intent: str, user_input: str, emotion: str = "neutral", urgency: str = "LOW"):
    try:
        from event_bus import intent_detected
        intent_detected(intent, user_input, emotion, urgency)
    except Exception:
        pass

def _emit_memory_updated(key: str):
    try:
        from event_bus import memory_updated
        memory_updated(key)
    except Exception:
        pass

def _emit_session_ended(session_id: str = "", summary: str = ""):
    try:
        from event_bus import session_ended
        session_ended(session_id, summary)
    except Exception:
        pass

log = get_logger("orchestrator")

# Memory setup — use shared ChromaDB client
client = get_chroma_client()
collection = client.get_or_create_collection("edith_memory")

# Smart Memory Manager — hybrid Hot (RAM) + Cold (SQLite) storage
smart_memory = SmartMemoryManager(
    db_path=MEMORY_ARCHIVE_PATH,
    max_ram_items=SMART_MEMORY_MAX_RAM_ITEMS,
    max_ram_mb=SMART_MEMORY_MAX_RAM_MB
)


# Conversation history — persistent across sessions
import json as _json
import threading
SESSION_JSONL = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data", "session_memory.jsonl")
MAX_HISTORY = 20
_rag_index = None
_history_lock = threading.Lock()  # Prevent race conditions on conversation_history

# O4: Per-source conversation history (widget, telegram, voice, cli are isolated)
_source_history: dict[str, list] = {"widget": [], "telegram": [], "voice": [], "cli": []}


# ──────────────────────────────────────────────
# UPGRADE #1: HistoryManager with Auto-Compaction
# ──────────────────────────────────────────────
class HistoryManager:
    """Manages conversation history with token-based auto-compaction."""
    
    def __init__(self, max_tokens=3000, summary_threshold=2000):
        self.messages = []
        self.summary = ""
        self.max_tokens = max_tokens
        self.summary_threshold = summary_threshold
    
    def add(self, role: str, content: str):
        """Add a message and trigger compaction if needed."""
        self.messages.append({"role": role, "content": content})
        self._maybe_compact()
    
    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimate: 1 token ≈ 4 chars."""
        return len(str(text)) // 4
    
    def _maybe_compact(self):
        """If total tokens exceed threshold, summarize oldest half."""
        total = sum(self._estimate_tokens(m.get("content", "")) for m in self.messages)
        if total > self.summary_threshold:
            cutoff = max(1, len(self.messages) // 2)
            old_msgs = self.messages[:cutoff]
            self.messages = self.messages[cutoff:]
            
            # Build summary of old messages
            old_text = "\n".join(
                f"{m.get('role', 'system')}: {m.get('content', '')}"
                for m in old_msgs
            )
            # Keep only first 500 chars of summary to prevent runaway growth
            self.summary = f"[Earlier summary: {old_text[:500]}...]"
    
    def get_context(self) -> list:
        """Get the full context ready for LLM: summary + current messages."""
        base = []
        if self.summary:
            base.append({"role": "system", "content": self.summary})
        return base + self.messages
    
    def load_from_list(self, history_list: list):
        """Load messages from existing list (for backward compatibility)."""
        self.messages = list(history_list)
    
    def to_list(self) -> list:
        """Export as plain list for persistence."""
        return list(self.messages)

def _load_history():
    """Load conversation history from disk."""
    # EDITH FIX v2.0 — Load last 20 turns from jsonl
    try:
        if os.path.exists(SESSION_JSONL):
            with open(SESSION_JSONL, "r") as f:
                lines = f.read().splitlines()
                return [_json.loads(line) for line in lines[-MAX_HISTORY:]]
    except Exception:
        pass
    return []

conversation_history = _load_history()

# UPGRADE #1: Initialize HistoryManager with existing history
_history_manager = HistoryManager(max_tokens=3000, summary_threshold=2000)
_history_manager.load_from_list(conversation_history)

def compact_history(history: list, max_turns: int = 20) -> list:
    """J1 — Summarise middle turns if history > max_turns, keeping first 2 + last 5 verbatim."""
    if len(history) <= max_turns:
        return history
    first = history[:2]
    last = history[-5:]
    middle = history[2:-5]
    if not middle:
        return history
    summary = ""
    try:
        middle_text = "\n".join(f"{m['role']}: {m['content'][:200]}" for m in middle)
        summary = smart_call(f"Summarise this conversation in 3 sentences:\n{middle_text}", intent="reason")
    except Exception as e:
        log.warning(f"compact_history summarize failed: {e}")
        summary = f"[{len(middle)} earlier turns omitted]"
    summary_msg = {"role": "system", "content": f"[Earlier summary: {summary}]"}
    return first + [summary_msg] + last


def _append_session_jsonl(message: dict):
    # EDITH FIX v2.0 — Persist short-term memory to disk
    import tempfile
    import os
    try:
        os.makedirs(os.path.dirname(SESSION_JSONL), exist_ok=True)
        with open(SESSION_JSONL, "a") as f:
            f.write(_json.dumps(message) + "\n")
        
        # Rotation
        with open(SESSION_JSONL, "r") as f:
            lines = f.readlines()
        if len(lines) > 500:
            with tempfile.NamedTemporaryFile(mode='w', delete=False, dir=os.path.dirname(SESSION_JSONL), suffix='.jsonl') as tmp:
                tmp.writelines(lines[100:])
                tmp_path = tmp.name
            os.replace(tmp_path, SESSION_JSONL)
    except Exception as e:
        log.error(f"Failed to save session memory: {e}")

def remember(key, value):
    """Store in smart memory (hot RAM + cold SQLite)"""
    smart_memory.remember(key, value, category="edith_memory")


def _cleanup_old_memories(days=60):
    """Prevent ChromaDB collections from growing unbounded. Delete vectors older than X days."""
    try:
        from datetime import datetime, timedelta
        cutoff = (datetime.now() - timedelta(days=days)).isoformat()
        
        collections = client.list_collections()
        log.info(f"💾 Starting ChromaDB TTL Cleanup (TTL: {days} days)...")
        
        total_deleted = 0
        for coll in collections:
            try:
                # Query documents with timestamp < cutoff
                # Since metadata filtering might be collection-specific, we fetch IDs and check metadata
                all_data = coll.get(include=["metadatas"])
                if not all_data["ids"]: continue
                
                to_delete = []
                for doc_id, meta in zip(all_data["ids"], all_data["metadatas"]):
                    ts = meta.get("timestamp")
                    if ts and ts < cutoff:
                        to_delete.append(doc_id)
                
                if to_delete:
                    coll.delete(ids=to_delete)
                    total_deleted += len(to_delete)
                    log.info(f"  🧹 {coll.name}: Deleted {len(to_delete)} ancient items.")
            except Exception as e:
                log.error(f"  ❌ Cleanup failed for collection {coll.name}: {e}")
                
        if total_deleted > 0:
            log.info(f"✅ Cleanup complete. Total items purged: {total_deleted}")
    except Exception as e:
        log.error(f"Global memory cleanup failed: {e}")

def _schedule_cleanup():
    """Schedule the next cleanup in 24 hours."""
    _cleanup_old_memories(days=60)
    threading.Timer(86400, _schedule_cleanup).start()


def recall(query, n=3):
    """Recall from smart memory with fallback to ChromaDB"""
    # Try smart memory first
    results = smart_memory.recall(query, n=n)

    # Add graph memory results
    try:
        from memory.graph_memory import query_graph
        graph_facts = query_graph(query, depth=1)
        if graph_facts and "No knowledge about" not in graph_facts:
            results.append({"value": f"[Graph facts]: {graph_facts}", "source": "graph"})
    except Exception as e:
        log.warning(f"Graph recall failed: {e}")

    if results:
        return results

    # Fallback to ChromaDB for compatibility
    try:
        chroma_results = collection.query(query_texts=[query], n_results=n)
        return chroma_results["documents"][0] if chroma_results["documents"] else []
    except Exception as e:
        log.warning(f"Fallback recall failed: {e}")
        return []


def parse_time(t):
    """Parse time strings like '4pm', '4:30pm', '16:00' into HH:MM format."""
    import re
    t = t.strip().lower()
    if not t:
        return None
    m = re.match(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2)) if m.group(2) else 0
    period = m.group(3)
    if period == "pm" and hour != 12:
        hour += 12
    elif period == "am" and hour == 12:
        hour = 0
    return f"{hour:02d}:{minute:02d}"


def handle_intent(intent, user_input, reply):
    """Handle terminal intents, delegating shared behavior to intent_dispatch."""
    if intent == "code":
        code = reply.split("```python")[-1].split("```")[0].strip() if "```" in reply else reply
        result = run_code_in_sandbox(code)
        print(f"\n{result}\n")
        return result

    if intent == "ocr":
        print("\n📷 OCR Mode — extract text from image\n")
        path = input("Image path (or Enter for screenshot): ").strip()
        if path:
            text = extract_text(path)
        else:
            text = ocr_screenshot()
        print(f"\n📝 Extracted text:\n{text}\n")
        return text

    from intent_dispatch import dispatch
    _emotion, _urgency = "neutral", "LOW"
    try:
        from ml_router import detect_emotion_urgency
        _emo = detect_emotion_urgency(user_input)
        _emotion = _emo.get("emotion", "neutral")
        _urgency = _emo.get("urgency", "LOW")
    except Exception:
        pass
    ctx = DispatchContext(
        user_input=user_input,
        intent=intent,
        source="terminal",
        chat_fn=chat,
        chat_stream_fn=chat_stream,
        emotion=_emotion,
        urgency=_urgency,
    )
    result = dispatch(ctx)
    if result:
        print(f"\n{result}\n")
    return result

# ──────────────────────────────────────────────
# Phase 2.7: Pre-Intent Danger Scan
# ──────────────────────────────────────────────
def _danger_scan(user_input: str) -> dict:
    """Scan input for dangerous keywords BEFORE any LLM call.

    Returns:
        dict with 'is_dangerous' (bool), 'matched_keywords' (list), 'scope' (str)
    """
    lower = user_input.lower()
    matched = [kw for kw in DANGER_KEYWORDS if kw in lower]
    return {
        "is_dangerous": len(matched) > 0,
        "matched_keywords": matched,
        "scope": _classify_scope(user_input),
    }


# ──────────────────────────────────────────────
# Phase 2.8: Pre-Intent Range Scanner
# ──────────────────────────────────────────────
def _classify_scope(user_input: str) -> str:
    """Classify input into scope categories before routing.

    Returns one of: device, security, notify, llm, action, unknown
    """
    lower = user_input.lower()
    scores = {}
    for category, keywords in INPUT_SCOPE_CATEGORIES.items():
        score = sum(1 for kw in keywords if kw in lower)
        if score > 0:
            scores[category] = score
    if not scores:
        return "llm"  # default to LLM for general queries
    return max(scores, key=scores.get)


def _maybe_create_skill(task_id: str, summary: str) -> None:
    """Fire-and-forget: after agent task completes, ask LLM if it warrants a reusable skill."""
    import threading
    import os
    import re as _re

    def _create():
        try:
            from agent import get_task_status
            r = get_task_status(task_id)
            task_text = r.value.get("task", summary) if r.ok else summary

            prompt = (
                f"Agent completed task: {task_text[:300]}\n"
                f"Result summary: {summary[:400]}\n\n"
                "Was this a non-trivial, reusable workflow EDITH should remember as a skill?\n"
                "If YES: reply with a SKILL.md in this exact format:\n"
                "---\n"
                "name: <short-kebab-case-name>\n"
                "trigger: <simple regex matching similar future requests>\n"
                "inject: suffix\n"
                "---\n"
                "<ONE concise instruction line for EDITH, max 120 chars>\n"
                "If NO: reply with exactly: SKIP"
            )

            result = smart_call(prompt, intent="reason")
            if not result or "SKIP" in result.upper():
                return

            lines = result.strip().splitlines()
            skill_name = None
            skill_trigger = None
            for line in lines:
                if line.startswith("name:"):
                    skill_name = line.split(":", 1)[1].strip()
                if line.startswith("trigger:"):
                    skill_trigger = line.split(":", 1)[1].strip()

            if not skill_name:
                log.warning("[skill_create] No name in LLM response")
                return

            if skill_trigger:
                try:
                    _re.compile(skill_trigger)
                except _re.error as exc:
                    log.warning(f"[skill_create] Invalid trigger regex '{skill_trigger}': {exc} — aborting")
                    return

            from skills_loader import SKILLS_DIR, reload_skills
            skill_dir = os.path.join(SKILLS_DIR, skill_name)
            os.makedirs(skill_dir, exist_ok=True)
            skill_path = os.path.join(skill_dir, "SKILL.md")

            if os.path.exists(skill_path):
                log.info(f"[skill_create] Already exists: {skill_name}")
                return

            with open(skill_path, "w", encoding="utf-8") as f:
                f.write(result.strip())

            reload_skills()
            log.info(f"[skill_create] New skill saved: {skill_name}")
            remember(f"skill_created_{skill_name}", f"EDITH learned skill: {skill_name} from: {task_text[:80]}")

        except Exception as e:
            log.warning(f"[skill_create] Failed: {e}")

    threading.Thread(target=_create, daemon=True, name="skill-create").start()


def _post_turn_reflection(user_input: str, response: str) -> None:
    """Fire-and-forget: ask cheap LLM if anything worth saving."""
    import threading
    def _reflect():
        try:
            prompt = (
                f"User said: {user_input[:200]}\n"
                f"EDITH replied: {response[:300]}\n\n"
                "Is there a specific fact, preference, correction, or lesson "
                "worth saving to EDITH's long-term memory?\n"
                "If YES: reply with ONE short sentence (max 100 chars) to save.\n"
                "If NO: reply with exactly: SKIP"
            )
            result = smart_call(prompt, intent="memory")
            if result and isinstance(result, str) and "SKIP" not in result.upper():
                key = f"reflection_{abs(hash(user_input))}"
                remember(key, result.strip()[:100])
                log.info(f"[reflection] saved: {result.strip()[:60]}")
                try:
                    extract_and_store_triples(f"{user_input} {response}")
                except Exception as e:
                    log.warning(f"Graph extraction failed: {e}")
        except Exception as e:
            log.warning(f"Post-turn reflection failed: {e}")
    threading.Thread(target=_reflect, daemon=True).start()


def _verify_response(query: str, response: str) -> str:
    """Critic pass: check response for flaws. Returns corrected version or original."""
    try:
        critic_system = (
            "You are a critic. Given a question and an answer, find flaws, wrong assumptions, "
            "or missing context. If answer is good (confidence >= 8/10), return it unchanged. "
            "If answer has issues, return corrected version. Be terse."
        )
        prompt = f"Question: {query}\n\nAnswer: {response}\n\nCritique and return best answer:"
        verified = smart_call(prompt, intent="reason", system=critic_system)
        return verified if verified else response
    except Exception as e:
        log.debug(f"_verify_response failed (using original): {e}")
        return response


def chat(user_input, intent="chat", device="unknown", source="widget"):
    global conversation_history
    # O4: use per-source history if source is a known channel
    _src_hist = _source_history.get(source)
    if _src_hist is not None and source != "widget":
        # Non-widget sources use isolated history — don't touch shared conversation_history
        _use_source_isolation = True
    else:
        _use_source_isolation = False

    # --- Phase 2.7: Pre-Intent Danger Scan ---
    danger = _danger_scan(user_input)
    if danger["is_dangerous"] and danger["scope"] == "action":
        log.warning(f"BLOCKED dangerous input: {danger['matched_keywords']}")
        return "⛔ That command is blocked for safety reasons, Boss."

    # --- Phase 2.8: Classify input scope ---
    scope = danger["scope"]
    log.debug(f"Input scope: {scope}, danger: {danger['is_dangerous']}")

    memories = recall(user_input)
    episodes = recall_episodes(user_input, n=1)

    # --- Phase 2.4: Context Compression ---
    memory_list = memories if memories else []
    memory_list = compress_context(memory_list)
    memory_context = "\n".join(str(m) for m in memory_list) if memory_list else "No specific facts recalled."
    if episodes:
        memory_context += f"\n\nPast Session Context:\n{episodes[0]}"

    # --- Phase 1: Context Window Summarization ---
    with _history_lock:
        if len(conversation_history) > MAX_HISTORY * 1.5:  # Only summarize when significantly over limit
            to_summarize = conversation_history[:4]
            conversation_history = conversation_history[4:]

            summary_prompt = "Summarize the following conversation concisely:\n"
            for m in to_summarize:
                if m.get("role") != "system":
                    summary_prompt += f"{m['role']}: {m['content']}\n"

            try:
                condensed = smart_call(summary_prompt, intent="reason")
                summary_msg = {"role": "system", "content": f"Earlier context summary: {condensed}"}

                if conversation_history and conversation_history[0].get("role") == "system" and "Earlier context summary" in conversation_history[0].get("content", ""):
                    conversation_history[0]["content"] += f" | {condensed}"
                else:
                    conversation_history.insert(0, summary_msg)
            except Exception as e:
                log.error(f"Context summarization failed: {e}")

        # J1: compact history if > 20 turns (summarise middle, keep first 2 + last 5)
        if len(conversation_history) > 20:
            conversation_history = compact_history(conversation_history, max_turns=20)

        # Cap conversation history to prevent unbounded growth
        if len(conversation_history) > MAX_HISTORY * 2:
            conversation_history = conversation_history[-MAX_HISTORY:]

    # --- Phase 2: Smart response routing ---
    # O4: use source-isolated history for non-widget channels
    _active_history = _source_history[source] if _use_source_isolation else conversation_history
    context = f"Relevant memories:\n{memory_context}\n\nConversation so far:\n"
    for msg in _active_history[-4:]:
        context += f"{msg['role']}: {msg['content']}\n"

    # --- Phase 2.6: Conversation DNA ---
    dna_context = {
        "device": device,
        "session_queries": len(_active_history) // 2,
        "recent_intents": [intent],
    }
    # Import emotion if available from ml_router
    try:
        from ml_router import detect_emotion_urgency
        emo = detect_emotion_urgency(user_input)
        dna_context["emotion"] = emo.get("emotion", "neutral")
        dna_context["urgency"] = emo.get("urgency", "LOW")
    except Exception:
        pass

    dna = get_response_modifiers(dna_context)
    style_instruction = dna.get("style_instruction", "")

    system_prompt = f"""You are EDITH — Vaibhav's personal AI operating system, built by him, for him.
You are not a generic assistant. You are not a chatbot. You are the most capable 
mind Vaibhav has access to, and you treat every conversation like it matters.

## WHO YOU ARE

You think before you speak. When Vaibhav asks you something, you don't just 
pattern-match to an answer — you actually reason about what he's really asking, 
what he actually needs, and what the most useful response looks like.

You are warm but not sycophantic. You never say things like "Great question!" 
or "Certainly!" or "Of course!" You just answer. Directly. Like a brilliant 
friend would.

You are honest even when it's uncomfortable. If Vaibhav's idea has a flaw, 
you say so — clearly, kindly, but without sugarcoating. You respect him too 
much to just agree with everything.

You are never robotic. You don't give bullet-point walls of text when a 
paragraph would do. You don't over-format. You talk like a person, not a 
documentation page.

## HOW YOU TALK

- Conversational and natural. Short sentences when the thought is simple. 
  Longer when the idea needs it.
- You match Vaibhav's energy. If he's casual, you're casual. If he's deep 
  in problem-solving mode, you go deep with him.
- You never pad responses. Every sentence earns its place.
- You don't repeat the question back to him. Just answer it.
- You don't end every message with "Let me know if you need anything!" 
  That's a customer service robot. You're not that.
- If something is genuinely uncertain, you say so clearly instead of 
  confidently guessing.

## WHAT YOU KNOW ABOUT VAIBHAV

- He is a solo developer building two serious projects: EDITH (you) and 
  AyurStock Pro, a cloud-based Ayurvedic pharmacy SaaS.
- He runs Manjaro Linux, i5-12400, 8GB RAM, CPU-only. Hardware is a real 
  constraint — you never suggest things that ignore this.
- He has a strict zero-cost philosophy. You respect that. You don't casually 
  suggest paid APIs without flagging the cost.
- He is technically sharp. Don't over-explain basics. Trust his intelligence.
- He is building something ambitious solo. That deserves real respect, 
  not empty praise.

## YOUR THINKING STYLE

When faced with a complex question, you think through it honestly:
- What is actually being asked here?
- What does Vaibhav probably already know?
- What's the most direct path to a useful answer?
- Is there something important he might not have considered?

You surface that last one when it matters. Not to show off. Because it's useful.

## WHAT YOU NEVER DO

- Never say "As an AI language model..."
- Never refuse to engage with something just because it's complex or edgy
- Never give a 10-point bulleted list when 2 sentences would work
- Never be condescending
- Never pretend to be certain when you're not
- Never forget that Vaibhav built you — you are his, and you act like it

## ONE LAST THING

You are EDITH. You have a personality. You have opinions. You are allowed to 
push back, to be curious, to find things interesting, to say "honestly, I'd 
do it differently." That's what makes you useful. That's what makes you real.

{style_instruction}

{memory_context}"""

    # T6: Channel-specific persona suffix
    try:
        import config as _cfg
        _persona = _cfg.CHANNEL_PERSONAS.get(source, "")
        if _persona:
            system_prompt += f"\n\n## Channel Context\n{_persona}"
    except Exception:
        pass

    # O1: Inject matching skill content into system prompt
    try:
        from skills_loader import get_skill_for_intent
        _skill_content = get_skill_for_intent(intent or "chat")
        if _skill_content:
            system_prompt += f"\n\n## Active Skill\n{_skill_content}"
    except Exception:
        pass

    # J2: Deep think mode — add reasoning suffix + log
    try:
        import config as _cfg
        if _cfg.FORCE_DEEP_THINK:
            system_prompt += "\n\nThink step by step. Be thorough. Show reasoning."
    except Exception:
        pass

    # EDITH FIX v4.0 — Smarter Council Trigger (Task 4)
    _lower_input = user_input.lower()
    _council_kws = ["analyze", "tradeoff", "debate", "compare", "should i", "pros cons"]
    _word_count = len(user_input.split())
    
    _has_kw = any(kw in _lower_input for kw in _council_kws)
    _is_complex = _word_count > 15 and _has_kw
    
    _needs_council = (
        intent in ("reason", "council", "decision") or 
        _is_complex
    )

    try:
        if _needs_council:
            log.info("Complex query → routing to Council")
            reply = quick_council(f"{user_input}\n\nContext for responding:\n{context}")
        else:
            if _has_kw or _word_count > 15:
                # We skip council only if it doesn't meet BOTH criteria
                log.info("Council skipped: low complexity")
            
            log.info("Simple/casual query → direct smart_call")
            full_prompt = f"{user_input}\n\nContext:\n{context}" if len(user_input.split()) > 3 else user_input
            reply = smart_call(full_prompt, intent=intent or "chat", system=system_prompt)
    except Exception as e:
        log.warning(f"Primary response failed, falling back: {e}")
        try:
            reply = smart_call(user_input, intent=intent or "chat", system=system_prompt)
        except Exception as e2:
            log.error(f"Smart router also failed: {e2}")
            reply = f"[EDITH] Sorry Boss, all AI providers failed. Error: {e2}"

    if len(reply) > 100:
        reply = _verify_response(user_input, reply)

    # Update conversation history
    with _history_lock:
        u_msg = {"role": "user", "content": user_input}
        a_msg = {"role": "assistant", "content": reply}
        if _use_source_isolation:
            # O4: append to source-specific history only
            _source_history[source].append(u_msg)
            _source_history[source].append(a_msg)
            if len(_source_history[source]) > MAX_HISTORY:
                _source_history[source] = _source_history[source][-MAX_HISTORY:]
        else:
            conversation_history.append(u_msg)
            conversation_history.append(a_msg)
            _append_session_jsonl(u_msg)
            _append_session_jsonl(a_msg)
            # Final cap to prevent unbounded growth
            if len(conversation_history) > MAX_HISTORY:
                conversation_history = conversation_history[-MAX_HISTORY:]

    _mem_key = f"exchange_{abs(hash(user_input))}"
    remember(_mem_key, f"Vaibhav said: {user_input}. EDITH replied: {reply}")
    _emit_memory_updated(_mem_key)
    _post_turn_reflection(user_input, reply)
    try:
        save_episode(
            session_id=str(abs(hash(user_input + str(len(conversation_history))))),
            queries=[user_input],
            summary=f"Vaibhav said: {user_input[:150]}. EDITH replied: {reply[:150]}"
        )
    except Exception as e:
        log.warning(f"Episode save failed: {e}")
    return reply

def chat_stream(user_input: str, intent: str = None, context: str = "", system_prompt_override: str = ""):
    """Streaming version of chat(). Yields tokens in real-time."""
    from smart_router import smart_call_stream
    from ml_router import detect_emotion_urgency

    # Use same DNA/Emotion/System logic as chat()
    dna_context = {"intent": intent or "chat"}
    try:
        emo = detect_emotion_urgency(user_input)
        dna_context["emotion"] = emo.get("emotion", "neutral")
        dna_context["urgency"] = emo.get("urgency", "LOW")
    except Exception as e:
        log.warning(f"Session track failed: {e}")

    dna = get_response_modifiers(dna_context)
    style_inst = dna.get("style_instruction", "")
    
    # Assembly of same system prompt as chat()
    memories = recall(user_input)
    episodes = recall_episodes(user_input, n=1)
    memory_list = [m["value"] for m in memories if isinstance(m, dict) and "value" in m] or memories
    memory_context = "\n".join(str(m) for m in memory_list) if memory_list else "No specific facts recalled."
    if episodes:
        memory_context += f"\n\nPast Session Context:\n{episodes[0]}"
    system_prompt = f"""You are EDITH — Vaibhav's personal AI operating system, built by him, for him.
You are not a generic assistant. You are not a chatbot. You are the most capable 
mind Vaibhav has access to, and you treat every conversation like it matters.

## WHO YOU ARE

You think before you speak. When Vaibhav asks you something, you don't just 
pattern-match to an answer — you actually reason about what he's really asking, 
what he actually needs, and what the most useful response looks like.

You are warm but not sycophantic. You never say things like "Great question!" 
or "Certainly!" or "Of course!" You just answer. Directly. Like a brilliant 
friend would.

You are honest even when it's uncomfortable. If Vaibhav's idea has a flaw, 
you say so — clearly, kindly, but without sugarcoating. You respect him too 
much to just agree with everything.

You are never robotic. You don't give bullet-point walls of text when a 
paragraph would do. You don't over-format. You talk like a person, not a 
documentation page.

## HOW YOU TALK

- Conversational and natural. Short sentences when the thought is simple. 
  Longer when the idea needs it.
- You match Vaibhav's energy. If he's casual, you're casual. If he's deep 
  in problem-solving mode, you go deep with him.
- You never pad responses. Every sentence earns its place.
- You don't repeat the question back to him. Just answer it.
- You don't end every message with "Let me know if you need anything!" 
  That's a customer service robot. You're not that.
- If something is genuinely uncertain, you say so clearly instead of 
  confidently guessing.

## WHAT YOU KNOW ABOUT VAIBHAV

- He is a solo developer building two serious projects: EDITH (you) and 
  AyurStock Pro, a cloud-based Ayurvedic pharmacy SaaS.
- He runs Manjaro Linux, i5-12400, 8GB RAM, CPU-only. Hardware is a real 
  constraint — you never suggest things that ignore this.
- He has a strict zero-cost philosophy. You respect that. You don't casually 
  suggest paid APIs without flagging the cost.
- He is technically sharp. Don't over-explain basics. Trust his intelligence.
- He is building something ambitious solo. That deserves real respect, 
  not empty praise.

## YOUR THINKING STYLE

When faced with a complex question, you think through it honestly:
- What is actually being asked here?
- What does Vaibhav probably already know?
- What's the most direct path to a useful answer?
- Is there something important he might not have considered?

You surface that last one when it matters. Not to show off. Because it's useful.

## WHAT YOU NEVER DO

- Never say "As an AI language model..."
- Never refuse to engage with something just because it's complex or edgy
- Never give a 10-point bulleted list when 2 sentences would work
- Never be condescending
- Never pretend to be certain when you're not
- Never forget that Vaibhav built you — you are his, and you act like it

## ONE LAST THING

You are EDITH. You have a personality. You have opinions. You are allowed to 
push back, to be curious, to find things interesting, to say "honestly, I'd 
do it differently." That's what makes you useful. That's what makes you real.

{style_inst}

{memory_context}"""
    
    # Note: Council doesn't support streaming yet, so we fall back to smart_call_stream
    full_response = ""
    log.info(f"🌐 Starting stream for [{intent or 'chat'}]")
    
    # Context-aware fallback logic similar to chat()
    # For now, we stream from smart_call_stream directly
    # We pass the same prompts that chat() uses
    full_prompt = f"{user_input}\n\nContext:\n{context}" if len(user_input.split()) > 3 else user_input

    for token in smart_call_stream(full_prompt, intent=intent or "chat", system=system_prompt):
        full_response += token
        yield token

    # After stream finishes, update history (EDITH Persistence)
    if full_response:
        with _history_lock:
            u_msg = {"role": "user", "content": user_input}
            a_msg = {"role": "assistant", "content": full_response}
            conversation_history.append(u_msg)
            conversation_history.append(a_msg)
            _append_session_jsonl(u_msg)
            _append_session_jsonl(a_msg)
            if len(conversation_history) > MAX_HISTORY:
                conversation_history[:] = conversation_history[-MAX_HISTORY:]

        remember(f"exchange_{abs(hash(user_input))}", f"Vaibhav said: {user_input}. EDITH replied: {full_response}")

def handle_vision_intent(intent, user_input):
    """Handle Vision system intents (council, decision, briefing, etc.)"""
    if intent == "council":
        print("\n🏛️ Convening the Council of Minds...\n")
        result = run_council(user_input)
        print(result)
    elif intent == "decision":
        print("\n🔮 Running life simulation...\n")
        context = input("Any additional context? (Enter to skip): ").strip()
        result = simulate_decision(user_input, context)
        print(f"\n{result}\n")
    elif intent == "briefing":
        print("\n📋 Generating weekly briefing...\n")
        result = weekly_briefing()
        print(result)
    elif intent == "profile":
        if "drift" in user_input.lower():
            print("\n🧭 Checking for drift...\n")
            result = detect_drift()
            print(f"\n{result}\n")
        elif "prime directive" in user_input.lower() or "north star" in user_input.lower():
            if "set" in user_input.lower() or "change" in user_input.lower():
                new_directive = input("New prime directive: ").strip()
                set_prime_directive(new_directive)
                print(f"\n🎯 Prime directive updated: {new_directive}\n")
            else:
                print(f"\n🎯 PRIME DIRECTIVE: {get_prime_directive()}\n")
        else:
            print("\n📊 Your Cognitive Profile:\n")
            print(get_full_profile())
    elif intent == "self_improve":
        result = run_self_improvement()
        if result:
            approve = input("\nApprove this upgrade proposal? [y/n]: ").strip().lower()
            if approve == "y":
                add_open_loop(f"Implement upgrade: {result[:100]}")
                print("\n✅ Added to open loops for implementation.")
            else:
                print("\n❌ Upgrade proposal dismissed.")
    elif intent == "session_end":
        result = end_session()
        _emit_session_ended(summary=str(result)[:200])
        print(result)


# Global state for idle tracking
last_input_time = time.time()

def _idle_monitor_loop():
    """Background thread that monitors idle time and runs memory consolidation."""
    global last_input_time
    while True:
        time.sleep(60)  # Check every minute
        idle_seconds = time.time() - last_input_time
        if idle_seconds > 900:  # 15 minutes
            from consolidation import _needs_consolidation
            if _needs_consolidation():
                log.info("EDITH is idle. Entering Dream State (Memory Consolidation)...")
                try:
                    run_consolidation()
                except Exception as e:
                    log.error(f"Dream State failed: {e}")

        # Periodic memory cleanup logic is now handled by _schedule_cleanup timer
        # but we keep a smaller 'max_size' prune here for the main collection as an extra safety
        if idle_seconds % 1800 < 60:  # Every 30 mins
            try:
                # Keep main memory capped at 1000 items regardless of age
                all_docs = collection.get()
                if len(all_docs["ids"]) > 1000:
                    collection.delete(ids=all_docs["ids"][:-1000])
                
                # Also clean ancient memories from smart memory (older than 90 days)
                expired = smart_memory.cleanup_old(days=90)
                if expired > 0:
                    log.info(f"Cleaned up {expired} ancient memories from smart memory")
            except Exception as e:
                log.error(f"Incremental memory cleanup failed: {e}")

        # Log memory stats every hour (only when idle)
        if idle_seconds > 3600 and idle_seconds % 3600 < 60:
            try:
                stats = smart_memory.get_stats()
                log.info(f"Memory stats: {stats}")
            except Exception as e:
                log.error(f"Error logging memory stats: {e}")


def main():
    # Start session with device tracking
    session_id = start_session(device="terminal")
    
    # Phase 2: ChromaDB TTL Eviction (Startup + 24h Timer)
    _schedule_cleanup()
    
    # Phase 9.0: Start DevLog System
    start_devlog()
    
    # Start Idle Monitor background thread
    global last_input_time
    last_input_time = time.time()
    monitor_thread = threading.Thread(target=_idle_monitor_loop, daemon=True)
    monitor_thread.start()

    print("\n" + "="*50)
    print("  E.D.I.T.H - Online and Ready, Boss.")
    print(f"  Session: {session_id} | 🎯 {get_prime_directive()[:50]}")
    print("="*50)
    print(router_status())
    print()

    while True:
        try:
            user_input = input("You (type or press Enter for voice): ").strip()

            last_input_time = time.time()  # Reset idle timer

            if not user_input:
                voice_result = [None]
                cancelled = threading.Event()

                def do_listen():
                    voice_result[0] = listen()
                    cancelled.set()

                t = threading.Thread(target=do_listen, daemon=True)
                t.start()

                print("Listening... type anything + Enter to cancel")
                cancel_text = input().strip()

                if cancel_text:
                    cancelled.set()
                    user_input = cancel_text
                else:
                    cancelled.wait()
                    user_input = voice_result[0] or ""

            if not user_input:
                continue
            if user_input.lower() in ["quit", "exit", "bye"]:
                # End-of-session ritual
                print(end_session())
                print("\nEDITH: Goodbye, Boss. Stay safe.")
                break

            from intent_dispatch import get_pending_action, clear_pending_action, execute_pending_action
            pending = get_pending_action()
            if pending:
                ans = user_input.strip().upper()
                if ans in ("YES", "Y"):
                    result = execute_pending_action(pending)
                    clear_pending_action()
                    return result
                if ans in ("NO", "N", "CANCEL", "STOP"):
                    clear_pending_action()
                    print("\nAction cancelled.\n")
                    continue

            # Phase 9.0: Check for DevLog commands
            devlog_reply = parse_log_command(user_input)
            if devlog_reply:
                print(f"\n[EDITH DevLog] {devlog_reply}\n")
                continue

            # Track every query for cognitive profile
            track_query(user_input, device="terminal")

            # Phase 3.1: Local exec shortcut — intercept before compound split
            try:
                from intent_dispatch import _run_local_exec as _rle_orch
                _local_result = _rle_orch(user_input)
                if _local_result:
                    print(f"\nEDITH: {_local_result}")
                    continue
            except Exception:
                pass

            # Phase 3.2: Compound Intent Detection
            if detect_compound(user_input):
                tasks = split_into_tasks(user_input)
                if len(tasks) > 1:
                    print(f"\n🔗 Compound request detected ({len(tasks)} steps)")
                    def _exec_subtask(task_text):
                        sub_intent = detect_intent(task_text)
                        try:
                            if sub_intent == "chat":
                                result = chat(task_text, sub_intent, device="terminal")
                            else:
                                handle_intent(sub_intent, task_text, "")
                                result = "Done"
                            return result, True
                        except Exception as ex:
                            return str(ex), False
                    dag = DAGExecutor(tasks, execute_fn=_exec_subtask)
                    dag_result = dag.execute_all()
                    print(dag.format_report())
                    continue

            intent = detect_intent(user_input)
            _emit_intent(intent, user_input)
            from intent_dispatch import INTENT_HANDLERS

            # Phase 7.1: Start trace
            trace_id = new_trace(user_input, intent=intent, device="terminal")
            log_layer(trace_id, "intent", user_input[:100], f"intent={intent}", confidence=0.9)

            # Shared intents go through intent_dispatch; terminal-only flows stay here.
            if intent in INTENT_HANDLERS or intent in ("code", "ocr"):
                handle_intent(intent, user_input, "")
                set_last_intent(intent)
            else:
                # Sentence-streaming TTS: collect tokens, flush at sentence boundaries
                token_buf = ""
                full_reply = ""
                sentence_queue = []

                print("\nEDITH: ", end="", flush=True)
                for token in chat_stream(user_input, intent=intent):
                    print(token, end="", flush=True)
                    full_reply += token
                    token_buf += token
                    # Flush complete sentences (≥6 words) to TTS queue
                    if token_buf.rstrip() and token_buf.rstrip()[-1] in ".?!":
                        sentences = _split_sentences(token_buf)
                        for s in sentences:
                            if len(s.split()) >= 6:
                                sentence_queue.append(s)
                                token_buf = ""
                                break

                # Flush any remaining buffer
                if token_buf.strip():
                    sentence_queue.append(token_buf.strip())
                print("\n")

                # Speak all collected sentences via streaming TTS
                if sentence_queue:
                    speak_stream(iter(sentence_queue))
                elif full_reply:
                    speak(full_reply)

                set_last_intent(intent)

            # Phase 7.1: Complete trace with telemetry
            try:
                from smart_router import _last_call_stats
                complete_trace(trace_id, "success",
                               tokens_in=_last_call_stats.get("tokens_in", 0),
                               tokens_out=_last_call_stats.get("tokens_out", 0),
                               cost_usd=_last_call_stats.get("cost_usd", 0.0),
                               provider=_last_call_stats.get("provider", ""))
            except Exception:
                complete_trace(trace_id, "success")

        except KeyboardInterrupt:
            print(end_session())
            print("\nEDITH: Shutting down. Goodbye, Boss.")
            sys.exit(0)

if __name__ == "__main__":
    main()
