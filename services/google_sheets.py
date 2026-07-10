"""Google Sheets persistence with idempotent, user-safe upserts."""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Mapping

from crawlers.base import Job

TRACKER_SHEET = "Tracker"
RAW_SHEET = "Raw_Jobs"
RULES_SHEET = "Search_Rules"
SOURCES_SHEET = "Sources"
TARGETS_SHEET = "Company_Targets"
RUN_LOG_SHEET = "Run_Log"

TRACKER_HEADERS = [
    "게시일",
    "마감일",
    "기업명",
    "공고명",
    "직무",
    "근무지",
    "링크",
    "출처",
    "상태",
    "메모",
    "job_key",
    "first_seen_at",
    "last_seen_at",
    "updated_at",
    "score",
    "matched_keywords",
]
RAW_HEADERS = [
    "collected_at",
    "source",
    "source_job_id",
    "company",
    "title",
    "position",
    "location",
    "url",
    "posted_at",
    "deadline",
    "experience",
    "employment_type",
    "raw_text",
    "job_key",
]
RULE_HEADERS = ["type", "keyword", "weight", "enabled", "note"]
SOURCE_HEADERS = ["source", "enabled", "method", "url", "frequency", "note"]
TARGET_HEADERS = ["company", "enabled", "url", "query_hint", "note"]
RUN_LOG_HEADERS = [
    "run_at",
    "status",
    "source",
    "fetched_count",
    "filtered_count",
    "new_count",
    "updated_count",
    "error_message",
    "duration_sec",
]

WORKSHEET_HEADERS = {
    TRACKER_SHEET: TRACKER_HEADERS,
    RAW_SHEET: RAW_HEADERS,
    RULES_SHEET: RULE_HEADERS,
    SOURCES_SHEET: SOURCE_HEADERS,
    TARGETS_SHEET: TARGET_HEADERS,
    RUN_LOG_SHEET: RUN_LOG_HEADERS,
}


def now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _as_bool(value: Any) -> bool:
    if isinstance(value, str):
        return value.strip().lower() not in {"false", "0", "no", "off", "n", ""}
    return bool(value)


def _job_value(job: Job | Mapping[str, Any], key: str, default: Any = "") -> Any:
    if isinstance(job, Mapping):
        return job.get(key, default)
    return getattr(job, key, default)


def _column_letter(index: int) -> str:
    result = ""
    while index:
        index, remainder = divmod(index - 1, 26)
        result = chr(65 + remainder) + result
    return result


