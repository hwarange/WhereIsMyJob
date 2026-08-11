import json

from crawlers.base import Job, extract_job_detail_records, json_ld_to_jobs
from crawlers.saramin import SaraminCrawler
from crawlers.jobkorea import JobKoreaCrawler
from crawlers.jobplanet import JobPlanetCrawler
from crawlers.jumpit import JumpitCrawler
from crawlers.jasoseol import JasoseolCrawler
from crawlers.wanted import WantedCrawler
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


def test_filter_excludes_only_graduate_degree_requirements():
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
    # Jasoseol detail pages often omit education info; those must stay visible.
    unspecified = Job(title="AI 엔지니어 신입", raw_text="자기소개서 제출 정규직")
    graduate_required = Job(title="AI 엔지니어 신입", raw_text="석사 이상 필수 정규직")
    graduate_arrow = Job(title="AI 엔지니어 신입", raw_text="석사↑ 정규직")
    assert tracker_filter.filter_jobs(
        [bachelor, associate, unrestricted, unspecified, graduate_required, graduate_arrow]
    ) == [bachelor, associate, unrestricted, unspecified]


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


def test_detail_link_extractor_matches_query_string_ids():
    html = """
    <li><a href="/career/job-detail?job_id=7816881003">토스뱅크 Server Developer 채용 연계형 인턴십</a></li>
    <li><a href="/career/article/52165">Toss Income Alignment Day</a></li>
    """
    jobs = extract_job_detail_records(
        html,
        "https://toss.im/career",
        "company_sites",
        detail_url_pattern=r"/career/job-detail\?job_id=(?P<id>\d+)",
    )
    assert [(job.source_job_id, job.title) for job in jobs] == [
        ("7816881003", "토스뱅크 Server Developer 채용 연계형 인턴십")
    ]


def test_detail_link_extractor_keeps_sibling_card_text_separate():
    # Cards without <li>/<article> wrappers share one container; one card's
    # "신입" must not leak into every sibling posting's raw_text.
    html = """
    <div>
      <a href="/jobs/P-1?page=1">Data Scientist (경력) 영입 # Algorithm/ML</a>
      <a href="/jobs/P-2?page=1">LLM Research Engineer (신입/경력) 영입 # Algorithm/ML</a>
    </div>
    """
    jobs = extract_job_detail_records(
        html,
        "https://careers.kakao.com/jobs",
        "company_sites",
        detail_url_pattern=r"/jobs/(?P<id>P-\d+)",
    )
    assert [job.source_job_id for job in jobs] == ["P-1", "P-2"]
    assert "신입" not in jobs[0].raw_text
    assert "신입" in jobs[1].raw_text


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


def test_jobkorea_board_rows_parse_both_row_styles():
    crawler = JobKoreaCrawler({"request_delay_sec": 0})
    html = """
    <li class="devloopArea">
      <div class="job-recommendation-details">
        <span class="company-name"><a href="/Recruit/GI_Read/111?sc=1">커스텀파츠</a></span>
        <p class="title"><a href="/Recruit/GI_Read/111?sc=1">2D, 3D, AI 머신비전 엔지니어(신입)</a></p>
        <div class="info">
          <ul class="tags-wrapper">
            <li class="tag">신입</li><li class="tag">대졸↑</li><li class="tag">정규직 외</li><li class="tag">대구 달서구 외</li>
          </ul>
          <div class="deadline">D-19</div>
        </div>
      </div>
    </li>
    <li class="devloopArea">
      <div class="company"><span class="name"><a href="/Recruit/GI_Read/222?sn=1"><span class="logo"><img/></span>엠비씨아카데미</a></span></div>
      <div class="description"><a href="/Recruit/GI_Read/222?sn=1"><span class="text">AI 데이터 분석 신입 채용</span>
        <span class="dday"><span class="deadLine">~09/13</span></span></a></div>
    </li>
    <li class="devloopArea"><a href="/goodjob/Tip">취업팁</a></li>
    """
    jobs = crawler.parse_list_html(html, "https://www.jobkorea.co.kr/recruit/joblist")
    assert [(job.source_job_id, job.company, job.title) for job in jobs] == [
        ("111", "커스텀파츠", "2D, 3D, AI 머신비전 엔지니어(신입)"),
        ("222", "엠비씨아카데미", "AI 데이터 분석 신입 채용"),
    ]
    assert jobs[0].experience == "신입"
    assert jobs[0].employment_type == "정규직 외"
    assert jobs[0].deadline == "D-19"
    assert "대졸↑" in jobs[0].raw_text
    assert jobs[1].deadline == "~09/13"
    assert jobs[0].url == "https://www.jobkorea.co.kr/Recruit/GI_Read/111"


