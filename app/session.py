"""Short-lived WhatsApp clarification state. Max a couple of follow-ups."""

from __future__ import annotations

from dataclasses import dataclass, field

MAX_ASKS = 2


@dataclass
class Pending:
    action: str
    mode: str
    title: str = ""
    when: str = ""
    goal: str = ""
    url: str = ""
    task_class: str = ""
    asks: int = 0
    notes: list[str] = field(default_factory=list)


_pending: dict[str, Pending] = {}


def get_pending(user: str) -> Pending | None:
    return _pending.get(user)


def clear_pending(user: str) -> None:
    _pending.pop(user, None)


def set_pending(user: str, pending: Pending) -> None:
    _pending[user] = pending


def missing_schedule_slots(title: str, when: str) -> list[str]:
    missing = []
    if not title.strip():
        missing.append("title")
    if not when.strip():
        missing.append("when")
    return missing


def schedule_followup(missing: list[str]) -> str:
    if missing == ["title", "when"]:
        return "What should I call it, and what day/time?"
    if missing == ["title"]:
        return "What should I call the event?"
    if missing == ["when"]:
        return "What day and time?"
    return "Need a title and a day/time."


def extract_url(text: str) -> str:
    for part in text.replace("\n", " ").split():
        token = part.strip("<>()[],.\"'")
        if token.startswith("http://") or token.startswith("https://"):
            return token
    return ""
