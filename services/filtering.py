"""Configurable keyword scoring for entry-level AI/ML jobs."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Iterable, Mapping

from crawlers.base import Job, clean_text


@dataclass(frozen=True)
class Rule:
    type: str
    keyword: str
    weight: int = 0
    enabled: bool = True
    note: str = ""

    @classmethod
    def from_mapping(cls, value: Mapping[str, Any]) -> "Rule":
        rule_type = str(value.get("type", "include")).strip().lower()
        if rule_type not in {"include", "exclude"}:
            raise ValueError(f"unknown rule type: {rule_type}")
        return cls(
            type=rule_type,
            keyword=clean_text(value.get("keyword", "")),
            weight=int(value.get("weight", 0)),
            enabled=_as_bool(value.get("enabled", True)),
            note=clean_text(value.get("note", "")),
        )


@dataclass(frozen=True)
class FilterResult:
    job: Job
    score: int
    matched_keywords: tuple[str, ...]


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "off", ""}
    return bool(value)


def _contains(text: str, keyword: str) -> bool:
    text_folded = text.casefold()
    keyword_folded = keyword.casefold()
    if not keyword_folded:
        return False
    # Short ASCII tokens such as AI, ML, PM, and PO should not match e-mail or
    # unrelated words.  Word boundaries also preserve matches around '/', '-'.
    if re.fullmatch(r"[a-z0-9]+", keyword_folded) and len(keyword_folded) <= 3:
        return re.search(rf"(?<![a-z0-9]){re.escape(keyword_folded)}(?![a-z0-9])", text_folded) is not None
    return keyword_folded in text_folded


class JobFilter:
    def __init__(
        self,
        rules: Iterable[Rule | Mapping[str, Any]] | None = None,
        *,
        strict_entry_level: bool = False,
        allow_bachelor_or_lower: bool = False,
        min_score: int = 6,
    ) -> None:
        self.rules = [rule if isinstance(rule, Rule) else Rule.from_mapping(rule) for rule in (rules or [])]
        self.strict_entry_level = strict_entry_level
        self.allow_bachelor_or_lower = allow_bachelor_or_lower
        self.min_score = int(min_score)
        self.entry_keywords = {
            rule.keyword.casefold()
            for rule in self.rules
            if rule.enabled and rule.type == "include" and rule.keyword.casefold() in {"신입", "junior", "entry", "경력무관", "new graduate"}
        }
        self.role_keywords = {
            rule.keyword
            for rule in self.rules
            if rule.enabled
            and rule.type == "include"
            and rule.keyword.casefold() not in {"신입", "junior", "entry", "경력무관", "new graduate", "공채"}
        }

    def score(self, job: Job) -> tuple[int, list[str]]:
        text = " ".join(
            clean_text(value)
            for value in (job.company, job.title, job.position, job.experience, job.employment_type, job.raw_text)
            if clean_text(value)
        )
        score = 0
        matched: list[str] = []
        for rule in self.rules:
            if not rule.enabled or not rule.keyword or not _contains(text, rule.keyword):
                continue
            score += rule.weight
            matched.append(rule.keyword)
        return score, matched

    def evaluate(self, job: Job) -> FilterResult:
        score, matched = self.score(job)
        job.score = score
        job.matched_keywords = matched
        return FilterResult(job=job, score=score, matched_keywords=tuple(matched))

    def include(self, job: Job) -> bool:
        result = self.evaluate(job)
        # A keyword that appears only in an ad label, company description, or
        # surrounding search-page markup must not turn an unrelated role into
        # an AI/ML job.  The role itself has to state an AI/ML specialty.
        role_text = " ".join((job.title, job.position))
        if self.role_keywords and not any(_contains(role_text, keyword) for keyword in self.role_keywords):
            return False
        if result.score < self.min_score:
            return False
        if self.strict_entry_level:
            text = " ".join((job.title, job.position, job.experience, job.raw_text)).casefold()
            if not any(_contains(text, keyword) for keyword in self.entry_keywords):
                return False
        if self.allow_bachelor_or_lower and not _allows_bachelor_or_lower(job):
            return False
        return True

    def filter_jobs(self, jobs: Iterable[Job]) -> list[Job]:
        return [job for job in jobs if self.include(job)]


def _allows_bachelor_or_lower(job: Job) -> bool:
    """Return true when the posting is open to bachelor's-or-lower applicants."""

    text = " ".join((job.title, job.position, job.experience, job.raw_text)).casefold()
    is_open_to_bachelor_or_lower = bool(
        re.search(r"학력\s*무관|고졸|초대졸|(?<!초)대졸|학사|4\s*년제|대학교\s*졸업", text)
    )
    requires_graduate_degree = bool(
        re.search(r"(?:석사|박사|대학원)\s*(?:이상|필수|졸업|학위\s*소지|학위자)", text)
    )
    return is_open_to_bachelor_or_lower and not requires_graduate_degree
