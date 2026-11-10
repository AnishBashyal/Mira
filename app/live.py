"""Thread-safe live feed for the screen view page."""

import queue
import threading
from typing import Any

_lock = threading.Lock()
_subscribers: list[queue.Queue] = []
_latest: dict[str, Any] | None = None


def publish(event: dict[str, Any]) -> None:
    global _latest
    with _lock:
        _latest = event
        dead: list[queue.Queue] = []
        for sub in _subscribers:
            try:
                sub.put_nowait(event)
            except queue.Full:
                dead.append(sub)
        for sub in dead:
            _subscribers.remove(sub)


def latest() -> dict[str, Any] | None:
    with _lock:
        return dict(_latest) if _latest else None


def subscribe() -> queue.Queue:
    sub: queue.Queue = queue.Queue(maxsize=64)
    with _lock:
        _subscribers.append(sub)
        if _latest is not None:
            try:
                sub.put_nowait(_latest)
            except queue.Full:
                pass
    return sub


def unsubscribe(sub: queue.Queue) -> None:
    with _lock:
        if sub in _subscribers:
            _subscribers.remove(sub)
