"""Source-specific collector for the public Jasoseol search results.

The search page server-renders company, title, role, employment type, closing
date, and a known detail URL.  Detail pages are read only to add an education
requirement or split a combined posting into individual roles.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse

from .base import BaseCrawler, CrawlerError, Job, clean_text

logger = logging.getLogger(__name__)

_DETAIL_PATH = re.compile(r"^/recruit/(?P<id>\d+)/?$")
_APPLICANT_SUFFIX = re.compile(r"\s*\d+[,.]?\d*명\s*작성\s*$")
_ROLE_PREFIX = re.compile(r"^(?P<experience>신입(?:\s*/\s*인턴)?|인턴|경력|경력무관)\s+(?P<role>.+)$")


class JasoseolCrawler(BaseCrawler):
    def __init__(self, settings: Mapping[str, Any] | None = None, session: Any = None) -> None:
        super().__init__("jasoseol", settings, session)

    def collect(self) -> list[Job]:
        search_url = self.settings.get("url", "https://jasoseol.com/search")
        try:
            # The public page server-renders the cards, but rejects ordinary
            # HTTP clients.  Render the same public page in Chromium first;
            # ``fetch_html`` falls back to the declared HTTP client only when
            # rendering itself is unavailable.
            search_html = self.fetch_html(search_url, prefer_playwright=True)
        except Exception as exc:
            logger.exception("jasoseol search collection failed for %s: %s", search_url, exc)
            return []

        listings = self.parse_search_html(search_html, search_url)
        if not listings:
            logger.warning(
                "jasoseol search returned no public result cards; the site may be declining the declared crawler"
            )
        limit = int(self.settings.get("detail_fetch_limit", 40))
        jobs: list[Job] = []
        for listing in listings[:limit]:
            try:
                detail_html = self.fetch_html(listing.url, prefer_playwright=True)
                jobs.extend(self.parse_recruit_detail(detail_html, listing))
            except Exception as exc:
                logger.warning("jasoseol detail collection failed for %s: %s", listing.url, exc)
                jobs.append(listing)
        return jobs

    def parse_search_html(self, html: str, search_url: str) -> list[Job]:
        """Parse the server-rendered cards on ``/search``.

        The ``EmploymentCompanyCard`` component is the public search-result
        contract.  Restricting extraction to it avoids menus, recommended
        links, and calendar items being mistaken for job postings.
        """

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:  # pragma: no cover - dependency install issue
            raise CrawlerError("beautifulsoup4 is required for Jasoseol collection") from exc

        soup = BeautifulSoup(html, "html.parser")
        host = urlparse(search_url).netloc.lower()
        listings: list[Job] = []
        seen: set[str] = set()
        cards = soup.select('a[data-sentry-component="EmploymentCompanyCard"][href]')
        for anchor in cards:
            url = urljoin(search_url, anchor.get("href", ""))
            parsed = urlparse(url)
            match = _DETAIL_PATH.fullmatch(parsed.path)
            if not match or parsed.netloc.lower() != host or url in seen:
                continue
            company_element = anchor.find("h5")
            title_element = anchor.find("h4")
            role_element = next(
                (
                    element
                    for element in anchor.find_all("div")
                    if "line-clamp" in " ".join(element.get("class", []))
                ),
                None,
            )
            company = clean_text(company_element.get_text(" ", strip=True) if company_element else "")
            title = clean_text(title_element.get_text(" ", strip=True) if title_element else "")
            position = clean_text(role_element.get_text(" ", strip=True) if role_element else "")
            if not company or not title:
                continue
            seen.add(url)
            employment = anchor.select_one('[data-sentry-component="CompanyEmploymentType"]')
            employment_parts = [clean_text(part.get_text(" ", strip=True)) for part in employment.select("span")]
            employment_parts = [part for part in employment_parts if part]
            period = anchor.select_one('[data-sentry-component="EmploymentPeriod"]')
            deadline = clean_text(period.get_text(" ", strip=True) if period else "")
            context = clean_text(anchor.get_text(" ", strip=True))
            listings.append(
                self.make_job(
                    source_job_id=match.group("id"),
                    company=company,
                    title=title,
                    position=position or title,
                    url=url,
                    deadline=deadline,
                    experience=employment_parts[1] if len(employment_parts) > 1 else "",
                    employment_type=employment_parts[1] if len(employment_parts) > 1 else "",
                    raw_text=context,
                )
            )
        return listings

    def parse_recruit_detail(self, html: str, listing: Job) -> list[Job]:
        """Expand the detail page's ``모집 직무`` rows into individual jobs."""

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:  # pragma: no cover - dependency install issue
            raise CrawlerError("beautifulsoup4 is required for Jasoseol collection") from exc

        soup = BeautifulSoup(html, "html.parser")
        main = soup.select_one("main") or soup
        page_text = clean_text(main.get_text(" ", strip=True))
        heading = main.find("h1")
        posting_title = clean_text(heading.get_text(" ", strip=True) if heading else "")
        company_heading = next(
            (
                candidate
                for candidate in main.find_all("h2")
                if clean_text(candidate.get_text(" ", strip=True)) != "모집 직무"
            ),
            None,
        )
        company = clean_text(company_heading.get_text(" ", strip=True) if company_heading else "") or listing.company
        role_heading = next(
            (
                candidate
                for candidate in main.find_all("h2")
                if clean_text(candidate.get_text(" ", strip=True)) == "모집 직무"
            ),
            None,
        )
        if role_heading is None:
            return [
                self.make_job(
                    source_job_id=listing.source_job_id,
                    company=company,
                    title=posting_title or listing.title,
                    position=listing.position,
                    url=listing.url,
                    deadline=listing.deadline,
                    experience=listing.experience,
                    employment_type=listing.employment_type,
                    raw_text=clean_text(f"{listing.raw_text} {page_text}"),
                )
            ]

        section = role_heading.parent
        rows = section.select("li") if section else []
        jobs: list[Job] = []
        for index, row in enumerate(rows, start=1):
            experience, role = self._role_from_row(row.get_text(" ", strip=True))
            if not role:
                continue
            jobs.append(
                self.make_job(
                    source_job_id=f"{listing.source_job_id}:{index}",
                    company=company,
                    title=f"{company} {role}".strip(),
                    position=role,
                    url=listing.url,
                    experience=experience,
                    employment_type="신입/인턴" if "신입" in experience or "인턴" in experience else "",
                    raw_text=page_text,
                )
            )
        return jobs or [
            self.make_job(
                source_job_id=listing.source_job_id,
                company=company,
                title=posting_title or listing.title,
                position=listing.position,
                url=listing.url,
                deadline=listing.deadline,
                experience=listing.experience,
                employment_type=listing.employment_type,
                raw_text=clean_text(f"{listing.raw_text} {page_text}"),
            )
        ]

    @staticmethod
    def _role_from_row(value: str) -> tuple[str, str]:
        text = clean_text(value)
        text = text.replace("자소서 문항 보기", "")
        text = _APPLICANT_SUFFIX.sub("", text).strip()
        match = _ROLE_PREFIX.match(text)
        if not match:
            return "", ""
        return clean_text(match.group("experience")), clean_text(match.group("role"))
