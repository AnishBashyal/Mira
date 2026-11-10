"""Score a run from the task + what actually happened."""


def score_run(
    *,
    task: str,
    outcome: str,
    steps: int = 0,
    actions: list | None = None,
    task_class: str = "",
) -> dict:
    actions = actions or []
    kind = (task_class or task or "other").lower()

    difficulty = {
        "list": 2,
        "mail": 2,
        "schedule": 5,
        "search": 2,
        "read": 2,
        "form": 4,
        "portal": 5,
        "web": 3,
        "other": 3,
    }.get(kind, 3)

    if steps >= 12:
        difficulty = min(5, difficulty + 1)

    if outcome in {"done", "ok"}:
        success = 1.0
    elif outcome == "timeout" and "type" in actions:
        success = 0.5
    elif outcome == "timeout" and steps >= 6:
        success = 0.35
    elif outcome == "fail":
        success = 0.0
    else:
        success = 0.0

    return {
        "difficulty": difficulty,
        "action_depth": int(steps or 0),
        "success_score": success,
        "task_class": kind,
    }