def test_jobplanet_search_item_maps_to_normalized_job():
    crawler = JobPlanetCrawler({"request_delay_sec": 0})
    item = {
        "id": 1540166,
        "company": {"name": "(주)딥로딩", "review_score": "4.8"},
        "jd": {
            "title": "AI 개발자 인턴 채용(인턴 종료 후 채용연계)",
            "url": "/companies/403705/job_postings/1540166/ai-slug/%EB%94%A5%EB%A1%9C%EB%94%A9?_rs_act=search&job_key=job_postings",
            "end_at": "2026-08-14T23:59:59.000+09:00",
            "cities": ["서울"],
            "job_type": {"name": "계약직", "id": 4},
            "career_text": "신입",
            "recruitment_types": [{"name": "신입", "id": 1}],
            "level1_occupations": [{"name": "개발", "id": 11600}],
            "level2_occupations": [{"name": "인공지능/머신러닝", "id": 11913}],
        },
    }
    job = crawler.search_item_to_job(item)
    assert job.source_job_id == "1540166"
    assert job.company == "(주)딥로딩"
    assert job.experience == "신입"
    assert job.employment_type == "계약직"
    assert job.deadline == "2026-08-14"
    assert job.location == "서울"
    # Tracking parameters must not survive into the posting URL.
    assert job.url == "https://www.jobplanet.co.kr/companies/403705/job_postings/1540166/ai-slug/%EB%94%A5%EB%A1%9C%EB%94%A9"
    assert "인공지능/머신러닝" in job.raw_text


