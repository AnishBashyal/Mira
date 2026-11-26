"""Cancel an in-flight screen run from WhatsApp."""

from __future__ import annotations

import re
import threading

_lock = threading.Lock()
_events: dict[str, threading.Event] = {}

STOP_WORDS = {"end", "stop", "cancel", "terminate", "quit", "abort", "kill"}


def is_stop_message(message: str) -> bool:
    cleaned = message.strip().lower().rstrip(".!")
    if cleaned.startswith("screen:"):
        cleaned = cleaned[7:].strip()
    if cleaned in STOP_WORDS:
        return True
    # short phrases like "please stop", "stop now", "cancel that"
    tokens = re.findall(r"[a-z]+", cleaned)
    if not tokens or len(tokens) > 4:
        return False
    return any(token in STOP_WORDS for token in tokens) and not any(
        token in {"schedule", "list", "mail", "search", "open", "show"} for token in tokens
    )


def begin_run(user: str) -> threading.Event:
    event = threading.Event()
    with _lock:
        old = _events.get(user)
        if old is not None:
            old.set()
        _events[user] = event
    return event


def request_cancel(user: str) -> bool:
    with _lock:
        event = _events.get(user)
    if event is None:
        return False
    event.set()
    return True


def clear_run(user: str) -> None:
    with _lock:
        _events.pop(user, None)


def cancelled(event: threading.Event | None) -> bool:
    return bool(event is not None and event.is_set())


def has_active_run(user: str) -> bool:
    with _lock:
        event = _events.get(user)
    return event is not None and not event.is_set()
