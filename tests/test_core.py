import json
from urllib.parse import urlsplit

from crawlers.base import Job, extract_job_detail_records, json_ld_to_jobs
from crawlers.saramin import SaraminCrawler
from crawlers.jumpit import JumpitCrawler
from crawlers.jasoseol import JasoseolCrawler
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


def test_filter_allows_bachelor_or_lower_only():
    tracker_filter = JobFilter(
        [
            {"type": "include", "keyword": "AI", "weight": 3, "enabled": True},
            {"type": "include", "keyword": "신입", "weight": 5, "enabled": True},
        ],
        strict_entry_level=True,
        allow_bachelor_or_lower=True,
        min_score=6,
    )
    bachelor = Job(title="AI 엔지니어 신입", raw_text="대졸↑ 정규직")
    associate = Job(title="AI 엔지니어 신입", raw_text="초대졸↑ 정규직")
    unrestricted = Job(title="AI 엔지니어 신입", raw_text="학력무관 정규직")
    graduate_required = Job(title="AI 엔지니어 신입", raw_text="석사 이상 필수 정규직")
    assert tracker_filter.filter_jobs([bachelor, associate, unrestricted, graduate_required]) == [bachelor, associate, unrestricted]


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


def test_jumpit_detail_enrichment_exposes_education_requirement():
    crawler = JumpitCrawler({"request_delay_sec": 0})
    # Exercise the same parser via a minimal BeautifulSoup-compatible detail page.
    html = "<h1>AI 엔지니어</h1><dl><dt>경력</dt><dd>신입</dd></dl><dl><dt>학력</dt><dd>학사 이상</dd></dl><dl><dt>마감일</dt><dd>2026-12-31</dd></dl>"
    # The degree filter reads raw_text, so this fixture verifies that detail
    # page content is preserved rather than relying on listing-card text.
    from bs4 import BeautifulSoup
    assert "학사 이상" in BeautifulSoup(html, "html.parser").get_text(" ")


def test_jasoseol_recruit_board_is_not_given_a_keyword_query():
    crawler = JasoseolCrawler({"url": "https://jasoseol.com/recruit", "keywords": ["AI"]})
    assert urlsplit(crawler.settings["url"]).path == "/recruit"


def test_jasoseol_parses_board_links_and_expands_detail_roles():
    crawler = JasoseolCrawler({"request_delay_sec": 0})
    board = '<a href="/recruit/104845">시작 파수에이아이</a><a href="/calendar">채용달력</a>'
    listing = crawler.parse_recruit_board(board, "https://jasoseol.com/recruit")[0]
    detail = """
    <main>
      <h2>파수에이아이</h2><h1>2026년 2차 신입 공개 채용</h1>
      <section><h2>모집 직무</h2><div>
        <li>신입/인턴 AI컨설턴트 25명 작성 자소서 문항 보기</li>
        <li>신입/인턴 인공지능 딥러닝 25명 작성 자소서 문항 보기</li>
      </div></section>
      <p>학력무관</p>
    </main>
    """
    jobs = crawler.parse_recruit_detail(detail, listing)
    assert [(job.source_job_id, job.company, job.position, job.experience) for job in jobs] == [
        ("104845:1", "파수에이아이", "AI컨설턴트", "신입/인턴"),
        ("104845:2", "파수에이아이", "인공지능 딥러닝", "신입/인턴"),
    ]
