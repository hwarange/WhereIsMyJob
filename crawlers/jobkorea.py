"""JobKorea search crawler."""

from __future__ import annotations

import logging
from typing import Any, Mapping
from urllib.parse import urlencode, urlsplit, urlunsplit

from .base import BaseCrawler, Job, extract_link_records, json_ld_to_jobs

logger = logging.getLogger(__name__)


class JobKoreaCrawler(BaseCrawler):
    def __init__(self, settings: Mapping[str, Any] | None = None, session: Any = None) -> None:
        super().__init__("jobkorea", settings, session)

    def _search_url(self, base_url: str, keyword: str) -> str:
        parts = urlsplit(base_url)
        query = {"stext": keyword, "tabType": "recruit"}
        existing = f"{parts.query}&" if parts.query else ""
        return urlunsplit((parts.scheme, parts.netloc, parts.path, existing + urlencode(query), parts.fragment))

    def collect(self) -> list[Job]:
        base_url = self.settings.get("url", "https://www.jobkorea.co.kr/")
        keywords = self.settings.get("keywords") or ["AI Engineer 신입"]
        jobs: list[Job] = []
        for keyword in keywords:
            url = self._search_url(base_url, keyword)
            try:
                html = self.fetch_html(url, prefer_playwright=bool(self.settings.get("use_playwright", False)))
                jobs.extend(json_ld_to_jobs(html, url, self.source))
                jobs.extend(extract_link_records(html, url, self.source))
            except Exception as exc:
                logger.exception("jobkorea collection failed for keyword %r: %s", keyword, exc)
        return jobs
