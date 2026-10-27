import json
from datetime import datetime
from pathlib import Path
from uuid import uuid4
from zoneinfo import ZoneInfo

from google import genai
from google.genai import types
from playwright.sync_api import sync_playwright

from app.config import GEMINI_API_KEY

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "browser_state.json"
SCREENSHOT_DIR = ROOT / "screenshots"
CALENDAR_URL = "https://calendar.google.com/calendar/u/0/r/week"
VIEWPORT = {"width": 1280, "height": 800}
MAX_STEPS = 10

UI_PROMPT = """
You control a web page using screenshots only.
Return only JSON with keys:
- action: one of click, type, press, scroll, wait, done, fail
- x: click x in pixels from the top-left of the screenshot (0 if unused)
- y: click y in pixels from the top-left of the screenshot (0 if unused)
- text: text to type for action=type, else empty string
- key: key name for action=press (examples: Enter, Tab, Escape), else empty string
- reason: short reason
Rules:
- Use only what is visible in the screenshot.
- Do not assume site-specific shortcuts unless they are shown on screen.
- Take the smallest useful next step toward the goal.
- done only when the goal is clearly finished.
- fail if you are stuck or the page blocks progress.
Screenshot size is 1280x800.
""".strip()


def _decide(path: Path, title: str, when: str, history: list[str]) -> dict:
    client = genai.Client(api_key=GEMINI_API_KEY)
    uploaded = client.files.upload(file=str(path))
    history_text = "\n".join(history) if history else "(none)"
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=[
            uploaded,
            (
                f"Goal: create an event titled {title} starting at {when}.\n"
                f"Steps so far:\n{history_text}\n"
                "Choose the next single action."
            ),
        ],
        config=types.GenerateContentConfig(
            system_instruction=UI_PROMPT,
            response_mime_type="application/json",
        ),
    )
    data = json.loads(response.text)
    action = data.get("action", "fail")
    if action not in {"click", "type", "press", "scroll", "wait", "done", "fail"}:
        action = "fail"
    return {
        "action": action,
        "x": int(data.get("x") or 0),
        "y": int(data.get("y") or 0),
        "text": (data.get("text") or ""),
        "key": (data.get("key") or ""),
        "reason": (data.get("reason") or ""),
    }


def _shot(page, prefix: str) -> Path:
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    path = SCREENSHOT_DIR / f"{prefix}-{uuid4().hex}.png"
    page.screenshot(path=str(path), full_page=False)
    return path


def create_event_by_screen(title: str, when: str = "") -> tuple[str, Path]:
    if not STATE_FILE.exists():
        raise FileNotFoundError("Run python -m app.browser_login first.")

    if not when:
        tz = ZoneInfo("America/Chicago")
        when = (datetime.now(tz).replace(hour=15, minute=0, second=0, microsecond=0)).isoformat()

    history: list[str] = []
    final_path: Path | None = None

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(
            storage_state=str(STATE_FILE),
            viewport=VIEWPORT,
        )
        page = context.new_page()
        page.goto(CALENDAR_URL, wait_until="domcontentloaded")
        page.wait_for_timeout(2500)

        for step in range(1, MAX_STEPS + 1):
            shot = _shot(page, f"ui-step{step}")
            decision = _decide(shot, title, when, history)
            print(f"UI step {step}: {decision}")
            history.append(f"{step}. {decision['action']} {decision['reason']}")

            action = decision["action"]
            if action == "done":
                final_path = _shot(page, "ui-done")
                context.close()
                browser.close()
                return f"Created on screen: {title} at {when}", final_path
            if action == "fail":
                final_path = shot
                context.close()
                browser.close()
                return f"Screen schedule failed: {decision['reason'] or 'stuck'}", final_path
            if action == "click":
                page.mouse.click(decision["x"], decision["y"])
            elif action == "type":
                page.keyboard.type(decision["text"], delay=40)
            elif action == "press":
                page.keyboard.press(decision["key"] or "Enter")
            elif action == "scroll":
                page.mouse.wheel(0, 600)
            elif action == "wait":
                page.wait_for_timeout(1500)
            page.wait_for_timeout(1200)

        final_path = _shot(page, "ui-timeout")
        context.close()
        browser.close()
        return "Screen schedule stopped after max steps.", final_path
