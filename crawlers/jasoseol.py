"""Jasoseol search-page crawler with a Playwright-first, requests fallback."""

from __future__ import annotations

import logging
from typing import Any, Mapping
from urllib.parse import urlencode, urlsplit, urlunsplit

from .base import BaseCrawler, Job, extract_link_records, json_ld_to_jobs

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
        for keyword in keywords:
            url = _with_query(base_url, {self.settings.get("query_param", "keyword"): keyword})
            try:
                html = self.fetch_html(url, prefer_playwright=True)
                jobs.extend(json_ld_to_jobs(html, url, self.source))
                jobs.extend(extract_link_records(html, url, self.source))
            except Exception as exc:
                logger.exception("jasoseol collection failed for keyword %r: %s", keyword, exc)
        return jobs
