"""
EDITH WhatsApp Module — Phase 5.1 (Stub)

Placeholder for WhatsApp bridge integration.
Requires whatsapp-web.js or similar bridge running on localhost.
All functions return stub responses until bridge is configured.

To activate: set WHATSAPP_BRIDGE_URL in .env and install the bridge.
"""

import os
from config import get_logger

log = get_logger("whatsapp")

BRIDGE_URL = os.getenv("WHATSAPP_BRIDGE_URL", "")
_bridge_active = bool(BRIDGE_URL)


def is_available() -> bool:
    """Check if WhatsApp bridge is configured and reachable."""
    if not _bridge_active:
        return False
    try:
        import requests
        r = requests.get(f"{BRIDGE_URL}/status", timeout=3)
        if r.status_code != 200:
            return False
        data = r.json()
        return data.get("ready", False)
    except Exception:
        return False


def send_message(contact: str, message: str) -> str:
    """Send a WhatsApp message (HITL gated)."""
    if not _bridge_active:
        return f"📱 [WhatsApp Stub] Would send to {contact}: {message[:50]}... (bridge not configured)"
    log.info(f"WhatsApp send to {contact}: {message[:50]}")
    try:
        import requests
        r = requests.post(f"{BRIDGE_URL}/send", json={
            "contact": contact, "message": message
        }, timeout=10)
        return f"✅ Message sent to {contact}" if r.status_code == 200 else f"❌ Send failed: {r.text}"
    except Exception as e:
        return f"❌ WhatsApp error: {e}"


def get_unread() -> str:
    """Get unread WhatsApp messages."""
    if not _bridge_active:
        return "📱 [WhatsApp Stub] Bridge not configured. Set WHATSAPP_BRIDGE_URL in .env"
    try:
        import requests
        r = requests.get(f"{BRIDGE_URL}/unread", timeout=10)
        if r.status_code != 200:
            return "No unread messages"
        data = r.json()
        msgs = data.get("messages", [])
        count = data.get("count", len(msgs))
        if not msgs:
            return "📱 No unread WhatsApp messages."
        lines = [f"📱 **{count} unread WhatsApp message(s):**\n"]
        for m in msgs:
            sender = m.get("from", "Unknown").replace("@c.us", "")
            body = m.get("body", "")
            lines.append(f"  • **{sender}**: {body}")
        return "\n".join(lines)
    except Exception as e:
        return f"❌ WhatsApp error: {e}"


def draft_message(contact: str, message: str) -> str:
    """Draft a message without sending (dry-run mode)."""
    return f"📝 [Draft] To: {contact}\nMessage: {message}\n\n⚠️ Type YES to send."


if __name__ == "__main__":
    print(f"WhatsApp bridge active: {_bridge_active}")
    print(f"Available: {is_available()}")
    print(send_message("John", "Hello from EDITH!"))