def test_jobplanet_browser_headers_default():
    crawler = JobPlanetCrawler({})
    assert crawler.settings["headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert "Referer" in crawler.settings["headers"]


def test_jumpit_api_position_maps_to_normalized_job():
    crawler = JumpitCrawler({"request_delay_sec": 0})
    item = {
        "id": 54709573,
        "title": "ML Systems Runtime Engineer [신입/병특]",
        "companyName": "보스반도체",
        "jobCategory": "devops/시스템 엔지니어",
        "techStacks": ["C++", "Python"],
        "newcomer": True,
        "minCareer": 0,
        "maxCareer": 3,
        "locations": ["경기 성남시 분당구"],
        "alwaysOpen": False,
        "closedAt": "2026-08-30T23:59:59",
    }
    job = crawler.position_to_job(item)
    assert job.source_job_id == "54709573"
    assert job.company == "보스반도체"
    # The API wraps matched keywords in <span> tags; they must not survive.
    highlighted = crawler.position_to_job({"id": 3, "title": "[<span>AI</span> Vision Engineer] YOLO 기반", "newcomer": True})
    assert highlighted.title == "[AI Vision Engineer] YOLO 기반"
    assert job.experience == "신입"
    assert job.url == "https://jumpit.saramin.co.kr/position/54709573"
    assert job.deadline == "2026-08-30T23:59:59"
    assert "Python" in job.raw_text


def test_jumpit_experienced_position_keeps_career_range():
    crawler = JumpitCrawler({"request_delay_sec": 0})
    job = crawler.position_to_job({"id": 1, "title": "백엔드", "newcomer": False, "minCareer": 5, "maxCareer": 15})
    assert job.experience == "경력 5~15년"


def test_jumpit_detail_merge_exposes_education_requirement():
    crawler = JumpitCrawler({"request_delay_sec": 0})
    job = crawler.position_to_job({"id": 2, "title": "웹 개발자 채용 (신입)", "newcomer": True, "minCareer": 0})
    crawler.merge_detail(job, {
        "qualifications": "• 신입\n• 대학졸업(2,3년)이상",
        "responsibility": "• 자사 웹 서비스 제작",
        "location": "서울 강남구",
    })
    # The degree filter reads raw_text, so detail requirements must land there.
    assert "대학졸업" in job.raw_text
    assert job.location == "서울 강남구"


def test_jasoseol_defaults_to_browser_headers_without_playwright():
    crawler = JasoseolCrawler({})
    assert crawler.settings["headers"]["User-Agent"].startswith("Mozilla/5.0")
    assert crawler.settings["use_playwright"] is False


def test_jasoseol_builds_paginated_search_urls():
    crawler = JasoseolCrawler({})
    assert crawler._page_url("https://jasoseol.com/search", 1) == "https://jasoseol.com/search"
    assert crawler._page_url("https://jasoseol.com/search", 2) == "https://jasoseol.com/search?page=2"
    assert crawler._page_url("https://jasoseol.com/search?sort=latest", 3) == "https://jasoseol.com/search?sort=latest&page=3"


def test_jasoseol_role_rows_accept_employment_type_prefixes():
    assert JasoseolCrawler._role_from_row("계약직 AI 마케팅 (GEO) (Junior) 0명 작성 자소서 문항 보기") == ("계약직", "AI 마케팅 (GEO) (Junior)")
    assert JasoseolCrawler._role_from_row("인턴 AI 마케팅 (GEO) (Assistant) 2명 작성 자소서 문항 보기") == ("인턴", "AI 마케팅 (GEO) (Assistant)")
    assert JasoseolCrawler._role_from_row("신입 / 경력 데이터 엔지니어 12명 작성") == ("신입 / 경력", "데이터 엔지니어")


def test_jasoseol_parses_board_links_and_expands_detail_roles():
    crawler = JasoseolCrawler({"request_delay_sec": 0})
    search = """
    <a data-sentry-component="EmploymentCompanyCard" href="/recruit/104845">
      <h5>파수에이아이</h5><h4>2026년 2차 신입 공개 채용</h4>
      <div class="line-clamp-1">AI컨설턴트, 인공지능 딥러닝</div>
      <div data-sentry-component="CompanyEmploymentType"><span>중견기업</span><span>신입</span></div>
      <div data-sentry-component="EmploymentPeriod">2026년 7월 1일 ~ 2026년 7월 20일</div>
    </a><a href="/calendar">채용달력</a>
    """
    listing = crawler.parse_search_html(search, "https://jasoseol.com/search")[0]
    assert (listing.company, listing.title, listing.position, listing.experience) == (
        "파수에이아이", "2026년 2차 신입 공개 채용", "AI컨설턴트, 인공지능 딥러닝", "신입"
    )
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


def test_wanted_parses_only_public_company_position_cards():
    crawler = WantedCrawler({"request_delay_sec": 0})
    html = """
    <h1>업스테이지</h1>
    <a href="/wd/362629" title="AI Research Engineer - LLM Eval">
      <span>개발</span><span>AI Research Engineer - LLM Eval</span>
      <span>경기</span><span>신입 이상</span><span>상시</span>
      <button data-position-id="362629" data-company-name="업스테이지"
              data-position-name="AI Research Engineer - LLM Eval"
              data-position-employment-type="regular"></button>
    </a>
    <a href="/wd/123456" title="메뉴 링크">메뉴</a>
    <a href="/company/16049">기업 소개</a>
    """
    jobs = crawler.parse_company_html(html, "https://www.wanted.co.kr/company/16049")
    assert [(job.source_job_id, job.company, job.title, job.location, job.experience, job.deadline) for job in jobs] == [
        ("362629", "업스테이지", "AI Research Engineer - LLM Eval", "경기", "신입 이상", "상시")
    ]


def test_wanted_parses_public_listing_cards_with_company_and_experience():
    crawler = WantedCrawler({"request_delay_sec": 0, "method": "public_listings"})
    html = """
    <a href="/wd/371996">
      <span>합격보상금 100만원</span><span>백엔드 엔지니어(5년 이하)</span>
      <span>포스타입</span><span>서울 강남구 · 신입-경력 5년</span>
      <button data-position-id="371996" data-company-name="포스타입"
              data-position-name="백엔드 엔지니어(5년 이하)"
              data-position-employment-type="regular"></button>
    </a>
    <a href="/wd/999999">공고처럼 보이는 메뉴</a>
    """
    jobs = crawler.parse_listing_html(html, "https://www.wanted.co.kr/wdlist")
    assert [(job.source_job_id, job.company, job.title, job.location, job.experience) for job in jobs] == [
        ("371996", "포스타입", "백엔드 엔지니어(5년 이하)", "서울 강남구", "신입-경력 5년")
    ]
