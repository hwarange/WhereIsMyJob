"""Collector for public Wanted company-position listings.

Wanted company pages expose a company's currently open positions as public
``/wd/<position-id>`` links. This crawler only reads that listing; it does
not sign in, apply to positions, or access private data.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Iterable, Mapping
from urllib.parse import urljoin, urlparse

from .base import BaseCrawler, CrawlerError, Job, clean_text, first_non_empty

logger = logging.getLogger(__name__)

_POSITION_PATH = re.compile(r"^/wd/(?P<id>\d+)/?$")
_EXPERIENCE_TEXT = re.compile(r"(?:신입|경력|인턴|무관)")


class WantedCrawler(BaseCrawler):
    """Collect public position cards from configured Wanted company pages."""

    default_target = {
        "company": "업스테이지",
        "url": "https://www.wanted.co.kr/company/16049",
    }

    def __init__(
        self,
        settings: Mapping[str, Any] | None = None,
        session: Any = None,
        targets: Iterable[Mapping[str, Any]] | None = None,
    ) -> None:
        super().__init__("wanted", settings, session)
        configured_targets = targets if targets is not None else self.settings.get("targets")
        self.targets = list(configured_targets or [self.default_target])

    def collect(self) -> list[Job]:
        jobs: list[Job] = []
        for target in self.targets:
            if not isinstance(target, Mapping) or not self._enabled(target.get("enabled", True)):
                continue
            url = clean_text(target.get("url"))
            company = clean_text(target.get("company"))
            parsed = urlparse(url)
            if parsed.scheme != "https" or parsed.netloc.lower() not in {"wanted.co.kr", "www.wanted.co.kr"}:
                logger.warning("wanted: invalid company URL for %s", company or "(unknown)")
                continue
            try:
                html = self.fetch_html(url, prefer_playwright=bool(self.settings.get("use_playwright", True)))
                jobs.extend(self.parse_company_html(html, url, company))
            except Exception as exc:
                logger.exception("wanted collection failed for %s (%s): %s", company or "(unknown)", url, exc)
        return jobs

    def render_with_playwright(self, url: str) -> str:
        """Render a public company page and reveal its bounded position list."""

        if not self.allowed_by_robots(url):
            raise CrawlerError(f"robots.txt disallows collection: {url}")
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:  # pragma: no cover - optional runtime dependency
            raise CrawlerError("playwright is not installed") from exc

        with sync_playwright() as playwright:
            browser = playwright.chromium.launch(headless=True)
            try:
                page = browser.new_page(user_agent=self.user_agent)
                page.goto(url, wait_until="domcontentloaded", timeout=int(self.timeout * 1000))
                page.wait_for_timeout(int(self.settings.get("render_wait_ms", 1500)))
                # Company pages initially show a preview. Expand the public
                # "N개 포지션 더보기" control a bounded number of times.
                if self._enabled(self.settings.get("expand_positions", True)):
                    for _ in range(int(self.settings.get("max_expand_clicks", 3))):
                        more = page.locator("button").filter(has_text=re.compile(r"포지션 더보기"))
                        if more.count() != 1:
                            break
                        more.click()
                        page.wait_for_timeout(250)
                return page.content()
            finally:
                browser.close()

    def parse_company_html(self, html: str, page_url: str, company_override: str = "") -> list[Job]:
        """Parse only Wanted position-card links from one company page."""

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:  # pragma: no cover - dependency install issue
            raise CrawlerError("beautifulsoup4 is required for Wanted collection") from exc

        soup = BeautifulSoup(html, "html.parser")
        page_host = urlparse(page_url).netloc.lower()
        heading = soup.find("h1")
        page_company = clean_text(heading.get_text(" ", strip=True) if heading else "")
        jobs: list[Job] = []
        seen_urls: set[str] = set()
        for anchor in soup.select("a[href]"):
            url = urljoin(page_url, str(anchor.get("href", "")))
            parsed = urlparse(url)
            match = _POSITION_PATH.fullmatch(parsed.path)
            if not match or parsed.netloc.lower() != page_host or url in seen_urls:
                continue
            position_data = anchor.select_one("[data-position-id]")
            if position_data is None or clean_text(position_data.get("data-position-id")) != match.group("id"):
                continue
            title = first_non_empty(anchor.get("title"), position_data.get("data-position-name"))
            if not title:
                continue
            lines = [clean_text(line) for line in anchor.get_text("\n", strip=True).splitlines()]
            lines = [line for line in lines if line]
            metadata = lines[lines.index(title) + 1 :] if title in lines else []
            experience = next((line for line in metadata if _EXPERIENCE_TEXT.search(line)), "")
            location = metadata[0] if metadata else ""
            deadline = metadata[-1] if len(metadata) > 1 and metadata[-1] != experience else ""
            seen_urls.add(url)
            jobs.append(
                self.make_job(
                    source_job_id=match.group("id"),
                    company=first_non_empty(company_override, position_data.get("data-company-name"), page_company),
                    title=title,
                    position=title,
                    location=location,
                    url=url,
                    deadline=deadline,
                    experience=experience,
                    employment_type=clean_text(position_data.get("data-position-employment-type")),
                    raw_text=clean_text(anchor.get_text(" ", strip=True)),
                )
            )
        return jobs

    @staticmethod
    def _enabled(value: Any) -> bool:
        if isinstance(value, str):
            return value.strip().lower() not in {"false", "0", "no", "n", "off"}
        return bool(value)
