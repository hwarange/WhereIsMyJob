"""CLI entry point for the WhereIsMyJob tracker."""

from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from typing import Any, Mapping

from crawlers import CompanySitesCrawler, JasoseolCrawler, JobKoreaCrawler, JumpitCrawler, SaraminCrawler, WantedCrawler
from crawlers.base import Job
from services.config import enabled, load_config, load_dotenv_if_available
from services.dedupe import dedupe_jobs
from services.filtering import JobFilter
from services.google_sheets import GoogleSheetsService, now_iso
from services.notify import notify_slack
from services.site_data import export_site_data

logger = logging.getLogger("job_tracker")


def _setup_logging() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s - %(message)s")


def _source_specs(config: Mapping[str, Any], source_filter: str | None) -> list[tuple[str, Any, dict[str, Any]]]:
    configured = config.get("sources", {}) if isinstance(config.get("sources", {}), Mapping) else {}
    aliases = {
        "saramin": "saramin_api",
        "saramin_api": "saramin_api",
        "jasoseol": "jasoseol",
        "jobkorea": "jobkorea",
        "jumpit": "jumpit",
        "company_sites": "company_sites",
        "company_site": "company_sites",
        "wanted": "wanted",
    }
    classes = {
        "saramin_api": SaraminCrawler,
        "jasoseol": JasoseolCrawler,
        "jobkorea": JobKoreaCrawler,
        "jumpit": JumpitCrawler,
        "company_sites": CompanySitesCrawler,
        "wanted": WantedCrawler,
    }
    specs: list[tuple[str, Any, dict[str, Any]]] = []
    for name, crawler_class in classes.items():
        settings = dict(configured.get(name, {}) or {})
        if not settings.get("enabled", False):
            continue
        if source_filter and aliases.get(source_filter, source_filter) != name:
            continue
        specs.append((name, crawler_class, settings))
    return specs


def _source_label(name: str) -> str:
    return "saramin" if name == "saramin_api" else name


