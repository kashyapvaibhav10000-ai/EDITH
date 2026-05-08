import imapclient
import email
from email.header import decode_header
import os
import vault
from dotenv import load_dotenv
from config import get_logger, MODELS
from errors import Result

def _llm(*args, **kwargs):
    from config import safe_ollama_call
    r = safe_ollama_call(*args, **kwargs)
    return r.value if r.ok else r.error

def _llm_gen(*args, **kwargs):
    from config import safe_ollama_generate
    r = safe_ollama_generate(*args, **kwargs)
    return r.value if r.ok else r.error

load_dotenv(os.path.join(os.path.dirname(__file__), ".env"))
log = get_logger("email_reader")

PROVIDERS = {
    "gmail": "imap.gmail.com",
    "outlook": "outlook.office365.com",
    "yahoo": "imap.mail.yahoo.com",
    "hotmail": "outlook.office365.com",
}

# Credentials — vault only (validated lazily in connect() to avoid import-time failure)
EMAIL_ADDRESS = vault.get_secret("GMAIL_ADDRESS", "") or os.getenv("GMAIL_ADDRESS", "")
APP_PASSWORD = vault.get_secret("GMAIL_APP_PASSWORD")
PROVIDER = "gmail"

def connect():
    if not APP_PASSWORD:
        raise RuntimeError("GMAIL_APP_PASSWORD not found in vault. Run: python vault.py set GMAIL_APP_PASSWORD <value>")
    server = PROVIDERS.get(PROVIDER, PROVIDER)
    client = imapclient.IMAPClient(server, ssl=True)
    client.login(EMAIL_ADDRESS, APP_PASSWORD)
    return client

def decode_str(s):
    if s is None:
        return ""
    decoded = decode_header(s)
    parts = []
    for part, enc in decoded:
        if isinstance(part, bytes):
            parts.append(part.decode(enc or "utf-8", errors="ignore"))
        else:
            parts.append(str(part))
    return " ".join(parts)

def get_body(msg):
    if msg.is_multipart():
        for part in msg.walk():
            ctype = part.get_content_type()
            disp = str(part.get("Content-Disposition"))
            if ctype == "text/plain" and "attachment" not in disp:
                return part.get_payload(decode=True).decode("utf-8", errors="ignore")
    else:
        return msg.get_payload(decode=True).decode("utf-8", errors="ignore")
    return ""

def fetch_emails(folder="INBOX", limit=5, unread_only=True):
    try:
        client = connect()
        client.select_folder(folder)
        if unread_only:
            messages = client.search(["UNSEEN"])
        else:
            messages = client.search(["ALL"])
        messages = sorted(messages, reverse=True)[:limit]
        if not messages:
            return []
        emails = []
        raw = client.fetch(messages, ["RFC822"])
        for uid, data in raw.items():
            raw_email = data[b"RFC822"]
            msg = email.message_from_bytes(raw_email)
            subject = decode_str(msg.get("Subject", "No Subject"))
            sender = decode_str(msg.get("From", "Unknown"))
            date = msg.get("Date", "Unknown date")
            body = get_body(msg)[:500]
            emails.append({"uid": uid, "subject": subject, "from": sender, "date": date, "body": body})
        client.logout()
        return emails
    except Exception as e:
        log.error(f"Email fetch failed: {e}")
        return [{"error": str(e)}]

def summarize_emails(emails):
    if not emails:
        return "No emails found."
    if "error" in emails[0]:
        return f"Email error: {emails[0]['error']}"
    summaries = []
    for i, em in enumerate(emails, 1):
        prompt = f"""Summarize this email in 1-2 sentences. Be concise.

From: {em['from']}
Subject: {em['subject']}
Body: {em['body']}

Summary:"""
        try:
            summary = _llm(MODELS["chat"], prompt)
            if summary.startswith("[EDITH] Ollama"):
                summary = "(Could not summarize — Ollama offline)"
        except Exception as e:
            log.error(f"Email summarize failed: {e}")
            summary = "(Could not summarize)"
        summaries.append(f"Email {i} from {em['from']}:\n  Subject: {em['subject']}\n  Summary: {summary}")
    return "\n\n".join(summaries)

def check_inbox(limit=5, unread_only=True) -> Result:
    """Fetch and summarize inbox. Returns Result[str]."""
    try:
        emails = fetch_emails(limit=limit, unread_only=unread_only)
        return Result.success(summarize_emails(emails))
    except Exception as e:
        log.error(f"check_inbox failed: {e}")
        return Result.from_exception(e)

if __name__ == "__main__":
    print("Checking inbox...")
    result = check_inbox()
    print(result)
