from pathlib import Path
from uuid import uuid4

from app.browser import open_page

ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = ROOT / "screenshots"
CALENDAR_WEEK_URL = "https://calendar.google.com/calendar/u/0/r/week"


def capture_page_screenshot(url: str, prefix: str = "page") -> Path:
    SCREENSHOT_DIR.mkdir(exist_ok=True)
    path = SCREENSHOT_DIR / f"{prefix}-{uuid4().hex}.png"
    with open_page() as page:
        page.goto(url, wait_until="domcontentloaded")
        page.wait_for_timeout(3000)
        page.screenshot(path=str(path), full_page=True)
    return path


def capture_event_screenshot(event_url: str) -> Path:
    return capture_page_screenshot(event_url, "event")


def capture_calendar_screenshot() -> Path:
    return capture_page_screenshot(CALENDAR_WEEK_URL, "calendar")
