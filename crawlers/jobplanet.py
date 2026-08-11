"""JobPlanet job-search crawler.

The job board (``/job``) is a client-rendered app whose cards come from the
public, unauthenticated JSON API at ``/api/v3/job/search`` — the same endpoint
any visitor's browser calls.  robots.txt allows ``/job`` and ``/api`` paths
(only the HTML ``/search`` pages and account areas are disallowed), and the
API returns company, deadline, cities, employment type, and recruitment types
(신입/경력) directly, so no detail pages are fetched.

The site's CDN rejects requests whose User-Agent is not a browser, so the
crawler sends a regular browser User-Agent by default while keeping
robots.txt checks and per-host rate limiting on.  No login, CAPTCHA, or other
access control is involved.
"""

from __future__ import annotations

import logging
from typing import Any, Mapping
from urllib.parse import urljoin

from .base import BaseCrawler, Job, clean_text

logger = logging.getLogger(__name__)

API_URL = "https://www.jobplanet.co.kr/api/v3/job/search"
SITE_URL = "https://www.jobplanet.co.kr/"

_BROWSER_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/149.0.0.0 Safari/537.36"
    ),
    "Accept": "application/json",
    "Referer": "https://www.jobplanet.co.kr/job",
}


class JobPlanetCrawler(BaseCrawler):
    def __init__(self, settings: Mapping[str, Any] | None = None, session: Any = None) -> None:
        merged = dict(settings or {})
        merged.setdefault("headers", dict(_BROWSER_HEADERS))
        super().__init__("jobplanet", merged, session)

    def collect(self) -> list[Job]:
        api_url = self.settings.get("api_url", API_URL)
        keywords = self.settings.get("keywords") or ["AI", "머신러닝", "LLM"]
        pages = max(1, int(self.settings.get("pages", 3)))
        page_size = int(self.settings.get("page_size", 20))
        newcomer_only = self.settings.get("newcomer_only", True) is not False
        jobs_by_id: dict[str, Job] = {}
        for keyword in keywords:
            for page in range(1, pages + 1):
                params = {"q": keyword, "page": str(page), "page_size": str(page_size)}
                try:
                    payload = self.request(api_url, params=params).json()
                except Exception as exc:
                    logger.exception("jobplanet search failed for %r page %d: %s", keyword, page, exc)
                    break
                items = (((payload.get("data") or {}).get("search_result") or {}).get("jobs")) or []
                if not items:
                    break
                for item in items:
                    job = self.search_item_to_job(item)
                    if not job.source_job_id or job.source_job_id in jobs_by_id:
                        continue
                    if newcomer_only and "신입" not in job.experience:
                        continue
                    jobs_by_id[job.source_job_id] = job
        return list(jobs_by_id.values())

    def search_item_to_job(self, item: Mapping[str, Any]) -> Job:
        jd = item.get("jd") or {}
        company = (item.get("company") or {}).get("name", "")
        title = clean_text(jd.get("title"))
        recruit_names = [
            clean_text(entry.get("name"))
            for entry in jd.get("recruitment_types") or []
            if isinstance(entry, Mapping)
        ]
        experience = ", ".join(name for name in recruit_names if name) or clean_text(jd.get("career_text"))
        occupations = [
            clean_text(entry.get("name"))
            for level in ("level1_occupations", "level2_occupations")
            for entry in jd.get(level) or []
            if isinstance(entry, Mapping)
        ]
        job_type = jd.get("job_type") or {}
        employment = clean_text(job_type.get("name") if isinstance(job_type, Mapping) else job_type)
        # The url field carries _rs_* tracking parameters; keep only the path.
        posting_path = clean_text(jd.get("url") or jd.get("partial_url")).split("?")[0]
        deadline = clean_text(jd.get("end_at"))[:10]
        return self.make_job(
            source_job_id=item.get("id"),
            company=company,
            title=title,
            position=title,
            location=", ".join(clean_text(city) for city in jd.get("cities") or []),
            url=urljoin(SITE_URL, posting_path) if posting_path else "",
            deadline=deadline,
            experience=experience,
            employment_type=employment,
            raw_text=" ".join(
                part
                for part in [title, company, *occupations, clean_text(jd.get("career_text")), employment]
                if part
            ),
        )
