"""
handlers/phone.py — Phone/messaging intent handlers (call, sms, phone, whatsapp)
"""

import re

from errors import Result
from context import DispatchContext
from handlers.helpers import extract_phone_number, extract_sms_body


def _handle_call(ctx: DispatchContext) -> Result:
    try:
        number = extract_phone_number(ctx.user_input)
        if number:
            from phone import initiate_call
            initiate_call(number)
            return Result.success(f"📞 Calling {number} now.")
        return Result.success("📞 Who should I call? Give me a number.")
    except Exception as e:
        return Result.from_exception(e)


def _handle_sms(ctx: DispatchContext) -> Result:
    try:
        from phone import send_sms
        number = extract_phone_number(ctx.user_input)
        body   = extract_sms_body(ctx.user_input)
        if not body:
            m = re.search(r"(?:say|saying)\s+(.+)", ctx.user_input, re.IGNORECASE)
            body = m.group(1).strip() if m else None
        if not number and not body:
            return Result.success("📱 What do you want to text? Try: 'send sms to +91XXXXXXXXXX saying hello'")
        if not number:
            return Result.success(f'📱 Got the message: "{body}". Who should I send it to?')
        if not body:
            return Result.success(f"📱 Got number {number}. What should the message say?")
        send_sms(number, body)
        return Result.success(f'📱 SMS sent to {number}: "{body}"')
    except Exception as e:
        return Result.from_exception(e)


def _handle_phone(ctx: DispatchContext) -> Result:
    try:
        from phone import ring_phone, get_notifications, phone_status
        lower = ctx.user_input.lower()
        if "ring" in lower or "find" in lower:
            ring_phone()
            return Result.success("📱 Ringing your phone now!")
        elif "notification" in lower:
            r = get_notifications()
            return Result.success(f"📱 {r.value if r.ok else r.error}")
        elif "battery" in lower:
            from phone import get_battery
            r = get_battery()
            return Result.success(f"📱 {r.value if r.ok else r.error}")
        r = phone_status()
        return Result.success(f"📱 {r.value if r.ok else r.error}")
    except Exception as e:
        return Result.from_exception(e)


def _handle_whatsapp(ctx: DispatchContext) -> Result:
    from intent_dispatch import set_pending_action

    try:
        from whatsapp import is_available, get_unread, draft_message, send_message, BRIDGE_URL
        lower = ctx.user_input.lower()
        if not is_available():
            if BRIDGE_URL:
                try:
                    import requests
                    r = requests.get(f"{BRIDGE_URL}/status", timeout=3)
                    if r.status_code == 200 and not r.json().get("ready"):
                        return Result.success(
                            "📱 WhatsApp bridge is running but not authenticated. "
                            "Scan the QR code in the bridge terminal."
                        )
                except Exception:
                    pass
                return Result.success("📱 WhatsApp bridge is not reachable. Make sure the bridge server is running.")
            return Result.success("📱 WhatsApp bridge not configured. Set WHATSAPP_BRIDGE_URL in .env.")
        if "unread" in lower or "check" in lower:
            return Result.success(f"📱 {get_unread()}")
        contact = extract_phone_number(ctx.user_input)
        body    = extract_sms_body(ctx.user_input)
        if not contact:
            return Result.success("📱 Who should I WhatsApp? Try: 'send WhatsApp to +91XXXXXXXXXX saying hello'")
        set_pending_action({"type": "whatsapp", "contact": contact, "message": body or ""})
        return Result.success(draft_message(contact, body or ""))
    except Exception as e:
        return Result.from_exception(e)


def handle(intent: str, ctx: DispatchContext) -> str:
    handlers = {
        "call":     _handle_call,
        "sms":      _handle_sms,
        "phone":    _handle_phone,
        "whatsapp": _handle_whatsapp,
    }
    fn = handlers.get(intent)
    if fn is None:
        return f"Unknown phone intent: {intent}"
    result = fn(ctx)
    if isinstance(result, Result):
        return str(result.value) if result.ok else str(result.error)
    return str(result)
