from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent
STATE_FILE = ROOT / "browser_state.json"
PROFILE_DIR = ROOT / "browser_profile"


def main():
    PROFILE_DIR.mkdir(exist_ok=True)
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            user_data_dir=str(PROFILE_DIR),
            channel="chrome",
            headless=False,
            args=["--disable-blink-features=AutomationControlled"],
        )
        page = context.pages[0] if context.pages else context.new_page()
        page.goto("https://calendar.google.com")
        print("Log in as anishdbashyal@gmail.com in the Chrome window.")
        print("When your calendar is fully visible, come back here and press Enter.")
        input()
        context.storage_state(path=str(STATE_FILE))
        context.close()
    print(f"Saved login to {STATE_FILE}")


if __name__ == "__main__":
    main()
