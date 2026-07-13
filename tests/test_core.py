import json

from crawlers.base import Job, extract_job_detail_records, json_ld_to_jobs
from crawlers.saramin import SaraminCrawler
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


def test_filter_rejects_non_ai_role_with_ai_only_in_context():
    job = Job(title="시스템 엔지니어 신입", position="시스템 엔지니어", raw_text="AI Engineer 검색 결과")
    tracker_filter = JobFilter(
        [
            {"type": "include", "keyword": "AI", "weight": 3, "enabled": True},
            {"type": "include", "keyword": "신입", "weight": 5, "enabled": True},
        ],
        strict_entry_level=True,
        min_score=6,
    )
    assert tracker_filter.filter_jobs([job]) == []


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


def test_detail_link_extractor_rejects_menu_and_social_links():
    html = """
    <a href="/Recruit/GI_Read/123">AI Engineer 신입</a>
    <a href="/Recruit">채용 안내</a>
    <a href="https://youtube.com/@company">Company YouTube</a>
    """
    jobs = extract_job_detail_records(
        html,
        "https://www.jobkorea.co.kr/Search/",
        "jobkorea",
        detail_url_pattern=r"/Recruit/GI_Read/(?P<id>\d+)",
    )
    assert [(job.source_job_id, job.title) for job in jobs] == [("123", "AI Engineer 신입")]


def test_json_ld_requires_job_posting_type():
    html = '<script type="application/ld+json">{"@type":"Organization","title":"채용 안내"}</script>'
    assert json_ld_to_jobs(html, "https://example.com", "company_sites") == []


def test_saramin_public_search_parses_only_recruitment_cards():
    html = """
    <div class="item_recruit" value="12345">
      <div class="area_job"><h2 class="job_tit"><a href="/zf_user/jobs/relay/view?rec_idx=12345" title="AI Engineer 신입">AI Engineer 신입</a></h2></div>
      <div class="job_date"><span class="date">~ 08/31</span></div>
      <div class="job_condition">신입 · 서울</div><div class="job_sector">AI·ML</div><div class="corp_name">테스트 기업</div>
    </div>
    <div class="item_recruit" value="not-a-job"><a href="/notice">공지</a></div>
    """
    jobs = SaraminCrawler({"method": "public_search"}).parse_search_html(html, "https://www.saramin.co.kr")
    assert [(job.source_job_id, job.company, job.title) for job in jobs] == [("12345", "테스트 기업", "AI Engineer 신입")]
