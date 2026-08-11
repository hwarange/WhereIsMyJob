"""JobKorea duty-board crawler.

JobKorea's robots.txt (updated 2026-04) disallows keyword search URLs
(``/Search?...``) but explicitly allows the public duty-filtered job board
(``/recruit/joblist``) and posting reads (``/Recruit/GI_Read``).  This
collector therefore never touches the search endpoint: it requests the board
filtered by AI/ML duty codes and the site's own entry-level filter
(``careerType=1``), and parses the server-rendered rows.  Detail pages are not
fetched — the list rows already carry company, deadline, experience,
education, and employment-type tags.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Mapping
from urllib.parse import urljoin

from .base import BaseCrawler, CrawlerError, Job, clean_text

logger = logging.getLogger(__name__)

BOARD_URL = "https://www.jobkorea.co.kr/recruit/joblist"

# 직무별 채용정보 보드의 duty 코드.  dutyCtgr 10031 = 데이터·AI 직군.
DEFAULT_DUTY_CTGR = "10031"
DEFAULT_DUTIES = [
    "1000242",  # AI/ML엔지니어
    "1000417",  # AI/ML연구원
    "1000237",  # 데이터사이언티스트
    "1000422",  # MLOps엔지니어
    "1000423",  # AI서비스개발자
]

_GI_READ = re.compile(r"/Recruit/GI_Read/(?P<id>\d+)", re.IGNORECASE)
_EXPERIENCE_TAG = re.compile(r"신입|경력|무관")
_EMPLOYMENT_TAG = re.compile(r"정규직|계약직|인턴|연수생|파견직|프리랜서|아르바이트")


class JobKoreaCrawler(BaseCrawler):
    def __init__(self, settings: Mapping[str, Any] | None = None, session: Any = None) -> None:
        super().__init__("jobkorea", settings, session)

    def collect(self) -> list[Job]:
        board_url = self.settings.get("url", BOARD_URL)
        duty_ctgr = clean_text(self.settings.get("duty_ctgr", DEFAULT_DUTY_CTGR))
        duties = [clean_text(duty) for duty in self.settings.get("duties") or DEFAULT_DUTIES]
        pages = max(1, int(self.settings.get("pages", 2)))
        career_type = clean_text(self.settings.get("career_type", "1"))
        jobs_by_id: dict[str, Job] = {}
        for duty in duties:
            for page in range(1, pages + 1):
                params = {
                    "menucode": "duty",
                    "dutyCtgr": duty_ctgr,
                    "duty": duty,
                    "Page_No": str(page),
                }
                if career_type:
                    # careerType=1 is the board's own 신입 filter.
                    params["careerType"] = career_type
                try:
                    html = self.request(board_url, params=params).text
                except Exception as exc:
                    logger.exception("jobkorea board fetch failed for duty %s page %d: %s", duty, page, exc)
                    break
                page_jobs = self.parse_list_html(html, board_url)
                new = [job for job in page_jobs if job.source_job_id not in jobs_by_id]
                for job in new:
                    jobs_by_id[job.source_job_id] = job
                if not new:
                    break
        return list(jobs_by_id.values())

    def parse_list_html(self, html: str, base_url: str) -> list[Job]:
        """Parse server-rendered board rows (both tag-style and headline-style)."""

        try:
            from bs4 import BeautifulSoup
        except ImportError as exc:  # pragma: no cover - dependency install issue
            raise CrawlerError("beautifulsoup4 is required for JobKorea collection") from exc

        soup = BeautifulSoup(html, "html.parser")
        jobs: list[Job] = []
        seen: set[str] = set()
        for row in soup.select("li.devloopArea"):
            anchor = next(
                (a for a in row.select("a[href]") if _GI_READ.search(a.get("href", ""))),
                None,
            )
            if anchor is None:
                continue
            match = _GI_READ.search(anchor.get("href", ""))
            source_job_id = match.group("id")
            if source_job_id in seen:
                continue
            company_element = row.select_one(".company-name a, .company .name a, .name a")
            title_element = row.select_one("p.title a, .title a, .description .text")
            company = clean_text(company_element.get_text(" ", strip=True) if company_element else "")
            title = clean_text(title_element.get_text(" ", strip=True) if title_element else "")
            if not title:
                title = clean_text(anchor.get_text(" ", strip=True))
            if not title or len(title) < 4:
                continue
            tags = [clean_text(tag.get_text(" ", strip=True)) for tag in row.select(".tags-wrapper .tag")]
            experience = next((tag for tag in tags if _EXPERIENCE_TAG.search(tag)), "")
            employment = next((tag for tag in tags if _EMPLOYMENT_TAG.search(tag)), "")
            deadline_element = row.select_one(".deadLine, .deadline, .dday")
            deadline = clean_text(deadline_element.get_text(" ", strip=True) if deadline_element else "")
            seen.add(source_job_id)
            jobs.append(
                self.make_job(
                    source_job_id=source_job_id,
                    company=company,
                    title=title,
                    position=title,
                    url=urljoin(base_url, f"/Recruit/GI_Read/{source_job_id}"),
                    deadline=deadline,
                    experience=experience,
                    employment_type=employment,
                    raw_text=clean_text(row.get_text(" ", strip=True)),
                )
            )
        return jobs
