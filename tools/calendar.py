import os
from datetime import datetime, timedelta
from pathlib import Path
from zoneinfo import ZoneInfo

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build

SCOPES   = ["https://www.googleapis.com/auth/calendar"]
LOCAL_TZ = ZoneInfo(os.getenv("TIMEZONE", "America/New_York"))


def _get_service():
    creds = None
    token_file = os.getenv("GOOGLE_TOKEN_FILE", "google_token.json")
    creds_file = os.getenv("GOOGLE_CREDENTIALS_FILE", "google_credentials.json")

    if Path(token_file).exists():
        creds = Credentials.from_authorized_user_file(token_file, SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(creds_file, SCOPES)
            creds = flow.run_local_server(port=0)
        Path(token_file).write_text(creds.to_json())

    return build("calendar", "v3", credentials=creds)


def check_availability(date: str, duration_minutes: int = 60) -> list[dict]:
    """
    Returns open slots on `date` (YYYY-MM-DD) in LOCAL_TZ business hours.
    Checks the primary calendar for conflicts, returns up to 6 options.
    """
    service = _get_service()

    # Midnight → midnight in local time
    day_start = datetime(
        *[int(x) for x in date.split("-")], 0, 0, tzinfo=LOCAL_TZ
    )
    day_end = day_start + timedelta(days=1)

    events_result = service.events().list(
        calendarId="primary",
        timeMin=day_start.isoformat(),
        timeMax=day_end.isoformat(),
        singleEvents=True,
        orderBy="startTime",
    ).execute()

    busy_slots = []
    for ev in events_result.get("items", []):
        s = ev["start"].get("dateTime")
        e = ev["end"].get("dateTime")
        if s and e:
            busy_slots.append((
                datetime.fromisoformat(s).astimezone(LOCAL_TZ),
                datetime.fromisoformat(e).astimezone(LOCAL_TZ),
            ))

    # Candidate slots 9am–6pm in 30-min increments
    candidates = []
    slot_start     = day_start.replace(hour=9,  minute=0)
    business_close = day_start.replace(hour=18, minute=0)

    while slot_start + timedelta(minutes=duration_minutes) <= business_close:
        slot_end = slot_start + timedelta(minutes=duration_minutes)
        conflict = any(
            not (slot_end <= b[0] or slot_start >= b[1]) for b in busy_slots
        )
        if not conflict:
            candidates.append({
                "start": slot_start.isoformat(),
                "end":   slot_end.isoformat(),
                "label": slot_start.strftime("%-I:%M %p"),  # "9:00 AM" in local tz
            })
        slot_start += timedelta(minutes=30)

    return candidates[:6]


def book_appointment(
    summary: str,
    start_iso: str,
    end_iso: str,
    caller_name: str = "",
    caller_phone: str = "",
    description: str = "",
) -> dict:
    """Creates a Google Calendar event and returns its ID and link."""
    service = _get_service()
    tz_name = str(LOCAL_TZ)

    body = {
        "summary": summary,
        "description": (
            f"Booked by AI front desk\n"
            f"Caller: {caller_name}  {caller_phone}\n"
            f"{description}"
        ),
        "start": {"dateTime": start_iso, "timeZone": tz_name},
        "end":   {"dateTime": end_iso,   "timeZone": tz_name},
    }
    event = service.events().insert(calendarId="primary", body=body).execute()
    return {"event_id": event["id"], "link": event.get("htmlLink", "")}
