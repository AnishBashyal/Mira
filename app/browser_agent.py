import hashlib
import json
import time
from pathlib import Path
from uuid import uuid4

from google import genai
from google.genai import types

from app.browser import open_page
from app.config import GEMINI_API_KEY
from app.live import publish

ROOT = Path(__file__).resolve().parent.parent
SCREENSHOT_DIR = ROOT / "screenshots"
VIEWPORT = {"width": 1280, "height": 800}
MAX_STEPS = 16
REPEAT_LIMIT = 3
CYCLE_LEN = 3
CLICK_GRID = 40

CLICK_FOCUS_OFFSETS = (
    (0, 0),
    (0, -10),
    (0, 10),
    (-14, 0),
    (14, 0),
    (0, -20),
    (0, 20),
    (-28, 0),
    (28, 0),
)

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
- To type, first click near the center of a visible text field.
- If history says a click missed the text field, click a clearly different spot inside the field.
- If history says typing was skipped for no focus, click the field again before typing.
- Do not repeat the same click or action if it already failed.
- done only when the goal is clearly finished because of actions in this run.
- fail if you are stuck or the page blocks progress.
Screenshot size is 1280x800.
""".strip()


def _click_in_bounds(x: int, y: int) -> bool:
    return 0 <= x < VIEWPORT["width"] and 0 <= y < VIEWPORT["height"]


def _shot_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _safe_evaluate(page, script: str, arg=None):
    """Evaluate JS; retry once if the page navigated mid-call (SSO/redirects)."""
    try:
        return page.evaluate(script) if arg is None else page.evaluate(script, arg)
    except Exception as error:
        message = str(error)
        if "Execution context was destroyed" not in message and "navigation" not in message.lower():
            raise
        try:
            page.wait_for_load_state("domcontentloaded", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(400)
        return page.evaluate(script) if arg is None else page.evaluate(script, arg)


def _editable_focused(page) -> bool:
    return bool(
        _safe_evaluate(
            page,
            """() => {
              const el = document.activeElement;
              if (!el) return false;
              const tag = (el.tagName || '').toLowerCase();
              if (tag === 'textarea') return true;
              if (tag === 'input') {
                const type = (el.type || 'text').toLowerCase();
                return !['button','submit','checkbox','radio','file','hidden','image','reset'].includes(type);
              }
              if (el.isContentEditable) return true;
              const role = (el.getAttribute('role') || '').toLowerCase();
              return role === 'textbox' || role === 'searchbox' || role === 'combobox';
            }""",
        )
    )


def _focus_editable_near(page, x: int, y: int) -> bool:
    """Vision picks (x,y); resolve nearest real editable via elementFromPoint (site-agnostic)."""
    return bool(
        _safe_evaluate(
            page,
            """([x, y]) => {
              const isEditable = (el) => {
                if (!el || el.disabled) return false;
                const tag = (el.tagName || '').toLowerCase();
                if (tag === 'textarea') return true;
                if (tag === 'input') {
                  const type = (el.type || 'text').toLowerCase();
                  return !['button','submit','checkbox','radio','file','hidden','image','reset'].includes(type);
                }
                if (el.isContentEditable) return true;
                const role = (el.getAttribute('role') || '').toLowerCase();
                return ['textbox','searchbox','combobox'].includes(role);
              };
              const climb = (el) => {
                let cur = el;
                while (cur) {
                  if (isEditable(cur)) return cur;
                  cur = cur.parentElement;
                }
                return null;
              };
              const tryPoint = (px, py) => climb(document.elementFromPoint(px, py));
              let hit = null;
              for (let r = 0; r <= 48 && !hit; r += 8) {
                for (let dx = -r; dx <= r && !hit; dx += 8) {
                  for (let dy = -r; dy <= r && !hit; dy += 8) {
                    if (r !== 0 && Math.max(Math.abs(dx), Math.abs(dy)) !== r) continue;
                    hit = tryPoint(x + dx, y + dy);
                  }
                }
              }
              if (!hit) return false;
              hit.scrollIntoView({block: 'center', inline: 'center'});
              hit.focus({preventScroll: true});
              hit.click();
              return document.activeElement === hit || isEditable(document.activeElement);
            }""",
            [x, y],
        )
    )


def _click_for_focus(page, x: int, y: int) -> bool:
    """Prefer DOM-resolved editable near (x,y); fall back to mouse offsets."""
    if _focus_editable_near(page, x, y):
        print(f"Focused editable near ({x}, {y}) via elementFromPoint")
        return True
    for dx, dy in CLICK_FOCUS_OFFSETS:
        cx, cy = x + dx, y + dy
        if not _click_in_bounds(cx, cy):
            continue
        page.mouse.click(cx, cy)
        page.wait_for_timeout(180)
        if _editable_focused(page):
            if dx or dy:
                print(f"Focused editable via offset ({dx}, {dy}) from ({x}, {y})")
            return True
    return False


def _type_into_focused(page, text: str) -> bool:
    """Type into the focused field; verify text landed (keyboard + value fallback)."""
    if not _editable_focused(page):
        return False
    page.keyboard.type(text, delay=25)
    page.wait_for_timeout(200)
    ok = bool(
        _safe_evaluate(
            page,
            """(sample) => {
              const el = document.activeElement;
              if (!el) return false;
              const value = (el.value != null ? el.value : (el.textContent || ''));
              return value.includes(sample);
            }""",
            text[: min(12, len(text))],
        )
    )
    if ok:
        return True
    # Some sites ignore synthetic key events — set value and fire input events.
    ok = bool(
        _safe_evaluate(
            page,
            """(full) => {
              const el = document.activeElement;
              if (!el) return false;
              el.focus();
              if ('value' in el) {
                const proto = Object.getOwnPropertyDescriptor(
                  el.tagName === 'TEXTAREA'
                    ? HTMLTextAreaElement.prototype
                    : HTMLInputElement.prototype,
                  'value'
                );
                if (proto && proto.set) proto.set.call(el, full);
                else el.value = full;
                el.dispatchEvent(new Event('input', { bubbles: true }));
                el.dispatchEvent(new Event('change', { bubbles: true }));
                return (el.value || '').includes(full.slice(0, Math.min(12, full.length)));
              }
              el.textContent = full;
              el.dispatchEvent(new InputEvent('input', { bubbles: true, data: full }));
              return (el.textContent || '').includes(full.slice(0, Math.min(12, full.length)));
            }""",
            text,
        )
    )
    if ok:
        print("Typed via value/input events after keyboard type failed")
    return ok


def _action_signature(decision: dict) -> str:
    action = decision["action"]
    if action == "click":
        x = (decision["x"] // CLICK_GRID) * CLICK_GRID
        y = (decision["y"] // CLICK_GRID) * CLICK_GRID
        return f"click@{x},{y}"
    if action == "type":
        return f"type:{decision['text'][:40]}"
    if action == "press":
        return f"press:{decision['key'] or 'Enter'}"
    return action


def _in_cycle(signatures: list[str]) -> bool:
    need = CYCLE_LEN * 2
    if len(signatures) < need:
        return False
    return signatures[-need:-CYCLE_LEN] == signatures[-CYCLE_LEN:]


def _decide(path: Path, goal: str, history: list[str], progress: str) -> dict:
    client = genai.Client(api_key=GEMINI_API_KEY)
    uploaded = client.files.upload(file=str(path))
    history_text = "\n".join(history) if history else "(none)"
    progress_line = f"\n{progress}\n" if progress else "\n"
    response = client.models.generate_content(
        model="gemini-3.8-flash",
        contents=[
            uploaded,
            (
                f"Goal: {goal}\n"
                f"Steps so far:\n{history_text}"
                f"{progress_line}"
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


def _elapsed(started: float) -> float:
    return round(time.perf_counter() - started, 2)


def _shot_url(path: Path) -> str:
    return f"/screenshots/{path.name}"


def _emit_step(step: int, decision: dict, shot: Path, started: float) -> None:
    publish(
        {
            "type": "step",
            "step": step,
            "action": decision.get("action"),
            "reason": decision.get("reason"),
            "x": decision.get("x"),
            "y": decision.get("y"),
            "text": decision.get("text"),
            "screenshot_url": _shot_url(shot),
            "elapsed": _elapsed(started),
        }
    )


def _result(message: str, path: Path, outcome: str, steps: int, started: float, actions: list) -> dict:
    payload = {
        "message": message,
        "screenshot": path,
        "outcome": outcome,
        "steps": steps,
        "seconds": _elapsed(started),
        "actions": actions,
    }
    publish(
        {
            "type": "run_end",
            "outcome": outcome,
            "message": message,
            "steps": steps,
            "seconds": payload["seconds"],
            "screenshot_url": _shot_url(path),
            "actions": actions,
        }
    )
    return payload


def run_ui_goal(url: str, goal: str, cancel=None) -> dict:
    """Open url, chase goal by screenshot actions. Site-agnostic."""
    from app.cancel import cancelled

    history: list[str] = []
    signatures: list[str] = []
    actions: list[str] = []
    prev_digest: str | None = None
    last_action = ""
    last_click: tuple[int, int] | None = None
    started = time.perf_counter()
    step = 0

    publish(
        {
            "type": "run_start",
            "goal": goal,
            "url": url,
            "started_at": time.strftime("%Y-%m-%dT%H:%M:%S"),
        }
    )

    with open_page(VIEWPORT) as page:
        page.goto(url, wait_until="domcontentloaded")
        try:
            page.wait_for_load_state("networkidle", timeout=8000)
        except Exception:
            pass
        page.wait_for_timeout(800)
        # Clear transient overlays that steal focus without being site-specific.
        page.keyboard.press("Escape")
        page.wait_for_timeout(200)

        for step in range(1, MAX_STEPS + 1):
            if cancelled(cancel):
                shot = _shot(page, "ui-cancelled")
                print("Screen run cancelled by user")
                return _result("Stopped by user.", shot, "cancelled", step - 1, started, actions)

            shot = _shot(page, f"ui-step{step}")
            digest = _shot_digest(shot)
            progress = ""
            # Focus changes often do not change pixels — only treat type/press/scroll
            # "no effect" as strong evidence of failure.
            if (
                prev_digest is not None
                and digest == prev_digest
                and last_action in {"type", "press", "scroll"}
            ):
                progress = (
                    "SYSTEM: previous action had no visible effect; "
                    "try a different control."
                )
                print("No visible effect from previous action")
            prev_digest = digest

            decision = _decide(shot, goal, history, progress)
            print(f"UI step {step}: {decision}")
            action = decision["action"]
            actions.append(action)
            _emit_step(step, decision, shot, started)

            if action == "done":
                final_path = _shot(page, "ui-done")
                return _result(f"Done: {goal}", final_path, "done", step, started, actions)
            if action == "fail":
                return _result(
                    f"Failed: {decision['reason'] or 'stuck'}",
                    shot,
                    "fail",
                    step,
                    started,
                    actions,
                )

            signature = _action_signature(decision)
            same_count = 1
            for previous in reversed(signatures):
                if previous != signature:
                    break
                same_count += 1
            signatures.append(signature)

            if same_count >= REPEAT_LIMIT:
                print(f"Stuck on repeated action: {signature}")
                return _result(
                    f"Failed: repeated the same action ({signature}).",
                    shot,
                    "fail",
                    step,
                    started,
                    actions,
                )

            if _in_cycle(signatures):
                print(f"Stuck in action cycle: {signatures[-CYCLE_LEN:]}")
                return _result(
                    "Failed: stuck repeating the same action sequence.",
                    shot,
                    "fail",
                    step,
                    started,
                    actions,
                )

            note = decision["reason"]
            if same_count >= 2:
                note = f"{note} (repeated {signature}; try a different action)"

            if action == "click" and not _click_in_bounds(decision["x"], decision["y"]):
                print(
                    f"Skipped out-of-bounds click: "
                    f"({decision['x']}, {decision['y']})"
                )
                history.append(
                    f"{step}. click skipped — ({decision['x']}, {decision['y']}) "
                    f"outside {VIEWPORT['width']}x{VIEWPORT['height']}; "
                    "pick coordinates inside the screenshot"
                )
                last_action = "click"
                page.wait_for_timeout(400)
                continue

            if action == "click":
                x, y = decision["x"], decision["y"]
                last_click = (x, y)
                focused = _click_for_focus(page, x, y)
                if focused:
                    history.append(f"{step}. click {note} (text field focused)")
                else:
                    history.append(
                        f"{step}. click {note} "
                        "(no text field focused — click nearer the field center)"
                    )
                    print(f"Click missed editable focus at ({x}, {y})")
                last_action = "click"
                page.wait_for_timeout(500)
                continue

            if action == "type":
                if not _editable_focused(page) and last_click is not None:
                    _click_for_focus(page, last_click[0], last_click[1])
                if not _editable_focused(page):
                    history.append(
                        f"{step}. type skipped — no text field focused; "
                        "click inside an input first"
                    )
                    print("Type skipped: no editable focused")
                    last_action = "type"
                    page.wait_for_timeout(400)
                    continue
                typed = _type_into_focused(page, decision["text"])
                if typed:
                    history.append(f"{step}. type {note}")
                    print(f"Typed OK: {decision['text'][:40]!r}")
                else:
                    history.append(
                        f"{step}. type failed — text did not appear in the field; "
                        "click the field again"
                    )
                    print(f"Type failed to land: {decision['text'][:40]!r}")
                last_action = "type"
                page.wait_for_timeout(800)
                continue

            history.append(f"{step}. {action} {note}")
            if action == "press":
                page.keyboard.press(decision["key"] or "Enter")
            elif action == "scroll":
                page.mouse.wheel(0, 600)
            elif action == "wait":
                page.wait_for_timeout(1500)
            last_action = action
            page.wait_for_timeout(1200)

        final_path = _shot(page, "ui-timeout")
        return _result("Stopped after max steps.", final_path, "timeout", step, started, actions)
