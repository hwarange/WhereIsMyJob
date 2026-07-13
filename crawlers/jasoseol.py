"""Jasoseol search-page crawler with a Playwright-first, requests fallback."""

from __future__ import annotations

import logging
from typing import Any, Mapping
from urllib.parse import urlencode, urlsplit, urlunsplit

from .base import BaseCrawler, Job, extract_job_detail_records, json_ld_to_jobs

logger = logging.getLogger(__name__)


def _with_query(url: str, params: Mapping[str, Any]) -> str:
    parts = urlsplit(url)
    query = parts.query
    encoded = urlencode(params)
    return urlunsplit((parts.scheme, parts.netloc, parts.path, f"{query}&{encoded}" if query else encoded, parts.fragment))


class JasoseolCrawler(BaseCrawler):
    def __init__(self, settings: Mapping[str, Any] | None = None, session: Any = None) -> None:
        super().__init__("jasoseol", settings, session)

    def collect(self) -> list[Job]:
        base_url = self.settings.get("url", "https://jasoseol.com/search")
        keywords = self.settings.get("keywords") or ["AI", "머신러닝", "LLM"]
        jobs: list[Job] = []
        # The public /recruit board does not support the old keyword query
        # parameter.  Read its rendered listing once, then apply our shared
        # AI/ML filter to the returned public job cards.
        urls = [base_url] if urlsplit(base_url).path.rstrip("/") == "/recruit" else [
            _with_query(base_url, {self.settings.get("query_param", "keyword"): keyword}) for keyword in keywords
        ]
        for url in urls:
            try:
                html = self.fetch_html(url, prefer_playwright=True)
                jobs.extend(json_ld_to_jobs(html, url, self.source))
                jobs.extend(
                    extract_job_detail_records(
                        html, url, self.source, detail_url_pattern=r"/recruit/(?P<id>\d+)(?:/|$)"
                    )
                )
            except Exception as exc:
                logger.exception("jasoseol collection failed for %s: %s", url, exc)
        return jobs
