import json

from crawlers.base import Job
from services.dedupe import build_job_key, dedupe_jobs, normalize_url
from services.filtering import JobFilter
from services.site_data import export_site_data


def test_normalize_url_removes_tracking_parameters():
    assert normalize_url("https://Example.com/jobs/1/?utm_source=x&id=2#top") == "https://example.com/jobs/1?id=2"


def test_dedupe_prefers_source_id():
    first = Job(source="saramin", source_job_id="123", title="AI Engineer", url="https://one.example/1")
    second = Job(source="saramin", source_job_id="123", title="AI Engineer", url="https://two.example/2")
    assert build_job_key(first) == build_job_key(second)
    assert len(dedupe_jobs([first, second])) == 1


def test_filter_scores_entry_level_ai_job():
    job = Job(source="test", title="AI Engineer 신입", raw_text="Python, LLM")
    tracker_filter = JobFilter(
        [
            {"type": "include", "keyword": "AI Engineer", "weight": 5, "enabled": True},
            {"type": "include", "keyword": "신입", "weight": 5, "enabled": True},
        ],
        strict_entry_level=True,
        min_score=6,
    )
    assert tracker_filter.filter_jobs([job]) == [job]
    assert job.score == 10


def test_site_export_preserves_existing_management_fields(tmp_path):
    path = tmp_path / "jobs.json"
    job = Job(source="test", title="AI Engineer", job_key="abc")
    export_site_data([job], path)
    saved = json.loads(path.read_text(encoding="utf-8"))
    saved["jobs"][0]["status"] = "지원완료"
    saved["jobs"][0]["memo"] = "포트폴리오 제출"
    path.write_text(json.dumps(saved, ensure_ascii=False), encoding="utf-8")
    payload = export_site_data([job], path)
    assert payload["jobs"][0]["status"] == "지원완료"
    assert payload["jobs"][0]["memo"] == "포트폴리오 제출"
