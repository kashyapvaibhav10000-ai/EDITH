import pickle
import base64
import os
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from googleapiclient.discovery import build
from google.auth.transport.requests import Request
from config import TOKEN_PICKLE_FILE, MODELS, get_logger

def _llm(*args, **kwargs):
    from config import safe_ollama_call
    r = safe_ollama_call(*args, **kwargs)
    return r.value if r.ok else r.error

def _llm_gen(*args, **kwargs):
    from config import safe_ollama_generate
    r = safe_ollama_generate(*args, **kwargs)
    return r.value if r.ok else r.error

log = get_logger("email_compose")

def get_gmail_service():
    with open(TOKEN_PICKLE_FILE, "rb") as f:
        creds = pickle.load(f)
    if creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(TOKEN_PICKLE_FILE, "wb") as f:
            pickle.dump(creds, f)
    return build("gmail", "v1", credentials=creds)

def draft_email_with_ai(instruction):
    prompt = f"""You are EDITH, a personal AI assistant. Draft a professional email based on this instruction:

Instruction: {instruction}

Respond ONLY in this exact JSON format, nothing else:
{{
  "to": "recipient@example.com"
  "subject": "Subject here"
  "body": "Full email body here"
}}"""
    import json
    response = _llm_gen(MODELS["chat"], prompt)
    # Strip markdown fences if present
    if response.startswith("```"):
        response = response.split("```")[1]
        if response.startswith("json"):
            response = response[4:]
    response = response.strip()
    return json.loads(response)

def send_email(service, to, subject, body):
    message = MIMEMultipart()
    message["to"] = to
    message["subject"] = subject
    message.attach(MIMEText(body, "plain"))
    raw = base64.urlsafe_b64encode(message.as_bytes()).decode()
    service.users().messages().send(userId="me", body={"raw": raw}).execute()

def compose_email():
    print("\n[EDITH Email] What should I write?")
    print("Example: 'Email john@example.com asking to reschedule our meeting to Friday'")
    instruction = input(">> ").strip()
    if not instruction:
        print("No instruction given.")
        return

    print("\n[EDITH] Drafting email...")
    try:
        draft = draft_email_with_ai(instruction)
    except Exception as e:
        log.error(f"Failed to draft email: {e}")
        print(f"[EDITH] Failed to draft email: {e}")
        return

    print("\n" + "="*50)
    print(f"  TO      : {draft['to']}")
    print(f"  SUBJECT : {draft['subject']}")
    print(f"  BODY    :\n")
    for line in draft["body"].split("\n"):
        print(f"    {line}")
    print("="*50)

    confirm = input("\nSend this email? [y/n]: ").strip().lower()
    if confirm == "y":
        service = get_gmail_service()
        send_email(service, draft["to"], draft["subject"], draft["body"])
        print("\n✅ Email sent!")
        log.info(f"Email sent to {draft['to']}")
    else:
        print("\n❌ Cancelled. Email not sent.")

    edit = input("\nWant to edit and retry? [y/n]: ").strip().lower()
    if edit == "y":
        print("\nWhat should I change?")
        changes = input(">> ").strip()
        new_instruction = f"{instruction}. Changes: {changes}"
        try:
            draft2 = draft_email_with_ai(new_instruction)
        except Exception as e:
            log.error(f"Failed to redraft: {e}")
            print(f"[EDITH] Failed to redraft: {e}")
            return

        print("\n" + "="*50)
        print(f"  TO      : {draft2['to']}")
        print(f"  SUBJECT : {draft2['subject']}")
        print(f"  BODY    :\n")
        for line in draft2["body"].split("\n"):
            print(f"    {line}")
        print("="*50)

        confirm2 = input("\nSend this email? [y/n]: ").strip().lower()
        if confirm2 == "y":
            service = get_gmail_service()
            send_email(service, draft2["to"], draft2["subject"], draft2["body"])
            print("\n✅ Email sent!")
        else:
            print("\n❌ Cancelled.")

if __name__ == "__main__":
    compose_email()
