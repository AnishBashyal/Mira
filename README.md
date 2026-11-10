# Mira

WhatsApp personal assistant for Senior Seminar. Uses Google Calendar/Gmail APIs, and a screenshot browser agent for screen tasks.

## Run

Terminal 1:

```bash
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

Terminal 2:

```bash
ngrok http 8000
```

WhatsApp sandbox: send `join design-news` if needed.

If Google API token breaks:

```bash
rm token.json
python -c "from app.calendar import get_credentials; get_credentials()"
```

If screen login is missing:

```bash
python -m app.browser_login
```

Health: http://127.0.0.1:8000/health  
Dashboard: http://127.0.0.1:8000/dashboard  

Webhook: `https://<ngrok-host>/webhook/whatsapp`

## WhatsApp

- `list` / `schedule ...` / `mail` → API  
- `screen: ...` → browser + screenshots  
- `stop` / `end` / `cancel` → stop a long screen run  

Screen is headless by default (`SCREEN_HEADED=0`). Use the dashboard to watch live screenshots and run history.
