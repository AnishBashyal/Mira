"""Summarize logs/runs.jsonl for the dashboard."""

from __future__ import annotations

from collections import Counter
from pathlib import Path

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


def summarize_runs(limit: int = 200) -> dict:
    rows = [_enriched(r) for r in read_runs(limit)]
    if not rows:
        return {"n": 0, "by_mode": {}, "by_site": [], "failure_modes": [], "highlights": []}

    by_mode: dict[str, dict] = {}
    for row in rows:
        mode = row.get("mode") or "unknown"
        bucket = by_mode.setdefault(
            mode,
            {"n": 0, "ok": 0, "seconds": [], "depths": [], "scores": []},
        )
        bucket["n"] += 1
        if _ok(row):
            bucket["ok"] += 1
        if row.get("seconds") is not None:
            bucket["seconds"].append(float(row["seconds"]))
        depth = row.get("action_depth", row.get("steps"))
        if depth is not None:
            bucket["depths"].append(int(depth))
        bucket["scores"].append(float(row.get("success_score") or 0))

    mode_summary = {}
    for mode, bucket in by_mode.items():
        n = bucket["n"]
        mode_summary[mode] = {
            "n": n,
            "ok": bucket["ok"],
            "success_rate": round(bucket["ok"] / n, 2) if n else 0,
            "avg_seconds": round(sum(bucket["seconds"]) / len(bucket["seconds"]), 1)
            if bucket["seconds"]
            else None,
            "avg_depth": round(sum(bucket["depths"]) / len(bucket["depths"]), 1)
            if bucket["depths"]
            else None,
            "avg_success_score": round(sum(bucket["scores"]) / len(bucket["scores"]), 2)
            if bucket["scores"]
            else 0,
        }

    site_counter: Counter[str] = Counter()
    site_ok: Counter[str] = Counter()
    fail_reasons: Counter[str] = Counter()
    for row in rows:
        site = row.get("site") or (
            "calendar" if row.get("task") in {"list", "schedule"} else "other"
        )
        site_counter[site] += 1
        if _ok(row):
            site_ok[site] += 1
        if not _ok(row):
            detail = (row.get("detail") or row.get("error") or row.get("outcome") or "").lower()
            if "bot" in detail or "verification" in detail or "403" in detail or "forbidden" in detail:
                fail_reasons["bot_or_block"] += 1
            elif "focus" in detail or "text field" in detail or "non-interactive" in detail:
                fail_reasons["focus_or_input"] += 1
            elif "execution context" in detail or "navigation" in detail:
                fail_reasons["navigation_redirect"] += 1
            elif "timeout" in detail or row.get("outcome") == "timeout":
                fail_reasons["timeout_wander"] += 1
            else:
                fail_reasons["other"] += 1

    by_site = [
        {
            "site": site,
            "n": site_counter[site],
            "ok": site_ok[site],
            "success_rate": round(site_ok[site] / site_counter[site], 2),
        }
        for site in site_counter
    ]
    by_site.sort(key=lambda item: (-item["n"], item["site"]))

    highlights = [
        "Calendar screen is compared with API list/schedule. API is fast; screen schedule often times out.",
        "Screen web is for general sites (no special API).",
        "Direct pages (Wikipedia) and weather.gov can work. Search engines and some media sites block the agent.",
        "College portals redirect into login mid-run. Skip those without a saved browser session.",
    ]

    return {
        "n": len(rows),
        "by_mode": mode_summary,
        "by_site": by_site,
        "failure_modes": [
            {"mode": name, "n": count} for name, count in fail_reasons.most_common()
        ],
        "highlights": highlights,
    }
