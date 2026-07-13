"""Static data export used by the GitHub Pages dashboard."""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Iterable, Mapping

from crawlers.base import Job
from services.google_sheets import now_iso


def _as_mapping(job: Job | Mapping[str, Any]) -> Mapping[str, Any]:
    return job if isinstance(job, Mapping) else job.to_dict()


def export_site_data(
    jobs: Iterable[Job | Mapping[str, Any]], path: str | Path, summary: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    """Write dashboard data and retain notes/statuses from a prior export."""

    destination = Path(path)
    previous: dict[str, Mapping[str, Any]] = {}
    if destination.exists():
        try:
            saved = json.loads(destination.read_text(encoding="utf-8"))
            previous = {
                str(row.get("job_key")): row
                for row in saved.get("jobs", [])
                if isinstance(row, Mapping) and row.get("job_key")
            }
        except (OSError, json.JSONDecodeError):
            previous = {}

    exported_jobs: list[dict[str, Any]] = []
    for job in jobs:
        row = dict(_as_mapping(job))
        old = previous.get(str(row.get("job_key", "")), {})
        row["status"] = old.get("status", "신규")
        row["memo"] = old.get("memo", "")
        row["first_seen_at"] = old.get("first_seen_at", row.get("collected_at", now_iso()))
        exported_jobs.append(row)

    exported_jobs.sort(key=lambda item: (item.get("deadline") or "9999", item.get("company") or ""))
    payload = {
        "generated_at": now_iso(),
        "summary": dict(summary or {}),
        "jobs": exported_jobs,
    }
    destination.parent.mkdir(parents=True, exist_ok=True)
    destination.write_text(json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return payload
