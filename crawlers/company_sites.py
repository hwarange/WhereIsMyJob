"""Configurable crawler for company career pages.

This adapter intentionally collects public links exposed by each configured
career page.  It does not bypass CAPTCHA, login pages, or other access controls.
"""

from __future__ import annotations

import hashlib
import logging
from typing import Any, Iterable, Mapping
from urllib.parse import urlparse

from .base import BaseCrawler, Job, extract_job_detail_records, json_ld_to_jobs

logger = logging.getLogger(__name__)


class CompanySitesCrawler(BaseCrawler):
    def __init__(
        self,
        settings: Mapping[str, Any] | None = None,
        session: Any = None,
        targets: Iterable[Mapping[str, Any]] | None = None,
    ) -> None:
        super().__init__("company_sites", settings, session)
        self.targets = list(targets or self.settings.get("targets", []))

    def collect(self) -> list[Job]:
        jobs: list[Job] = []
        for target in self.targets:
            if not isinstance(target, Mapping) or not self._enabled(target.get("enabled", True)):
                continue
            url = str(target.get("url", "")).strip()
            company = str(target.get("company", "")).strip()
            if not url or not urlparse(url).scheme:
                logger.warning("company_sites: invalid target URL for %s", company or "(unknown)")
                continue
            try:
                html = self.fetch_html(url, prefer_playwright=bool(self.settings.get("use_playwright", True)))
                # A corporate landing page is not a job board.  Use schema.org
                # JobPosting data, or a deliberately configured job-detail URL
                # pattern; never treat every navigation/social link as a job.
                page_jobs = json_ld_to_jobs(html, url, self.source)
                detail_pattern = str(target.get("detail_url_pattern", "")).strip()
                if detail_pattern:
                    page_jobs.extend(
                        extract_job_detail_records(
                            html, url, self.source, detail_url_pattern=detail_pattern
                        )
                    )
                for job in page_jobs:
                    if not job.company:
                        job.company = company
                    if not job.source_job_id:
                        job.source_job_id = hashlib.sha256(job.url.encode("utf-8")).hexdigest()[:20]
                    jobs.append(job)
            except Exception as exc:
                logger.exception("company site collection failed for %s (%s): %s", company, url, exc)
        return jobs

    @staticmethod
    def _enabled(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() not in {"false", "0", "no", "n"}
        return bool(value)


# Backwards-friendly alias matching the file name used in the specification.
CompanySiteCrawler = CompanySitesCrawler
