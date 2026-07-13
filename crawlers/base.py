"""Common models and HTTP/HTML helpers for job crawlers.

The source websites do not share a stable response format.  Keeping the
normalized record and the networking policy here means each source adapter can
remain small and can fail independently from the other adapters.
"""

from __future__ import annotations

import logging
import re
import time
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Mapping, Optional
from urllib.parse import urljoin, urlparse
from urllib.robotparser import RobotFileParser

logger = logging.getLogger(__name__)


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def clean_text(value: Any) -> str:
    """Collapse whitespace while keeping the original language intact."""

    if value is None:
        return ""
    return re.sub(r"\s+", " ", str(value)).strip()


def first_non_empty(*values: Any) -> str:
    for value in values:
        text = clean_text(value)
        if text:
            return text
    return ""


@dataclass
class Job:
    """Normalized job record shared by crawlers, filters, and Sheets."""

    source: str = ""
    source_job_id: str = ""
    company: str = ""
    title: str = ""
    position: str = ""
    location: str = ""
    url: str = ""
    posted_at: str = ""
    deadline: str = ""
    experience: str = ""
    employment_type: str = ""
    raw_text: str = ""
    collected_at: str = field(default_factory=utc_now_iso)
    job_key: str = ""
    score: int = 0
    matched_keywords: list[str] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any], source: str = "") -> "Job":
        """Build a Job while tolerating extra source-specific fields."""

        data = dict(value)
        if source and not data.get("source"):
            data["source"] = source
        allowed = {field_name for field_name in cls.__dataclass_fields__}
        return cls(**{key: data[key] for key in allowed if key in data})


JobRecord = Job


class CrawlerError(RuntimeError):
    """An expected source-specific collection error."""


class BaseCrawler:
    """Base class with bounded retries, rate limiting, and robots.txt checks."""

    user_agent = "WhereIsMyJob/1.0 (+https://github.com/; respectful job tracker)"

    def __init__(
        self,
        source: str,
        settings: Optional[Mapping[str, Any]] = None,
        session: Any = None,
    ) -> None:
        self.source = source
        self.settings = dict(settings or {})
        self._session = session
        self._last_request_by_host: dict[str, float] = {}
        self._robots: dict[str, Optional[RobotFileParser]] = {}
        self.request_delay = float(self.settings.get("request_delay_sec", 1.0))
        self.timeout = float(self.settings.get("timeout_sec", 30))
        self.max_retries = int(self.settings.get("max_retries", 3))

    @property
    def session(self) -> Any:
        if self._session is None:
            try:
                import requests

                self._session = requests.Session()
            except ImportError as exc:  # pragma: no cover - dependency install issue
                raise CrawlerError("requests is required for web collection") from exc
        return self._session

    def _headers(self) -> dict[str, str]:
        headers = {"User-Agent": self.user_agent, "Accept-Language": "ko-KR,ko;q=0.9,en;q=0.8"}
        configured = self.settings.get("headers")
        if isinstance(configured, Mapping):
            headers.update({str(key): str(value) for key, value in configured.items()})
        return headers

    def _respect_rate_limit(self, url: str) -> None:
        host = urlparse(url).netloc.lower()
        if not host or self.request_delay <= 0:
            return
        elapsed = time.monotonic() - self._last_request_by_host.get(host, 0)
        remaining = self.request_delay - elapsed
        if remaining > 0:
            time.sleep(remaining)
        self._last_request_by_host[host] = time.monotonic()

    def allowed_by_robots(self, url: str) -> bool:
        """Return whether the configured user agent may fetch ``url``.

        A failure to read robots.txt is treated conservatively and can be
        configured with ``respect_robots: false`` for a trusted internal source.
        Public sources default to respecting robots.txt.
        """

        if self.settings.get("respect_robots", True) is False:
            return True
        parsed = urlparse(url)
        if not parsed.scheme or not parsed.netloc:
            return False
        origin = f"{parsed.scheme}://{parsed.netloc}"
        if origin not in self._robots:
            robots_url = urljoin(origin, "/robots.txt")
            parser = RobotFileParser()
            parser.set_url(robots_url)
            try:
                self._respect_rate_limit(robots_url)
                response = self.session.get(robots_url, headers=self._headers(), timeout=self.timeout)
                if response.status_code >= 400:
                    self._robots[origin] = None
                else:
                    parser.parse(response.text.splitlines())
                    self._robots[origin] = parser
            except Exception as exc:
                logger.warning("%s: could not read robots.txt for %s: %s", self.source, origin, exc)
                self._robots[origin] = None
        parser = self._robots[origin]
        return parser.can_fetch(self.user_agent, url) if parser is not None else True

    def request(self, url: str, **kwargs: Any) -> Any:
        """GET a URL with retries for transient network/server failures."""

        if not self.allowed_by_robots(url):
            raise CrawlerError(f"robots.txt disallows collection: {url}")
        kwargs.setdefault("headers", self._headers())
        kwargs.setdefault("timeout", self.timeout)
        last_error: Optional[Exception] = None
        for attempt in range(self.max_retries):
            try:
                self._respect_rate_limit(url)
                response = self.session.get(url, **kwargs)
                if response.status_code == 429 or response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                return response
            except Exception as exc:
                last_error = exc
                if attempt == self.max_retries - 1:
                    break
                delay = min(2**attempt, 8)
                logger.warning("%s request retry %d/%d for %s: %s", self.source, attempt + 1, self.max_retries, url, exc)
                time.sleep(delay)
        raise CrawlerError(f"request failed after retries: {url}: {last_error}") from last_error

    def fetch_html(self, url: str, prefer_playwright: bool = False) -> str:
        """Fetch static HTML, optionally trying Playwright before requests."""

        if prefer_playwright and self.settings.get("use_playwright", True):
            try:
                return self.render_with_playwright(url)
            except Exception as exc:
                logger.warning("%s: Playwright unavailable/failed for %s; using requests: %s", self.source, url, exc)
        return self.request(url).text

    def render_with_playwright(self, url: str) -> str:
        """Render a public page without attempting CAPTCHA or access control bypass."""

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
                # Search pages often render their result cards just after the
                # initial document.  A bounded wait is enough to capture those
                # cards without attempting to evade access controls.
                page.wait_for_timeout(int(self.settings.get("render_wait_ms", 1500)))
                return page.content()
            finally:
                browser.close()

    def make_job(self, **values: Any) -> Job:
        values = {key: clean_text(value) if key != "matched_keywords" else value for key, value in values.items()}
        values.setdefault("source", self.source)
        values.setdefault("collected_at", utc_now_iso())
        return Job.from_mapping(values, source=self.source)

    def collect(self) -> list[Job]:  # pragma: no cover - interface method
        raise NotImplementedError