def run_tracker(
    config_path: str,
    *,
    dry_run: bool = False,
    source_filter: str | None = None,
    export_json: str | None = None,
) -> dict[str, Any]:
    """Run enabled crawlers and return a JSON-serializable execution summary."""

    load_dotenv_if_available()
    config = load_config(config_path)
    sheet_service: GoogleSheetsService | None = None
    sheet_enabled_sources: set[str] | None = None
    if not dry_run and not export_json:
        sheet_service = GoogleSheetsService.from_env()
        sheet_service.ensure_worksheets()
        try:
            sheet_source_rows = sheet_service.load_sources()
            if sheet_source_rows:
                sheet_enabled_sources = {
                    "saramin_api" if str(row.get("source", "")).strip().lower() == "saramin" else str(row.get("source", "")).strip().lower()
                    for row in sheet_source_rows
                    if enabled(row.get("enabled", True))
                }
        except Exception as exc:
            logger.warning("Could not load Sources; using config source settings: %s", exc)

    company_targets = (config.get("sources", {}).get("company_sites", {}) or {}).get("targets", [])
    if sheet_service is not None and enabled((config.get("sources", {}).get("company_sites", {}) or {}).get("from_sheet", True)):
        try:
            sheet_targets = sheet_service.load_company_targets()
            if sheet_targets:
                company_targets = sheet_targets
        except Exception as exc:
            logger.warning("Could not load Company_Targets; using config targets: %s", exc)

    all_jobs: list[Job] = []
    source_runs: list[dict[str, Any]] = []
    started_at = time.monotonic()
    for name, crawler_class, settings in _source_specs(config, source_filter):
        if sheet_enabled_sources is not None and name not in sheet_enabled_sources:
            logger.info("%s: disabled by Sources sheet", name)
            continue
        if name == "company_sites":
            crawler = crawler_class(settings, targets=company_targets)
        else:
            crawler = crawler_class(settings)
        source_started = time.monotonic()
        try:
            jobs = crawler.collect()
            all_jobs.extend(jobs)
            source_runs.append({
                "source": _source_label(name),
                "status": "success",
                "fetched_count": len(jobs),
                "error_message": "",
                "duration_sec": round(time.monotonic() - source_started, 2),
            })
            logger.info("%s: collected %d jobs", name, len(jobs))
        except Exception as exc:
            logger.exception("%s crawler failed; continuing with other sources", name)
            source_runs.append({
                "source": _source_label(name),
                "status": "error",
                "fetched_count": 0,
                "error_message": str(exc),
                "duration_sec": round(time.monotonic() - source_started, 2),
            })

    unique_jobs = dedupe_jobs(all_jobs)
    filter_config = config.get("filter", {}) or {}
    rules = filter_config.get("rules", [])
    if sheet_service is not None:
        try:
            sheet_rules = sheet_service.load_search_rules()
            if sheet_rules:
                rules = sheet_rules
        except Exception as exc:
            logger.warning("Could not load Search_Rules; using config rules: %s", exc)
    job_filter = JobFilter(
        rules,
        strict_entry_level=enabled(filter_config.get("strict_entry_level", False)),
        allow_bachelor_or_lower=enabled(filter_config.get("allow_bachelor_or_lower", False)),
        min_score=int(filter_config.get("min_score", 6)),
    )
    filtered_jobs = job_filter.filter_jobs(unique_jobs)
    errors = [run for run in source_runs if run["status"] == "error"]
    status = "error" if errors and not all_jobs else ("partial" if errors else "success")
    summary: dict[str, Any] = {
        "run_at": now_iso(),
        "status": status,
        "fetched_count": len(all_jobs),
        "unique_count": len(unique_jobs),
        "filtered_count": len(filtered_jobs),
        "new_count": 0,
        "updated_count": 0,
        "duration_sec": round(time.monotonic() - started_at, 2),
        "sources": source_runs,
        "errors": [run["error_message"] for run in errors],
    }

    if dry_run or export_json:
        if export_json:
            export_site_data(filtered_jobs, export_json, summary)
            summary["export_json"] = export_json
        if dry_run:
            summary["jobs"] = [job.to_dict() for job in filtered_jobs]
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return summary

    assert sheet_service is not None
    raw_counts = sheet_service.upsert_raw_jobs(unique_jobs)
    tracker_counts = sheet_service.upsert_tracker_jobs(filtered_jobs)
    summary["new_count"] = tracker_counts["new_count"]
    summary["updated_count"] = tracker_counts["updated_count"]
    logger.info("Sheets updated: raw=%s tracker=%s", raw_counts, tracker_counts)

    sheet_service.append_run_log({
        "run_at": summary["run_at"],
        "status": summary["status"],
        "source": source_filter or "all",
        "fetched_count": summary["fetched_count"],
        "filtered_count": summary["filtered_count"],
        "new_count": summary["new_count"],
        "updated_count": summary["updated_count"],
        "error_message": " | ".join(summary["errors"]),
        "duration_sec": summary["duration_sec"],
    })
    notifications = config.get("notifications", {}) or {}
    slack = notifications.get("slack", {}) or {}
    if enabled(slack.get("enabled", False)):
        notify_slack(filtered_jobs, slack.get("webhook_url"))
    return summary


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Collect entry-level AI/ML job postings")
    parser.add_argument("--config", default="config.yaml", help="YAML configuration path (default: config.yaml)")
    parser.add_argument("--dry-run", action="store_true", help="Collect and filter without writing persistent output")
    parser.add_argument("--source", help="Run only one source: saramin, jasoseol, jobkorea, jumpit, wanted, company_sites")
    parser.add_argument("--export-json", help="Write filtered jobs to a GitHub Pages JSON file")
    return parser


def main(argv: list[str] | None = None) -> int:
    _setup_logging()
    args = build_parser().parse_args(argv)
    try:
        run_tracker(args.config, dry_run=args.dry_run, source_filter=args.source, export_json=args.export_json)
        return 0
    except Exception as exc:
        logger.exception("Tracker run failed: %s", exc)
        return 1


if __name__ == "__main__":
    sys.exit(main())
