"""Summarize logs/runs.jsonl for the dashboard."""

from __future__ import annotations

from collections import Counter

from app.runs import read_runs
from app.score import score_run


def _enriched(row: dict) -> dict:
    if "success_score" in row and "difficulty" in row:
        return row
    scores = score_run(
        task=str(row.get("task") or ""),
        outcome=str(row.get("outcome") or ""),
        steps=int(row.get("steps") or 0),
        actions=row.get("actions") or [],
        task_class=str(row.get("task_class") or ""),
    )
    return {**row, **scores}


def _ok(row: dict) -> bool:
    return row.get("outcome") in {"ok", "done"} or float(row.get("success_score") or 0) >= 1.0


def _site_for(row: dict) -> str:
    if row.get("site"):
        return str(row["site"])
    if row.get("task") in {"list", "schedule", "mail"}:
        return "calendar" if row.get("task") != "mail" else "gmail"
    return "other"


def _bucket_stats(rows: list[dict]) -> dict:
    n = len(rows)
    if not n:
        return {
            "n": 0,
            "ok": 0,
            "success_rate": 0,
            "avg_seconds": None,
            "avg_depth": None,
            "avg_success_score": 0,
        }
    ok = sum(1 for row in rows if _ok(row))
    seconds = [float(row["seconds"]) for row in rows if row.get("seconds") is not None]
    depths = [
        int(row.get("action_depth", row.get("steps") or 0))
        for row in rows
        if row.get("action_depth") is not None or row.get("steps") is not None
    ]
    scores = [float(row.get("success_score") or 0) for row in rows]
    return {
        "n": n,
        "ok": ok,
        "success_rate": round(ok / n, 2),
        "avg_seconds": round(sum(seconds) / len(seconds), 1) if seconds else None,
        "avg_depth": round(sum(depths) / len(depths), 1) if depths else None,
        "avg_success_score": round(sum(scores) / len(scores), 2) if scores else 0,
    }


def _fail_mode(row: dict) -> str:
    detail = (row.get("detail") or row.get("error") or row.get("outcome") or "").lower()
    if "bot" in detail or "verification" in detail or "403" in detail or "forbidden" in detail:
        return "bot_or_block"
    if "focus" in detail or "text field" in detail or "non-interactive" in detail:
        return "focus_or_input"
    if "execution context" in detail or "navigation" in detail:
        return "navigation_redirect"
    if "timeout" in detail or row.get("outcome") == "timeout":
        return "timeout_wander"
    return "other"


def summarize_runs(limit: int = 200) -> dict:
    rows = [_enriched(r) for r in read_runs(limit)]
    if not rows:
        return {
            "n": 0,
            "by_mode": {},
            "by_site": [],
            "calendar_compare": [],
            "web_summary": {},
            "failure_modes": [],
            "highlights": [],
        }

    by_mode_rows: dict[str, list[dict]] = {}
    for row in rows:
        by_mode_rows.setdefault(row.get("mode") or "unknown", []).append(row)
    mode_summary = {mode: _bucket_stats(group) for mode, group in by_mode_rows.items()}

    site_rows: dict[str, list[dict]] = {}
    for row in rows:
        site_rows.setdefault(_site_for(row), []).append(row)
    by_site = [
        {"site": site, **_bucket_stats(group)}
        for site, group in site_rows.items()
    ]
    by_site.sort(key=lambda item: (-item["n"], item["site"]))

    # Side-by-side Calendar: list + schedule for api vs screen
    calendar_compare = []
    for task in ("list", "schedule"):
        row = {"task": task}
        for mode in ("api", "screen"):
            group = [
                r for r in rows
                if r.get("mode") == mode and r.get("task") == task
            ]
            row[mode] = _bucket_stats(group)
        calendar_compare.append(row)

    web_only = [r for r in rows if r.get("task") == "web"]
    web_summary = _bucket_stats(web_only)

    fail_reasons: Counter[str] = Counter()
    for row in rows:
        if not _ok(row):
            fail_reasons[_fail_mode(row)] += 1
    fail_total = sum(fail_reasons.values()) or 1
    failure_modes = [
        {
            "mode": name,
            "n": count,
            "pct": round(100 * count / fail_total),
        }
        for name, count in fail_reasons.most_common()
    ]

    api = mode_summary.get("api", {})
    screen = mode_summary.get("screen", {})
    list_api = next((c["api"] for c in calendar_compare if c["task"] == "list"), {})
    list_screen = next((c["screen"] for c in calendar_compare if c["task"] == "list"), {})
    sched_api = next((c["api"] for c in calendar_compare if c["task"] == "schedule"), {})
    sched_screen = next((c["screen"] for c in calendar_compare if c["task"] == "schedule"), {})

    # Site-class split for web conclusions
    web_rows = [r for r in rows if r.get("task") == "web"]
    easy_sites = {"en.wikipedia.org", "www.weather.gov"}
    hard_markers = ("google.", "duckduckgo.", "imdb.", "ellucian", "colleague")
    easy = [r for r in web_rows if _site_for(r) in easy_sites]
    hard = [
        r for r in web_rows
        if any(m in _site_for(r) for m in hard_markers)
    ]
    easy_stats = _bucket_stats(easy)
    hard_stats = _bucket_stats(hard)

    highlights = []
    if api.get("n"):
        highlights.append(
            f"API path is reliable for everyday use: {api.get('ok', 0)}/{api.get('n', 0)} ok "
            f"(avg {api.get('avg_seconds') or '–'}s)."
        )
    if list_api.get("n") or list_screen.get("n"):
        highlights.append(
            f"Calendar list works both ways, but screen is slower "
            f"(API ~{list_api.get('avg_seconds') or '–'}s vs screen ~{list_screen.get('avg_seconds') or '–'}s)."
        )
    if sched_api.get("n") or sched_screen.get("n"):
        highlights.append(
            f"Calendar create is the clear split: API {sched_api.get('ok', 0)}/{sched_api.get('n', 0)} "
            f"(~{sched_api.get('avg_seconds') or '–'}s); "
            f"screen {sched_screen.get('ok', 0)}/{sched_screen.get('n', 0)} "
            f"(~{sched_screen.get('avg_seconds') or '–'}s). Dense forms still beat pixel clicks."
        )
    if easy_stats.get("n") or hard_stats.get("n"):
        highlights.append(
            f"Screen web: public pages like Wikipedia/weather.gov "
            f"{easy_stats.get('ok', 0)}/{easy_stats.get('n', 0)} ok; "
            f"search engines / blocked / login sites "
            f"{hard_stats.get('ok', 0)}/{hard_stats.get('n', 0)} ok."
        )
    if screen.get("n") and api.get("n"):
        highlights.append(
            f"Overall screen success stays lower and slower "
            f"({screen.get('ok', 0)}/{screen.get('n', 0)}, avg {screen.get('avg_seconds') or '–'}s) "
            f"than API — use screen for research demos, API when it must work."
        )
    if failure_modes:
        top = ", ".join(f"{f['mode']} ({f['n']})" for f in failure_modes[:3])
        highlights.append(f"Main failure modes: {top}.")

    return {
        "n": len(rows),
        "by_mode": mode_summary,
        "by_site": by_site,
        "calendar_compare": calendar_compare,
        "web_summary": web_summary,
        "failure_modes": failure_modes,
        "highlights": highlights,
    }
