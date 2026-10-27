import json
from datetime import datetime
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY

ACTIONS = {"list", "schedule", "mail", "help"}

SYSTEM_PROMPT = """
You route WhatsApp messages for Mira, a personal assistant.
Return only JSON with keys:
- action: one of list, schedule, mail, help
- title: event title for schedule, else empty string
- when: ISO datetime with timezone offset for schedule, else empty string
Rules:
- list: user wants upcoming calendar events
- schedule: user wants to create a calendar event
- mail: user wants recent inbox subjects
- help: anything else, or unclear
Use America/Chicago for relative times like today, tomorrow, next Friday.
Resolve when from the current time given below. Do not invent past years.
If schedule has no clear time, use tomorrow at 15:00 America/Chicago.
""".strip()


def route_message(body: str) -> dict:
    now = datetime.now(ZoneInfo("America/Chicago"))
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=(
            f"Current time: {now.isoformat()}\n"
            f"User message: {body}"
        ),
        config=types.GenerateContentConfig(
            system_instruction=SYSTEM_PROMPT,
            response_mime_type="application/json",
        ),
    )
    data = json.loads(response.text)
    action = data.get("action", "help")
    if action not in ACTIONS:
        action = "help"
    return {
        "action": action,
        "title": (data.get("title") or "").strip(),
        "when": (data.get("when") or "").strip(),
    }


def describe_calendar_screenshot(path) -> str:
    client = genai.Client(api_key=GEMINI_API_KEY)
    uploaded = client.files.upload(file=str(path))
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=[
            uploaded,
            (
                "This is a screenshot of Google Calendar. "
                "List the visible events with their times and titles. "
                "If none are visible, say so. Be short."
            ),
        ],
    )
    return (response.text or "").strip() or "No events visible in the screenshot."
