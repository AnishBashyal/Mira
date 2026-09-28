# Mira

Personal WhatsApp assistant. Terminal 1 runs the server. Terminal 2 makes it reachable.

## Run

Terminal 1:

```bash
cd "/Users/anishbashyal/Desktop/Senior Seminar II"
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Terminal 2:

```bash
ngrok http 8000
```

Health check: http://127.0.0.1:8000/health

In Twilio, set **When a message comes in** to `https://<ngrok-host>/webhook/whatsapp` (HTTP POST). The host changes when ngrok restarts.

From WhatsApp: `list`, `schedule <title>`, or `mail`.
