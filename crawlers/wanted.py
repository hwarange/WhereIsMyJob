"""Collector for public Wanted position listings.

The crawler can read either configured company pages or a bounded slice of
Wanted's public all-positions page. It never signs in, applies to positions,
or accesses private data.
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
_PUBLIC_LISTING_URL = "https://www.wanted.co.kr/wdlist"


class WantedCrawler(BaseCrawler):
    """Collect public Wanted position cards."""

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
        method = clean_text(self.settings.get("method", "company_targets")).lower()
        if method in {"public_listings", "public_listing", "listing"}:
            return self._collect_public_listings()
        if method not in {"company_targets", "company_target", "company"}:
            logger.warning("wanted: unsupported collection method %r", method)
            return []

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

    def _collect_public_listings(self) -> list[Job]:
        """Collect a bounded portion of the public all-positions page.

        Keyword relevance is deliberately handled by the shared ``JobFilter``
        so Wanted and the other sources use one consistent set of rules.
        """

        url = clean_text(self.settings.get("url", _PUBLIC_LISTING_URL))
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc.lower() not in {"wanted.co.kr", "www.wanted.co.kr"}:
            logger.warning("wanted: invalid public listing URL %s", url or "(empty)")
            return []
        try:
            html = self.fetch_html(url, prefer_playwright=True)
            limit = int(self.settings.get("listing_fetch_limit", 300))
            return self.parse_listing_html(html, url, limit=limit)
        except Exception as exc:
            logger.exception("wanted public listing collection failed for %s: %s", url, exc)
            return []

    def render_with_playwright(self, url: str) -> str:
        """Render a public company or all-positions page."""

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
                method = clean_text(self.settings.get("method", "company_targets")).lower()
                if method in {"public_listings", "public_listing", "listing"}:
                    return self._render_public_listings(page)
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

    def _render_public_listings(self, page: Any) -> str:
        """Reveal a bounded number of cards from Wanted's public listing."""

        limit = max(1, int(self.settings.get("listing_fetch_limit", 300)))
        max_scrolls = max(0, int(self.settings.get("max_scrolls", 25)))
        cards = page.locator('a[href^="/wd/"]')
        unchanged_scrolls = 0
        for _ in range(max_scrolls):
            before = cards.count()
            if before >= limit:
                break
            page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
            page.wait_for_timeout(int(self.settings.get("scroll_wait_ms", 500)))
            after = cards.count()
            unchanged_scrolls = unchanged_scrolls + 1 if after <= before else 0
            if unchanged_scrolls >= 2:
                break
        return page.content()

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

    def parse_listing_html(self, html: str, page_url: str, *, limit: int = 300) -> list[Job]:
        """Parse public all-positions cards without treating navigation as jobs."""

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:  # pragma: no cover - dependency install issue
            raise CrawlerError("beautifulsoup4 is required for Wanted collection") from exc

        soup = BeautifulSoup(html, "html.parser")
        page_host = urlparse(page_url).netloc.lower()
        jobs: list[Job] = []
        seen_urls: set[str] = set()
        for anchor in soup.select("a[href]"):
            if len(jobs) >= max(1, limit):
                break
            url = urljoin(page_url, str(anchor.get("href", "")))
            parsed = urlparse(url)
            match = _POSITION_PATH.fullmatch(parsed.path)
            if not match or parsed.netloc.lower() != page_host or url in seen_urls:
                continue
            position_data = anchor.select_one("[data-position-id]")
            if position_data is None or clean_text(position_data.get("data-position-id")) != match.group("id"):
                continue
            title = first_non_empty(position_data.get("data-position-name"), anchor.get("title"))
            company = clean_text(position_data.get("data-company-name"))
            if not title or not company:
                continue
            lines = [clean_text(line) for line in anchor.get_text("\n", strip=True).splitlines()]
            lines = [line for line in lines if line]
            details = lines[lines.index(company) + 1 :] if company in lines else []
            location, experience = "", ""
            if details:
                location_and_experience = details[-1]
                if " · " in location_and_experience:
                    location, experience = (clean_text(part) for part in location_and_experience.split(" · ", 1))
                else:
                    experience = next((line for line in details if _EXPERIENCE_TEXT.search(line)), "")
                    location = details[0] if details and details[0] != experience else ""
            seen_urls.add(url)
            jobs.append(
                self.make_job(
                    source_job_id=match.group("id"),
                    company=company,
                    title=title,
                    position=title,
                    location=location,
                    url=url,
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
