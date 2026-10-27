from pathlib import Path
from uuid import uuid4

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "browser_state.json"
SCREENSHOT_DIR = ROOT / "screenshots"


def _capture(url: str, prefix: str) -> Path:
    if not STATE_FILE.exists():
        raise FileNotFoundError("Run python -m app.browser_login first.")

    SCREENSHOT_DIR.mkdir(exist_ok=True)
    path = SCREENSHOT_DIR / f"{prefix}-{uuid4().hex}.png"

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(channel="chrome", headless=True)
        context = browser.new_context(storage_state=str(STATE_FILE))
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        page.screenshot(path=str(path), full_page=True)
        context.close()
        browser.close()

    return path


def capture_event_screenshot(event_url: str) -> Path:
    return _capture(event_url, "event")


def capture_calendar_screenshot() -> Path:
    return _capture("https://calendar.google.com/calendar/u/0/r/week", "calendar")
