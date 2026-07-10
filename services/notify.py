"""Optional Slack notifications."""

from __future__ import annotations

import logging
import os
from typing import Iterable

from crawlers.base import Job

logger = logging.getLogger(__name__)


def notify_slack(jobs: Iterable[Job], webhook_url: str | None = None) -> bool:
    jobs = list(jobs)
    webhook_url = webhook_url or os.getenv("SLACK_WEBHOOK_URL", "")
    if not jobs or not webhook_url:
        return False
    lines = [f"*신규 AI/ML 채용공고 {len(jobs)}건*", ""]
    for job in jobs[:30]:
        title = job.title or job.position or "제목 없음"
        company = job.company or "회사 미상"
        lines.append(f"• <{job.url}|{company} — {title}> (점수 {job.score})")
    if len(jobs) > 30:
        lines.append(f"• 외 {len(jobs) - 30}건")
    try:
        import requests

        response = requests.post(webhook_url, json={"text": "\n".join(lines)}, timeout=15)
        response.raise_for_status()
        return True
    except Exception as exc:
        logger.exception("Slack notification failed: %s", exc)
        return False
