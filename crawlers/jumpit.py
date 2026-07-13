"""Jumpit developer-job crawler."""

from __future__ import annotations

import logging
from typing import Any, Mapping
from urllib.parse import urlencode, urlsplit, urlunsplit

from .base import BaseCrawler, CrawlerError, Job, clean_text, extract_job_detail_records, json_ld_to_jobs

logger = logging.getLogger(__name__)


class JumpitCrawler(BaseCrawler):
    def __init__(self, settings: Mapping[str, Any] | None = None, session: Any = None) -> None:
        super().__init__("jumpit", settings, session)

    def _search_url(self, base_url: str, keyword: str) -> str:
        parts = urlsplit(base_url)
        query = {self.settings.get("query_param", "keyword"): keyword}
        existing = f"{parts.query}&" if parts.query else ""
        return urlunsplit((parts.scheme, parts.netloc, parts.path, existing + urlencode(query), parts.fragment))

    def collect(self) -> list[Job]:
        base_url = self.settings.get("url", "https://jumpit.saramin.co.kr/positions")
        keywords = self.settings.get("keywords") or ["AI", "ML", "LLM"]
        jobs: list[Job] = []
        for keyword in keywords:
            url = self._search_url(base_url, keyword)
            try:
                html = self.fetch_html(url, prefer_playwright=bool(self.settings.get("use_playwright", True)))
                jobs.extend(json_ld_to_jobs(html, url, self.source))
                jobs.extend(
                    extract_job_detail_records(
                        html, url, self.source, detail_url_pattern=r"/position/(?P<id>[A-Za-z0-9_-]+)(?:/|$)"
                    )
                )
            except Exception as exc:
                logger.exception("jumpit collection failed for keyword %r: %s", keyword, exc)
        # The listing cards omit education requirements.  Read each public
        # detail page so the shared degree filter can make a real decision.
        unique = {job.url: job for job in jobs if job.url}
        limit = int(self.settings.get("detail_fetch_limit", 80))
        detailed: list[Job] = []
        for job in list(unique.values())[:limit]:
            try:
                detailed.append(self._enrich_detail(job))
            except Exception as exc:
                logger.warning("jumpit detail collection failed for %s: %s", job.url, exc)
        return detailed

    def _enrich_detail(self, job: Job) -> Job:
        html = self.fetch_html(job.url, prefer_playwright=False)
        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:  # pragma: no cover
            raise CrawlerError("beautifulsoup4 is required for Jumpit detail collection") from exc
        soup = BeautifulSoup(html, "html.parser")
        fields: dict[str, str] = {}
        for row in soup.select("dl"):
            label = clean_text((row.find("dt") or "").get_text(" ", strip=True) if row.find("dt") else "")
            value = clean_text((row.find("dd") or "").get_text(" ", strip=True) if row.find("dd") else "")
            if label and value:
                fields[label] = value
        heading = soup.find("h1")
        if heading:
            job.title = clean_text(heading.get_text(" ", strip=True)) or job.title
            job.position = job.title
        job.experience = fields.get("경력", job.experience)
        job.deadline = fields.get("마감일", job.deadline)
        job.location = fields.get("근무지역", job.location)
        job.raw_text = clean_text(soup.get_text(" ", strip=True))
        return job
