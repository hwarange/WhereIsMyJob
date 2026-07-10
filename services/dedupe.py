"""Stable job identity and duplicate suppression."""

from __future__ import annotations

import hashlib
import re
import unicodedata
from typing import Iterable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

from crawlers.base import Job, clean_text

TRACKING_PARAMS = {"gclid", "fbclid", "ref", "referrer", "source", "src"}


def normalize_url(url: str) -> str:
    parts = urlsplit(clean_text(url))
    if not parts.netloc:
        return clean_text(url).rstrip("/")
    query = [
        (key, value)
        for key, value in parse_qsl(parts.query, keep_blank_values=True)
        if not key.lower().startswith("utm_") and key.lower() not in TRACKING_PARAMS
    ]
    normalized_path = re.sub(r"/{2,}", "/", parts.path or "/").rstrip("/") or "/"
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), normalized_path, urlencode(sorted(query)), ""))


def normalize_identity(value: str) -> str:
    value = unicodedata.normalize("NFKC", clean_text(value)).casefold()
    value = re.sub(r"[\[\]()[\]{}<>〈〉「」【】]", " ", value)
    value = re.sub(r"[^\w가-힣]+", " ", value, flags=re.UNICODE)
    return re.sub(r"\s+", " ", value).strip()


def build_job_key(job: Job) -> str:
    """Build SHA-256 identity using source ID, URL, then content fallback."""

    source = normalize_identity(job.source)
    source_job_id = normalize_identity(job.source_job_id)
    if source and source_job_id:
        seed = f"source_id|{source}|{source_job_id}"
    else:
        url = normalize_url(job.url)
        if source and url:
            seed = f"url|{source}|{url}"
        else:
            seed = "content|{}|{}|{}".format(
                normalize_identity(job.company),
                normalize_identity(job.title or job.position),
                normalize_identity(job.deadline),
            )
    return hashlib.sha256(seed.encode("utf-8")).hexdigest()


def dedupe_jobs(jobs: Iterable[Job]) -> list[Job]:
    by_key: dict[str, Job] = {}
    for job in jobs:
        job.job_key = build_job_key(job)
        existing = by_key.get(job.job_key)
        if existing is None:
            by_key[job.job_key] = job
            continue
        # Merge fields from later crawlers without discarding richer data from
        # the first occurrence.  The identity remains stable.
        for field_name in ("source_job_id", "company", "title", "position", "location", "url", "posted_at", "deadline", "experience", "employment_type", "raw_text"):
            if not getattr(existing, field_name) and getattr(job, field_name):
                setattr(existing, field_name, getattr(job, field_name))
        if job.score > existing.score:
            existing.score = job.score
            existing.matched_keywords = job.matched_keywords
    return list(by_key.values())
