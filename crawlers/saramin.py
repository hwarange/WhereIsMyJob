"""Saramin Open API crawler."""

from __future__ import annotations

import json
import logging
import os
import xml.etree.ElementTree as ET
from typing import Any, Mapping

from .base import BaseCrawler, CrawlerError, Job, clean_text, first_non_empty

logger = logging.getLogger(__name__)


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _xml_child_text(node: ET.Element, names: tuple[str, ...]) -> str:
    for child in node.iter():
        if _local_name(child.tag) in names and child.text:
            return clean_text(child.text)
    return ""


def _json_value(value: Any, *keys: str) -> Any:
    current = value
    for key in keys:
        if isinstance(current, Mapping):
            current = current.get(key, "")
        else:
            return ""
    return current


class SaraminCrawler(BaseCrawler):
    """Collect jobs through Saramin's official job-search API."""

    api_url = "https://oapi.saramin.co.kr/job-search"

    def __init__(self, settings: Mapping[str, Any] | None = None, session: Any = None, access_key: str | None = None) -> None:
        super().__init__("saramin", settings, session)
        self.access_key = access_key or os.getenv("SARAMIN_ACCESS_KEY", "")

    def collect(self) -> list[Job]:
        if not self.access_key:
            logger.warning("saramin: SARAMIN_ACCESS_KEY is not set; skipping API collection")
            return []
        keywords = self.settings.get("keywords") or ["AI Engineer 신입"]
        count = int(self.settings.get("count_per_keyword", 50))
        jobs: list[Job] = []
        for keyword in keywords:
            try:
                response = self.request(
                    self.settings.get("url", self.api_url),
                    params={"access-key": self.access_key, "keywords": keyword, "count": count, "start": 0, "sort": "reg_dt"},
                    headers={**self._headers(), "Accept": "application/json, application/xml;q=0.9"},
                )
                jobs.extend(self.parse_response(response, keyword=keyword))
            except Exception as exc:
                logger.exception("saramin collection failed for keyword %r: %s", keyword, exc)
        return jobs

    def parse_response(self, response: Any, keyword: str = "") -> list[Job]:
        """Parse either JSON or XML, as the API has supported both formats."""

        body = getattr(response, "text", "") or ""
        content_type = str(getattr(response, "headers", {}).get("content-type", "")).lower()
        payload: Any = None
        if "json" in content_type or body.lstrip().startswith(("{", "[")):
            try:
                payload = response.json()
            except (AttributeError, ValueError, json.JSONDecodeError):
                payload = None
        if payload is not None:
            return self._parse_json(payload)
        try:
            root = ET.fromstring(body)
        except ET.ParseError as exc:
            raise CrawlerError(f"saramin response was not valid JSON/XML for keyword {keyword!r}") from exc
        return self._parse_xml(root)

    def _parse_json(self, payload: Any) -> list[Job]:
        values: Any = payload
        if isinstance(payload, Mapping):
            values = payload.get("jobs", payload.get("job", payload.get("items", [])))
            if isinstance(values, Mapping):
                values = values.get("job", values.get("item", []))
        if isinstance(values, Mapping):
            values = [values]
        jobs: list[Job] = []
        for item in values or []:
            if not isinstance(item, Mapping):
                continue
            company = _json_value(item, "company", "detail", "name") or _json_value(item, "company", "name")
            detail = item.get("detail", {}) if isinstance(item.get("detail", {}), Mapping) else {}
            title = first_non_empty(_json_value(item, "position", "title"), item.get("title"), detail.get("title"))
            url = first_non_empty(item.get("url"), detail.get("href"), item.get("link"))
            location = first_non_empty(_json_value(item, "position", "location"), item.get("location"), detail.get("location"))
            experience = first_non_empty(_json_value(item, "position", "experience-level", "name"), item.get("experience"))
            employment = first_non_empty(_json_value(item, "position", "job-type", "name"), item.get("employment_type"), item.get("jobType"))
            raw = json.dumps(item, ensure_ascii=False)
            jobs.append(
                self.make_job(
                    source_job_id=first_non_empty(item.get("id"), item.get("job_id"), detail.get("id")),
                    company=company,
                    title=title,
                    position=title,
                    location=location,
                    url=url,
                    posted_at=first_non_empty(item.get("opening-timestamp"), item.get("posted_at"), item.get("datePosted")),
                    deadline=first_non_empty(item.get("expiration-timestamp"), item.get("deadline"), item.get("validThrough")),
                    experience=experience,
                    employment_type=employment,
                    raw_text=raw,
                )
            )
        return jobs

    def _parse_xml(self, root: ET.Element) -> list[Job]:
        jobs: list[Job] = []
        nodes = [node for node in root.iter() if _local_name(node.tag) == "job"]
        for node in nodes:
            company_node = next((child for child in node.iter() if _local_name(child.tag) == "company"), None)
            company = _xml_child_text(company_node, ("name",)) if company_node is not None else ""
            detail_node = next((child for child in node if _local_name(child.tag) == "detail"), None)
            url = ""
            if detail_node is not None:
                url = first_non_empty(detail_node.attrib.get("href"), _xml_child_text(detail_node, ("href", "url")))
            title = _xml_child_text(node, ("title",))
            jobs.append(
                self.make_job(
                    source_job_id=node.attrib.get("id", ""),
                    company=company,
                    title=title,
                    position=title,
                    location=_xml_child_text(node, ("location", "name")),
                    url=url,
                    posted_at=_xml_child_text(node, ("opening-timestamp", "datePosted")),
                    deadline=_xml_child_text(node, ("expiration-timestamp", "validThrough")),
                    experience=_xml_child_text(node, ("experience-level", "name")),
                    employment_type=_xml_child_text(node, ("job-type", "name")),
                    raw_text=" ".join(text.strip() for text in node.itertext() if text.strip()),
                )
            )
        return jobs


# Explicit alias for callers that want to distinguish the API adapter from
# future Saramin HTML adapters.
SaraminAPICrawler = SaraminCrawler
