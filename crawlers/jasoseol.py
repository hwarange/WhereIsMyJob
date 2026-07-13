"""Source-specific collector for the public Jasoseol recruitment board.

Jasoseol's board links to a company-level posting, while the actual positions
and entry-level labels are rendered on the posting detail page.  This adapter
therefore collects only known ``/recruit/<id>`` links and expands each detail
page into one normalized record per recruiting position.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping
from urllib.parse import urljoin, urlparse

from .base import BaseCrawler, CrawlerError, Job, clean_text

logger = logging.getLogger(__name__)

_DETAIL_PATH = re.compile(r"^/recruit/(?P<id>\d+)/?$")
_STATUS_PREFIX = re.compile(r"^(?:시작|마감|수시|진행중?)\s*")
_APPLICANT_SUFFIX = re.compile(r"\s*\d+[,.]?\d*명\s*작성\s*$")
_ROLE_PREFIX = re.compile(r"^(?P<experience>신입(?:\s*/\s*인턴)?|인턴|경력|경력무관)\s+(?P<role>.+)$")


class JasoseolCrawler(BaseCrawler):
    def __init__(self, settings: Mapping[str, Any] | None = None, session: Any = None) -> None:
        super().__init__("jasoseol", settings, session)

    def collect(self) -> list[Job]:
        board_url = self.settings.get("url", "https://jasoseol.com/recruit")
        try:
            board_html = self.fetch_html(board_url, prefer_playwright=True)
        except Exception as exc:
            logger.exception("jasoseol board collection failed for %s: %s", board_url, exc)
            return []

        listings = self.parse_recruit_board(board_html, board_url)
        limit = int(self.settings.get("detail_fetch_limit", 40))
        jobs: list[Job] = []
        for listing in listings[:limit]:
            try:
                detail_html = self.fetch_html(listing.url, prefer_playwright=True)
                jobs.extend(self.parse_recruit_detail(detail_html, listing))
            except Exception as exc:
                logger.warning("jasoseol detail collection failed for %s: %s", listing.url, exc)
        return jobs

    def parse_recruit_board(self, html: str, board_url: str) -> list[Job]:
        """Read only the public recruitment-detail links from the board."""

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:  # pragma: no cover - dependency install issue
            raise CrawlerError("beautifulsoup4 is required for Jasoseol collection") from exc

        soup = BeautifulSoup(html, "html.parser")
        host = urlparse(board_url).netloc.lower()
        listings: list[Job] = []
        seen: set[str] = set()
        for anchor in soup.select("a[href]"):
            url = urljoin(board_url, anchor.get("href", ""))
            parsed = urlparse(url)
            match = _DETAIL_PATH.fullmatch(parsed.path)
            if not match or parsed.netloc.lower() != host or url in seen:
                continue
            company = _STATUS_PREFIX.sub("", clean_text(anchor.get_text(" ", strip=True)))
            if not company:
                continue
            seen.add(url)
            parent = anchor.find_parent("li") or anchor.parent
            context = clean_text(parent.get_text(" ", strip=True) if parent else company)
            listings.append(
                self.make_job(
                    source_job_id=match.group("id"),
                    company=company,
                    title=company,
                    position=company,
                    url=url,
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
                    position=posting_title or listing.position,
                    url=listing.url,
                    raw_text=page_text,
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
                position=posting_title or listing.position,
                url=listing.url,
                raw_text=page_text,
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
