from contextlib import contextmanager
from pathlib import Path

from playwright.sync_api import sync_playwright

from app.config import SCREEN_HEADED

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "browser_state.json"


@contextmanager
def open_page(viewport: dict | None = None):
    if not STATE_FILE.exists():
        raise FileNotFoundError("Run python -m app.browser_login first.")

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            channel="chrome",
            headless=not SCREEN_HEADED,
            slow_mo=200 if SCREEN_HEADED else 0,
        )
        options = {"storage_state": str(STATE_FILE)}
        if viewport:
            options["viewport"] = viewport
        context = browser.new_context(**options)
        page = context.new_page()
        try:
            yield page
        finally:
            context.close()
            browser.close()
