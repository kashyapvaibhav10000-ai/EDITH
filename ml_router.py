from config import MODELS, get_logger

def _llm(*args, **kwargs):
    from config import safe_ollama_call
    r = safe_ollama_call(*args, **kwargs)
    return r.value if r.ok else r.error

def _llm_gen(*args, **kwargs):
    from config import safe_ollama_generate
    r = safe_ollama_generate(*args, **kwargs)
    return r.value if r.ok else r.error

log = get_logger("ml_router")

def detect_emotion_urgency(text):
    text_lower = text.lower()

    urgent_keywords = ["urgent", "asap", "emergency", "immediately", "now", "critical", "help", "stuck", "broken", "crash", "error", "failed"]
    urgency_score = sum(1 for w in urgent_keywords if w in text_lower)

    emotions = {
        "frustrated": ["frustrated", "annoyed", "angry", "stupid", "hate", "damn", "ugh", "not working", "broken"],
        "happy": ["thanks", "great", "awesome", "perfect", "love", "excellent", "amazing", "good job"],
        "confused": ["confused", "don't understand", "what does", "how does", "why does", "what is", "explain"],
        "stressed": ["stressed", "overwhelmed", "too much", "deadline", "pressure", "behind"],
        "neutral": [],
    }

    detected_emotion = "neutral"
    for emotion, keywords in emotions.items():
        if any(k in text_lower for k in keywords):
            detected_emotion = emotion
            break

    routes = {
        "coding": ["code", "bug", "function", "class", "python", "javascript", "error", "debug", "fix", "implement", "write"],
        "email": ["email", "send", "compose", "reply", "write to", "message to"],
        "search": ["search", "find", "look up", "what is", "who is", "latest", "news"],
        "vision": ["screenshot", "screen", "image", "photo", "look at", "see", "analyze"],
        "calendar": ["meeting", "schedule", "calendar", "appointment", "remind", "when is"],
        "memory": ["remember", "recall", "what did", "last time", "before", "history"],
        "video": ["youtube", "video", "summarize this", "watch"],
        "image": ["generate image", "create image", "draw", "picture of"],
        "vault": ["password", "credential", "login for", "secret"],
        "monitor": ["disk", "battery", "weather", "break", "system"],
        "general": [],
    }

    detected_route = "general"
    for route, keywords in routes.items():
        if any(k in text_lower for k in keywords):
            detected_route = route
            break

    AUTONOMY_SCORE = 97
    can_act_autonomously = AUTONOMY_SCORE >= 95 and urgency_score == 0

    return {
        "emotion": detected_emotion,
        "urgency": "HIGH" if urgency_score >= 2 else "MEDIUM" if urgency_score == 1 else "LOW",
        "route": detected_route,
        "autonomous": can_act_autonomously,
        "urgency_score": urgency_score,
    }

def get_response_style(emotion, urgency):
    styles = {
        "frustrated": "Be calm, patient, and extra clear. Acknowledge the frustration briefly.",
        "happy": "Match the positive energy. Be enthusiastic.",
        "confused": "Be extra detailed and use simple explanations with examples.",
        "stressed": "Be efficient and direct. No fluff. Get to the solution fast.",
        "neutral": "Be professional and concise.",
    }
    style = styles.get(emotion, styles["neutral"])
    if urgency == "HIGH":
        style += " URGENT — respond immediately with the most critical info first."
    return style

def route_query(user_input):
    analysis = detect_emotion_urgency(user_input)
    log.info(f"Emotion: {analysis['emotion']} | Urgency: {analysis['urgency']} | Route: {analysis['route']}")

    style = get_response_style(analysis["emotion"], analysis["urgency"])

    prompt = f"""You are EDITH, a personal AI assistant for Vaibhav.

Response style: {style}
Task type: {analysis['route']}

User message: {user_input}

Respond helpfully and concisely."""

    response = _llm_gen(MODELS["chat"], prompt)
    return analysis, response

if __name__ == "__main__":
    print("[EDITH ML Router] Active — emotion + urgency aware")
    print("Try: 'I am frustrated my code is broken help!'")
    print("Or:  'Can you explain how async works?'")
    print("Type 'exit' to quit\n")

    while True:
        user_input = input("You >> ").strip()
        if user_input.lower() == "exit":
            break
        if not user_input:
            continue
        analysis, response = route_query(user_input)
        print(f"\n[EDITH] {response}\n")
