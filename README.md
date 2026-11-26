# Mira

WhatsApp personal assistant for Senior Seminar II.  
Google Calendar / Gmail through APIs, plus a screenshot browser agent for `screen:` tasks.

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

Google API token broken (`invalid_grant`):

```bash
rm token.json
python -c "from app.calendar import get_credentials; get_credentials()"
```

Screen login missing:

```bash
python -m app.browser_login
```

- Health: http://127.0.0.1:8000/health  
- Dashboard: http://127.0.0.1:8000/dashboard (live screenshots + Runs comparison)  
- Webhook: `https://<ngrok-host>/webhook/whatsapp`

## WhatsApp

| Message | Path |
|---------|------|
| `list` / `schedule ...` / `mail` | Google API |
| `screen: list` / `screen: schedule ...` | Calendar on screen |
| `screen: nashville forecast on weather.gov` | General web on screen |
| `stop` / `end` / `cancel` | Stop a long screen run |

Screen runs are headless by default (`SCREEN_HEADED=0`). Watch them on the dashboard. Runs are logged under `logs/runs.jsonl` and summarized on the Runs tab (API vs screen for calendar, plus web sites / failures).
