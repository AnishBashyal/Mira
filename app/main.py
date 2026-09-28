from fastapi import FastAPI, Form, Response
from twilio.twiml.messaging_response import MessagingResponse

from app.calendar import create_test_event, list_upcoming_events
from app.gmail import list_recent_inbox

app = FastAPI(title="Personal AI Agent")


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
    text = "Send list, schedule <title>, or mail."

    try:
        if "list" in Body.lower():
            events = list_upcoming_events()
            text = "\n".join(event_line(event) for event in events) or "No upcoming events found."
        elif Body.lower().startswith("schedule"):
            title = Body[8:].strip() or "Mira test"
            event = create_test_event(title)
            text = f"Created {event_line(event)}"
        elif "mail" in Body.lower():
            subjects = list_recent_inbox()
            text = "\n".join(subjects) or "No inbox messages found."
    except Exception as error:
        text = "Request failed."
        print(error)

    print(text)
    reply = MessagingResponse()
    reply.message(text)
    return Response(content=str(reply), headers={"Content-Type": "text/xml"})
