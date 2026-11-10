import json
from datetime import datetime
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types

from app.config import GEMINI_API_KEY

ACTIONS = {"list", "schedule", "mail", "web", "help"}

SYSTEM_PROMPT = """
You route WhatsApp messages for Mira, a personal assistant.
Return only JSON with keys:
- action: one of list, schedule, mail, web, help
- title: event title for schedule, else empty string
- when: ISO datetime with timezone offset for schedule, else empty string
Rules:
- list: user wants upcoming calendar events
- schedule: user wants to create a calendar event
- mail: user wants recent inbox subjects
- web: browse/search the web, open a site, look something up online,
  Wikipedia/Google/maps/news/portals, or any screenshot-browser task
- help: only if the message is empty, greeting-only, or truly not a task
Use America/Chicago for relative times like today, tomorrow, next Friday.
Resolve when from the current time given below. Do not invent past years.
If schedule is missing a clear title, leave title empty.
If schedule is missing a clear day/time, leave when empty.
Do not invent a title or time just to fill the fields.
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


def answer_from_screenshot(path, goal: str) -> str:
    """One-line answer for WhatsApp from the final page screenshot."""
    client = genai.Client(api_key=GEMINI_API_KEY)
    uploaded = client.files.upload(file=str(path))
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=[
            uploaded,
            (
                f"Goal: {goal}\n"
                "From this screenshot only, give the shortest useful answer "
                "(one short sentence or a single fact). "
                "If the answer is not visible, say what is on screen in one line."
            ),
        ],
    )
    return (response.text or "").strip() or "Done."


WEB_PLAN_PROMPT = """
You plan a screenshot-browser task from a short user message.
Return only JSON with keys:
- goal: clear imperative for a UI agent that only sees screenshots
- start_url: https URL to open first if a public site can be inferred, else empty string
- ask_user: one short question ONLY if a private/specific URL or critical detail is required; else empty string
- task_class: one of search, read, form, portal, other
Rules:
- For Wikipedia / Google / DuckDuckGo / news / well-known public sites, set start_url yourself. Do not ask.
- For college portals, banks, work intranets, or "my school account", leave start_url empty and ask for the link.
- Never put passwords or "log in with my credentials" in the goal. If a site needs login, say so in ask_user
  (e.g. ask for a public URL, or that the user must already be logged in in the browser).
- Ask at most for what is truly necessary. Prefer empty ask_user.
- Prefer public pages that can be completed without signing in.
- goal must stand alone (include what to find or do).
""".strip()


def plan_web_task(body: str) -> dict:
    client = genai.Client(api_key=GEMINI_API_KEY)
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=f"User message: {body}",
        config=types.GenerateContentConfig(
            system_instruction=WEB_PLAN_PROMPT,
            response_mime_type="application/json",
        ),
    )
    data = json.loads(response.text)
    task_class = (data.get("task_class") or "other").strip().lower()
    if task_class not in {"search", "read", "form", "portal", "other"}:
        task_class = "other"
    start_url = (data.get("start_url") or "").strip()
    if start_url and not start_url.startswith("http"):
        start_url = ""
    return {
        "goal": (data.get("goal") or body).strip(),
        "start_url": start_url,
        "ask_user": (data.get("ask_user") or "").strip(),
        "task_class": task_class,
    }
