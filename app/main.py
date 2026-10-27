import asyncio
from pathlib import Path

from fastapi import BackgroundTasks, FastAPI, Form, Response
from fastapi.staticfiles import StaticFiles
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

from app.agent import describe_calendar_screenshot, route_message
from app.calendar import create_test_event, list_upcoming_events
from app.config import (
    PUBLIC_BASE_URL,
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_WHATSAPP_NUMBER,
)
from app.browser_agent import create_event_by_screen
from app.gmail import list_recent_inbox
from app.screenshot import capture_calendar_screenshot, capture_event_screenshot

ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = ROOT / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Personal AI Agent")
app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOT_DIR)), name="screenshots")
twilio_client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


@app.get("/health")
def health():
    return {"status": "ok"}


def event_line(event):
    start = event["start"].get("dateTime", event["start"].get("date"))
    return f"{start} {event.get('summary', '(no title)')}"


def parse_mode(body: str) -> tuple[str, str]:
    stripped = body.strip()
    if stripped.lower().startswith("screen:"):
        return "screen", stripped[7:].strip()
    return "api", stripped


def send_whatsapp(to: str, body: str, media_url: str | None = None):
    kwargs = {
        "from_": TWILIO_WHATSAPP_NUMBER,
        "to": to,
        "body": body,
    }
    if media_url:
        kwargs["media_url"] = [media_url]
    message = twilio_client.messages.create(**kwargs)
    print(f"Sent WhatsApp sid={message.sid} status={message.status}")


async def screen_list_and_reply(to: str):
    try:
        path = await asyncio.to_thread(capture_calendar_screenshot)
        text = await asyncio.to_thread(describe_calendar_screenshot, path)
        media_url = f"{PUBLIC_BASE_URL}/screenshots/{path.name}"
        print(f"Screenshot: {media_url}")
        print(text)
        await asyncio.to_thread(send_whatsapp, to, text, media_url)
    except Exception as error:
        print(error)
        await asyncio.to_thread(send_whatsapp, to, "Screen calendar request failed.")


async def screen_schedule_and_reply(to: str, title: str, when: str):
    try:
        text, path = await asyncio.to_thread(create_event_by_screen, title, when)
        media_url = f"{PUBLIC_BASE_URL}/screenshots/{path.name}"
        print(f"Screenshot: {media_url}")
        print(text)
        await asyncio.to_thread(send_whatsapp, to, text, media_url)
    except Exception as error:
        print(error)
        await asyncio.to_thread(send_whatsapp, to, "Screen schedule request failed.")


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(
    background_tasks: BackgroundTasks,
    From: str = Form(...),
    Body: str = Form(""),
):
    print(f"Incoming WhatsApp from {From}: {Body}")
    text = "Ask me to list events, schedule something, or check mail. Use screen: for calendar-by-screenshot."
    media_url = None

    try:
        mode, message = parse_mode(Body)
        print(f"Mode: {mode}")
        route = await asyncio.to_thread(route_message, message)
        print(f"Route: {route}")
        action = route["action"]

        if action == "list" and mode == "screen":
            background_tasks.add_task(screen_list_and_reply, From)
            text = "Looking at your calendar on screen..."
        elif action == "list":
            events = await asyncio.to_thread(list_upcoming_events)
            text = "\n".join(event_line(event) for event in events) or "No upcoming events found."
        elif action == "schedule" and mode == "screen":
            title = route["title"] or "Mira test"
            background_tasks.add_task(
                screen_schedule_and_reply,
                From,
                title,
                route["when"],
            )
            text = "Creating the event on screen..."
        elif action == "schedule":
            title = route["title"] or "Mira test"
            event = await asyncio.to_thread(create_test_event, title, route["when"])
            text = f"Created {event_line(event)}"
            event_url = event.get("htmlLink")
            if event_url:
                path = await asyncio.to_thread(capture_event_screenshot, event_url)
                media_url = f"{PUBLIC_BASE_URL}/screenshots/{path.name}"
                print(f"Screenshot: {media_url}")
        elif action == "mail":
            subjects = await asyncio.to_thread(list_recent_inbox)
            text = "\n".join(subjects) or "No inbox messages found."
    except Exception as error:
        text = "Request failed."
        print(error)

    print(text)
    reply = MessagingResponse()
    message = reply.message(text)
    if media_url:
        message.media(media_url)
    return Response(content=str(reply), headers={"Content-Type": "text/xml"})
