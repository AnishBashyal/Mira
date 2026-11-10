import json
from datetime import datetime, timezone
from pathlib import Path

from app.score import score_run

ROOT = Path(__file__).resolve().parent.parent
LOG_DIR = ROOT / "logs"
LOG_FILE = LOG_DIR / "runs.jsonl"


def log_run(**fields) -> None:
    """Append one run row and score it."""
    LOG_DIR.mkdir(exist_ok=True)
    scores = score_run(
        task=str(fields.get("task") or ""),
        outcome=str(fields.get("outcome") or ""),
        steps=int(fields.get("steps") or 0),
        actions=fields.get("actions") or [],
        task_class=str(fields.get("task_class") or ""),
    )
    row = {
        "time": datetime.now(timezone.utc).isoformat(),
        **fields,
        **scores,
    }
    with LOG_FILE.open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(row) + "\n")
    print(
        f"Run log: {row.get('mode')} {row.get('task')} → {row.get('outcome')} "
        f"({row.get('seconds')}s) score={row.get('success_score')} "
        f"diff={row.get('difficulty')} depth={row.get('action_depth')}"
    )


def read_runs(limit: int = 100) -> list[dict]:
    if not LOG_FILE.exists():
        return []
    rows: list[dict] = []
    for line in LOG_FILE.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows[-limit:]