def parse_json_ld(html: str) -> list[Mapping[str, Any]]:
    """Extract JSON-LD job postings when a page provides them."""

    import json

    try:
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html, "html.parser")
        scripts = soup.select('script[type="application/ld+json"]')
    except ImportError:
        return []
    found: list[Mapping[str, Any]] = []
    for script in scripts:
        try:
            data = json.loads(script.string or script.get_text())
        except (TypeError, ValueError):
            continue
        values = data if isinstance(data, list) else [data]
        for item in values:
            if not isinstance(item, Mapping):
                continue
            item_type = item.get("@type")
            types = item_type if isinstance(item_type, list) else [item_type]
            if any(str(value).casefold() == "jobposting" for value in types):
                found.append(item)
    return found


def extract_link_records(html: str, base_url: str, source: str) -> list[Job]:
    """Deprecated broad parser kept for backwards compatibility.

    New collectors must use :func:`extract_job_detail_records`.  Parsing every
    link on a career page treats menus, social links, and help pages as jobs.
    """

    return extract_job_detail_records(
        html,
        base_url,
        source,
        detail_url_pattern=r"/(?:recruit|position|job)[^?#]*(?:\d|detail|read)",
    )


def extract_job_detail_records(
    html: str,
    base_url: str,
    source: str,
    *,
    detail_url_pattern: str,
) -> list[Job]:
    """Extract only links that match a source's known job-detail URL format."""

    try:
        from bs4 import BeautifulSoup
    except ImportError as exc:  # pragma: no cover - dependency install issue
        raise CrawlerError("beautifulsoup4 is required for HTML crawlers") from exc

    soup = BeautifulSoup(html, "html.parser")
    pattern = re.compile(detail_url_pattern, re.IGNORECASE)
    source_host = urlparse(base_url).netloc.lower()
    jobs: list[Job] = []
    seen_urls: set[str] = set()
    for anchor in soup.select("a[href]"):
        href = urljoin(base_url, anchor.get("href", ""))
        text = clean_text(anchor.get_text(" ", strip=True))
        parsed = urlparse(href)
        if not href.startswith(("http://", "https://")) or not text or parsed.netloc.lower() != source_host:
            continue
        if href in seen_urls or not pattern.search(parsed.path):
            continue
        if text.casefold() in {"자세히 보기", "상세 보기", "지원하기", "more", "view"}:
            continue
        parent = anchor.find_parent(["article", "li"]) or anchor.parent
        context = clean_text(parent.get_text(" ", strip=True) if parent else text)
        if len(text) < 4 or len(context) < 4:
            continue
        match = pattern.search(parsed.path)
        source_job_id = match.groupdict().get("id", "") if match else ""
        seen_urls.add(href)
        jobs.append(
            Job(
                source=source,
                source_job_id=source_job_id,
                company="",
                title=text,
                position=text,
                url=href,
                raw_text=context,
            )
        )
    return jobs


def json_ld_to_jobs(html: str, base_url: str, source: str) -> list[Job]:
    jobs: list[Job] = []
    for item in parse_json_ld(html):
        identifier = item.get("identifier", "")
        if isinstance(identifier, Mapping):
            identifier = identifier.get("value", "")
        hiring_org = item.get("hiringOrganization", {})
        if isinstance(hiring_org, Mapping):
            company = hiring_org.get("name", "")
        else:
            company = hiring_org
        address = item.get("jobLocation", {})
        if isinstance(address, list):
            address = address[0] if address else {}
        if isinstance(address, Mapping):
            address = address.get("address", address)
        if isinstance(address, Mapping):
            location = first_non_empty(address.get("addressLocality"), address.get("streetAddress"), address.get("addressRegion"))
        else:
            location = address
        jobs.append(
            Job(
                source=source,
                source_job_id=clean_text(identifier),
                company=clean_text(company),
                title=first_non_empty(item.get("title"), item.get("name")),
                position=first_non_empty(item.get("title"), item.get("name")),
                location=clean_text(location),
                url=urljoin(base_url, clean_text(item.get("url"))),
                posted_at=first_non_empty(item.get("datePosted")),
                deadline=first_non_empty(item.get("validThrough")),
                experience=clean_text(item.get("experienceRequirements")),
                employment_type=clean_text(item.get("employmentType")),
                raw_text=clean_text(item.get("description")),
            )
        )
    return jobs
