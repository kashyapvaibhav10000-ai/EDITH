import datetime
import os
from google.auth.transport.requests import Request
from errors import Result
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = ['https://www.googleapis.com/auth/calendar']
CREDS_FILE = '/home/vaibhav/EDITH/credentials.json'
TOKEN_FILE = '/home/vaibhav/EDITH/token.json'

def get_service():
    creds = None
    if os.path.exists(TOKEN_FILE):
        creds = Credentials.from_authorized_user_file(TOKEN_FILE, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDS_FILE, SCOPES)
            creds = flow.run_local_server(port=0)
        with open(TOKEN_FILE, 'w') as token:
            token.write(creds.to_json())
    return build('calendar', 'v3', credentials=creds)

def get_events(days_ahead=1, max_results=10):
    try:
        service = get_service()
        now = datetime.datetime.utcnow()
        end = now + datetime.timedelta(days=days_ahead)
        events_result = service.events().list(
            calendarId='primary',
            timeMin=now.isoformat() + 'Z',
            timeMax=end.isoformat() + 'Z',
            maxResults=max_results,
            singleEvents=True,
            orderBy='startTime'
        ).execute()
        return events_result.get('items', [])
    except Exception as e:
        return [{"error": str(e)}]

def format_events(events):
    if not events:
        return "No upcoming events found."
    if "error" in events[0]:
        return f"Calendar error: {events[0]['error']}"
    lines = []
    for e in events:
        start = e['start'].get('dateTime', e['start'].get('date', ''))
        if 'T' in start:
            dt = datetime.datetime.fromisoformat(start)
            time_str = dt.strftime("%d %b, %I:%M %p")
        else:
            time_str = start
        lines.append(f"• {e.get('summary', 'No title')} — {time_str}")
    return "\n".join(lines)

def get_today_briefing() -> Result:
    """Return today's calendar events. Returns Result[str]."""
    try:
        events = get_events(days_ahead=1)
        return Result.success(f"📅 Today's schedule:\n{format_events(events)}")
    except Exception as e:
        return Result.from_exception(e)

def get_week_briefing() -> Result:
    """Return this week's calendar events. Returns Result[str]."""
    try:
        events = get_events(days_ahead=7)
        return Result.success(f"📅 This week:\n{format_events(events)}")
    except Exception as e:
        return Result.from_exception(e)

if __name__ == "__main__":
    print(get_today_briefing())

def create_event(title, date_str, time_str=None, duration_minutes=60) -> Result:
    """Create a calendar event. Returns Result[str]."""
    try:
        service = get_service()
        datetime.datetime.strptime(date_str, "%Y-%m-%d")  # validate date format

        if time_str:
            start_dt = datetime.datetime.strptime(f"{date_str} {time_str}", "%Y-%m-%d %H:%M")
            end_dt = start_dt + datetime.timedelta(minutes=duration_minutes)
            event = {
                'summary': title,
                'start': {'dateTime': start_dt.isoformat(), 'timeZone': 'Asia/Kolkata'},
                'end': {'dateTime': end_dt.isoformat(), 'timeZone': 'Asia/Kolkata'},
            }
        else:
            event = {
                'summary': title,
                'start': {'date': date_str},
                'end': {'date': date_str},
            }

        created = service.events().insert(calendarId='primary', body=event).execute()
        return Result.success(f"✅ Event created: {created.get('summary')} on {date_str}")
    except Exception as e:
        return Result.failure(f"❌ Error creating event: {e}", error_type="unknown")