class GoogleSheetsService:
    """A thin gspread adapter designed to be easy to fake in unit tests."""

    def __init__(self, spreadsheet: Any) -> None:
        self.spreadsheet = spreadsheet

    @classmethod
    def from_env(cls) -> "GoogleSheetsService":
        sheet_id = os.getenv("GOOGLE_SHEET_ID", "").strip()
        raw_credentials = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "").strip()
        if not sheet_id:
            raise RuntimeError("GOOGLE_SHEET_ID is not set")
        if not raw_credentials:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON is not set")
        try:
            credential_path = Path(raw_credentials)
            if credential_path.exists():
                info = json.loads(credential_path.read_text(encoding="utf-8"))
            else:
                info = json.loads(raw_credentials)
        except (OSError, json.JSONDecodeError) as exc:
            raise RuntimeError("GOOGLE_SERVICE_ACCOUNT_JSON must contain valid service-account JSON or a file path") from exc
        try:
            import gspread
            from google.oauth2.service_account import Credentials
        except ImportError as exc:  # pragma: no cover - dependency install issue
            raise RuntimeError("gspread and google-auth are required for Sheets sync") from exc
        scopes = [
            "https://www.googleapis.com/auth/spreadsheets",
            "https://www.googleapis.com/auth/drive.file",
        ]
        credentials = Credentials.from_service_account_info(info, scopes=scopes)
        return cls(gspread.authorize(credentials).open_by_key(sheet_id))

    def _worksheet(self, name: str) -> Any:
        try:
            return self.spreadsheet.worksheet(name)
        except Exception as exc:
            raise RuntimeError(f"worksheet not found: {name}") from exc

    def ensure_worksheets(self) -> None:
        for name, headers in WORKSHEET_HEADERS.items():
            try:
                worksheet = self.spreadsheet.worksheet(name)
            except Exception:
                worksheet = self.spreadsheet.add_worksheet(title=name, rows=max(100, 1000 if name in {TRACKER_SHEET, RAW_SHEET} else 100), cols=len(headers))
            try:
                first_row = worksheet.row_values(1)
            except Exception:
                values = worksheet.get_all_values()
                first_row = values[0] if values else []
            if first_row[: len(headers)] != headers:
                self._update_row(worksheet, 1, headers)

    def load_sheet_records(self, sheet_name: str) -> list[dict[str, Any]]:
        worksheet = self._worksheet(sheet_name)
        try:
            records = worksheet.get_all_records()
        except Exception:
            values = worksheet.get_all_values()
            if not values:
                return []
            headers = values[0]
            records = [dict(zip(headers, row)) for row in values[1:]]
        return [dict(record) for record in records if any(str(value).strip() for value in record.values())]

    def load_company_targets(self) -> list[dict[str, Any]]:
        targets = []
        for row in self.load_sheet_records(TARGETS_SHEET):
            if _as_bool(row.get("enabled", True)) and row.get("url"):
                targets.append(row)
        return targets

    def load_search_rules(self) -> list[dict[str, Any]]:
        """Return configured rule rows from Search_Rules, if the sheet has any."""

        return [
            row
            for row in self.load_sheet_records(RULES_SHEET)
            if row.get("keyword")
        ]

    def load_sources(self) -> list[dict[str, Any]]:
        """Return configured source rows for optional sheet-driven operations."""

        return [
            row
            for row in self.load_sheet_records(SOURCES_SHEET)
            if row.get("source")
        ]

    def _update_row(self, worksheet: Any, row_number: int, values: list[Any]) -> None:
        end_column = _column_letter(len(values))
        range_name = f"A{row_number}:{end_column}{row_number}"
        try:
            worksheet.update(range_name, [values], value_input_option="USER_ENTERED")
        except TypeError:
            # Older gspread versions use update(values, range_name).
            worksheet.update([values], range_name)

    def _append_row(self, worksheet: Any, values: list[Any]) -> None:
        try:
            worksheet.append_row(values, value_input_option="USER_ENTERED")
        except TypeError:
            worksheet.append_row(values)

    def upsert_raw_jobs(self, jobs: Iterable[Job | Mapping[str, Any]]) -> dict[str, int]:
        worksheet = self._worksheet(RAW_SHEET)
        records = self.load_sheet_records(RAW_SHEET)
        existing_rows = {str(row.get("job_key", "")): index + 2 for index, row in enumerate(records) if row.get("job_key")}
        counts = {"new_count": 0, "updated_count": 0}
        for job in jobs:
            row = [
                _job_value(job, "collected_at") or now_iso(),
                _job_value(job, "source"),
                _job_value(job, "source_job_id"),
                _job_value(job, "company"),
                _job_value(job, "title"),
                _job_value(job, "position"),
                _job_value(job, "location"),
                _job_value(job, "url"),
                _job_value(job, "posted_at"),
                _job_value(job, "deadline"),
                _job_value(job, "experience"),
                _job_value(job, "employment_type"),
                _job_value(job, "raw_text"),
                _job_value(job, "job_key"),
            ]
            key = str(_job_value(job, "job_key"))
            if key and key in existing_rows:
                self._update_row(worksheet, existing_rows[key], row)
                counts["updated_count"] += 1
            else:
                self._append_row(worksheet, row)
                counts["new_count"] += 1
        return counts

    def upsert_tracker_jobs(self, filtered_jobs: Iterable[Job | Mapping[str, Any]]) -> dict[str, int]:
        worksheet = self._worksheet(TRACKER_SHEET)
        records = self.load_sheet_records(TRACKER_SHEET)
        existing_rows = {str(row.get("job_key", "")): (index + 2, row) for index, row in enumerate(records) if row.get("job_key")}
        counts = {"new_count": 0, "updated_count": 0}
        current_time = now_iso()
        for job in filtered_jobs:
            key = str(_job_value(job, "job_key"))
            previous = existing_rows.get(key)
            previous_row = previous[1] if previous else {}
            first_seen = previous_row.get("first_seen_at") or current_time
            status = previous_row.get("상태", "") if previous else "신규"
            memo = previous_row.get("메모", "") if previous else ""
            row = [
                _job_value(job, "posted_at"),
                _job_value(job, "deadline"),
                _job_value(job, "company"),
                _job_value(job, "title"),
                _job_value(job, "position"),
                _job_value(job, "location"),
                _job_value(job, "url"),
                _job_value(job, "source"),
                status,
                memo,
                key,
                first_seen,
                current_time,
                current_time,
                _job_value(job, "score", 0),
                ", ".join(_job_value(job, "matched_keywords", []) or []),
            ]
            if previous:
                self._update_row(worksheet, previous[0], row)
                counts["updated_count"] += 1
            else:
                self._append_row(worksheet, row)
                counts["new_count"] += 1
        return counts

    def append_run_log(self, log: Mapping[str, Any]) -> None:
        worksheet = self._worksheet(RUN_LOG_SHEET)
        row = [log.get(header, "") for header in RUN_LOG_HEADERS]
        self._append_row(worksheet, row)
