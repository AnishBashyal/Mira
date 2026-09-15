from fastapi import FastAPI, Form, Response
from twilio.rest import Client
from twilio.twiml.messaging_response import MessagingResponse

from app.config import (
    TWILIO_ACCOUNT_SID,
    TWILIO_AUTH_TOKEN,
    TWILIO_CONTENT_SID,
    TWILIO_WHATSAPP_NUMBER,
)

app = FastAPI(title="Personal AI Agent")
client = Client(TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN)


@app.get("/health")
def health():
    return {"status": "ok"}


@app.post("/webhook/whatsapp")
async def whatsapp_webhook(
    From: str = Form(...),
    Body: str = Form(""),
):
    print(f"Incoming WhatsApp from {From}: {Body}")

    message = client.messages.create(
        from_=TWILIO_WHATSAPP_NUMBER,
        to=From,
        content_sid=TWILIO_CONTENT_SID,
    )
    print(f"Sent reply sid={message.sid} status={message.status}")

    return Response(content=str(MessagingResponse()), headers={"Content-Type": "text/xml"})
