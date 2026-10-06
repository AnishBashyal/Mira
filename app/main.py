import asyncio
from pathlib import Path

from fastapi import FastAPI, Form, Response
from fastapi.staticfiles import StaticFiles
from twilio.twiml.messaging_response import MessagingResponse

from app.agent import route_message
from app.calendar import create_test_event, list_upcoming_events
from app.config import PUBLIC_BASE_URL
from app.gmail import list_recent_inbox
from app.screenshot import capture_event_screenshot

ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = ROOT / "screenshots"
SCREENSHOT_DIR.mkdir(exist_ok=True)

app = FastAPI(title="Personal AI Agent")
app.mount("/screenshots", StaticFiles(directory=str(SCREENSHOT_DIR)), name="screenshots")


@app.get("/health")
def health():
    return {"status": "ok"}


def event_line(event):
    start = event["start"].get("dateTime", event["start"].get("date"))
    return f"{start} {event.get('summary', '(no title)')}"


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(
    From: str = Form(...),
    Body: str = Form(""),
):
    print(f"Incoming WhatsApp from {From}: {Body}")
    text = "Ask me to list events, schedule something, or check mail."
    media_url = None

    try:
        route = await asyncio.to_thread(route_message, Body)
        print(f"Route: {route}")
        action = route["action"]

        if action == "list":
            events = await asyncio.to_thread(list_upcoming_events)
            text = "\n".join(event_line(event) for event in events) or "No upcoming events found."
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
