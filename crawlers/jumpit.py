"""Jumpit developer-job crawler.

The positions page is a client-rendered Next.js app whose cards come from the
public, unauthenticated JSON API at ``jumpit-api.saramin.co.kr`` — the same
endpoint any visitor's browser calls.  Reading it directly returns the records
the public page displays, including ``newcomer``/``minCareer``/``closedAt``
fields the rendered HTML never exposes, and avoids launching a browser.
robots.txt on the site host allows ``/position/*``; the rate limiting and
bounded retries from ``BaseCrawler`` apply to every API call.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping

from .base import BaseCrawler, Job, clean_text

logger = logging.getLogger(__name__)

# Even with highlight=false the API wraps matched keywords in <span> tags.
_HTML_TAG = re.compile(r"<[^>]+>")


def _strip_tags(value: Any) -> str:
    # Highlight spans wrap keywords inline, so drop tags without adding spaces.
    return clean_text(_HTML_TAG.sub("", str(value))) if value is not None else ""

API_URL = "https://jumpit-api.saramin.co.kr/api/positions"
DETAIL_API_URL = "https://jumpit-api.saramin.co.kr/api/position/{id}"
POSITION_URL = "https://jumpit.saramin.co.kr/position/{id}"


class JumpitCrawler(BaseCrawler):
    def __init__(self, settings: Mapping[str, Any] | None = None, session: Any = None) -> None:
        super().__init__("jumpit", settings, session)

    def collect(self) -> list[Job]:
        api_url = self.settings.get("api_url", API_URL)
        keywords = self.settings.get("keywords") or ["AI", "머신러닝", "LLM"]
        pages = max(1, int(self.settings.get("pages", 3)))
        newcomer_only = self.settings.get("newcomer_only", True) is not False
        jobs_by_id: dict[str, Job] = {}
        for keyword in keywords:
            for page in range(1, pages + 1):
                params = {
                    "integrated": "true",
                    "keyword": keyword,
                    "highlight": "false",
                    "sort": "recent",
                    "page": str(page),
                }
                if newcomer_only:
                    # career=0 is the site's own "신입" filter.
                    params["career"] = "0"
                try:
                    payload = self.request(api_url, params=params).json()
                except Exception as exc:
                    logger.exception("jumpit position search failed for %r page %d: %s", keyword, page, exc)
                    break
                positions = (payload.get("result") or {}).get("positions") or []
                if not positions:
                    break
                for item in positions:
                    job = self.position_to_job(item)
                    if job.source_job_id and job.source_job_id not in jobs_by_id:
                        jobs_by_id[job.source_job_id] = job

        # Listing cards omit education and the full requirements text; the
        # public detail API provides both for the shared filters.
        limit = int(self.settings.get("detail_fetch_limit", 60))
        jobs = list(jobs_by_id.values())
        for job in jobs[:limit]:
            detail_url = DETAIL_API_URL.format(id=job.source_job_id)
            try:
                payload = self.request(detail_url).json()
                self.merge_detail(job, payload.get("result") or {})
            except Exception as exc:
                logger.warning("jumpit detail fetch failed for %s: %s", job.url, exc)
        return jobs

    def position_to_job(self, item: Mapping[str, Any]) -> Job:
        position_id = clean_text(item.get("id"))
        title = _strip_tags(item.get("title"))
        category = _strip_tags(item.get("jobCategory"))
        tech_stacks = [clean_text(stack) for stack in item.get("techStacks") or []]
        locations = [clean_text(place) for place in item.get("locations") or []]
        min_career = clean_text(item.get("minCareer"))
        max_career = clean_text(item.get("maxCareer"))
        newcomer = bool(item.get("newcomer")) or min_career == "0"
        if newcomer:
            experience = "신입"
        elif min_career or max_career:
            experience = f"경력 {min_career}~{max_career}년"
        else:
            experience = ""
        deadline = "상시채용" if item.get("alwaysOpen") else clean_text(item.get("closedAt"))
        return self.make_job(
            source_job_id=position_id,
            company=_strip_tags(item.get("companyName")),
            title=title,
            position=category or title,
            location=", ".join(place for place in locations if place),
            url=POSITION_URL.format(id=position_id),
            deadline=deadline,
            experience=experience,
            raw_text=" ".join(part for part in [title, category, *tech_stacks] if part),
        )

    @staticmethod
    def merge_detail(job: Job, detail: Mapping[str, Any]) -> Job:
        """Fold the detail API's requirement text into the listing record."""

        extra = [
            clean_text(detail.get(key))
            for key in ("responsibility", "qualifications", "preferredRequirements", "educationName")
        ]
        job.raw_text = clean_text(" ".join(part for part in [job.raw_text, *extra] if part))
        location = clean_text(detail.get("location"))
        if location:
            job.location = location
        closed_at = clean_text(detail.get("closedAt"))
        if closed_at and job.deadline != "상시채용":
            job.deadline = closed_at
        return job
