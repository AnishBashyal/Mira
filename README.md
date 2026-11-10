# Mira

My personal WhatsApp assistant. Terminal 1 runs the server. Terminal 2 makes it reachable.

## Bootup (after closing laptop)

1. WhatsApp: send `join design-news` to the Twilio sandbox number.
2. Terminal 1:

```bash
cd "/Users/anishbashyal/Desktop/Senior Seminar II"
source .venv/bin/activate
uvicorn app.main:app --reload --port 8000
```

3. Terminal 2:

```bash
ngrok http 8000
```

4. Screen path (browser): only if `browser_state.json` is missing or screen login fails:

```bash
source .venv/bin/activate
python -m app.browser_login
```

5. Google API (Calendar/Gmail) — if WhatsApp list/schedule/mail fails with `invalid_grant` / token expired:

```bash
source .venv/bin/activate
rm token.json
python -c "from app.calendar import get_credentials; get_credentials()"
```

Sign in in the browser, then retry the WhatsApp message.

Health check: http://127.0.0.1:8000/health

Webhook (if ngrok host changed): `https://<ngrok-host>/webhook/whatsapp` (HTTP POST). Stable host is usually `https://viral-waged-helmet.ngrok-free.dev/webhook/whatsapp`.

From WhatsApp: `list`, `schedule <title>`, `mail`, or `screen: ...`.

## Demo: API vs screen

I keep screen runs **headless** by default (`SCREEN_HEADED=0`) so typing focus is steadier; I watch live shots on my dashboard instead. Set `SCREEN_HEADED=1` only if I want a visible Chrome window.

1. Open http://127.0.0.1:8000/dashboard
2. Same task without `screen:` (API) — fast WhatsApp reply.
3. Same task with `screen:` — I show screenshots, actions, and a timer on the dashboard.
4. I append comparison rows to `logs/runs.jsonl` (also under **My runs** on the dashboard).

### Stuff I gather for the report

Paired calendar (API then screen, same wording) — a few of each:

- `list` / `screen: list`
- `schedule Costco Friday 9pm` / `screen: schedule Costco Friday 9pm`

Natural screen web (I pick the start URL when I can):

```text
screen: nashville forecast on weather.gov
```

Private sites (I ask for the link once):

```text
screen: show my Fall 2026 grades on my college portal
```

I score each run in `logs/runs.jsonl` (`difficulty`, `action_depth`, `success_score`).
