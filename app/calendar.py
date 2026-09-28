from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.readonly",
]
ROOT = Path(__file__).resolve().parent.parent
CREDENTIALS_FILE = ROOT / "credentials.json"
TOKEN_FILE = ROOT / "token.json"


def get_credentials():
    creds = None
    if TOKEN_FILE.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN_FILE))
    has_scopes = creds is not None and set(SCOPES).issubset(set(creds.scopes or []))
    if not creds or not creds.valid or not has_scopes:
        if creds and creds.expired and creds.refresh_token and has_scopes:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(str(CREDENTIALS_FILE), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN_FILE.write_text(creds.to_json())
    return creds


def list_upcoming_events(max_results=10):
    service = build("calendar", "v3", credentials=get_credentials())
    now = datetime.now(timezone.utc).isoformat()
    result = (
        service.events()
        .list(
            calendarId="primary",
            timeMin=now,
            maxResults=max_results,
            singleEvents=True,
            orderBy="startTime",
        )
        .execute()
    )
    return result.get("items", [])


def create_test_event(summary):
    tz = ZoneInfo("America/Chicago")
    start = (datetime.now(tz) + timedelta(days=1)).replace(hour=15, minute=0, second=0, microsecond=0)
    end = start + timedelta(hours=1)
    service = build("calendar", "v3", credentials=get_credentials())
    event = {
        "summary": summary,
        "start": {"dateTime": start.isoformat(), "timeZone": "America/Chicago"},
        "end": {"dateTime": end.isoformat(), "timeZone": "America/Chicago"},
    }
    return service.events().insert(calendarId="primary", body=event).execute()


def main():
    events = list_upcoming_events()
    if not events:
        print("No upcoming events found.")
        return
    for event in events:
        start = event["start"].get("dateTime", event["start"].get("date"))
        print(start, event.get("summary", "(no title)"))


if __name__ == "__main__":
    main()
