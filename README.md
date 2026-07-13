# WhereIsMyJob

신입·Junior·Entry-level AI/ML 채용공고를 여러 공개 채용 페이지에서 수집해 GitHub Pages 대시보드에 누적하는 Python 자동 트래커입니다. 각 수집기는 독립적으로 실행되므로 한 사이트의 HTML 변경이나 일시적인 오류가 다른 사이트의 수집을 중단시키지 않습니다.

## 동작 흐름

1. 자소설·잡코리아·점핏·기업 채용 페이지의 공개 검색/채용 페이지를 수집합니다. 사람인 수집기는 현재 기본 비활성화되어 있습니다.
2. `Job` 표준 모델로 회사명·공고명·직무·근무지·링크·게시일·마감일·경력·고용형태·원문을 통일합니다.
3. AI/ML 및 신입 관련 키워드에는 가점을 주고 Senior/Lead/경력 연차/마케팅·영업 등에는 감점을 주어 `min_score` 이상만 Tracker에 반영합니다.
4. `source + source_job_id` → `source + 정규화 URL` → `회사 + 제목 + 마감일` 순으로 SHA-256 `job_key`를 만들어 중복을 제거합니다.
5. 필터된 공고는 `docs/data/jobs.json`으로 내보내지고, GitHub Pages 대시보드에서 상태와 메모를 관리할 수 있습니다.

## 파일 구성

```text
job_tracker.py                 # CLI 및 전체 실행 오케스트레이션
crawlers/
  base.py                      # Job 모델, 재시도, rate limit, robots.txt, HTML 공통 도구
  saramin.py                   # 사람인 공식 Open API
  jasoseol.py                  # 자소설 Playwright 우선 수집
  jobkorea.py                  # 잡코리아 검색 수집
  jumpit.py                    # 점핏 검색 수집
  company_sites.py             # Company_Targets 기반 기업 채용 페이지
services/
  config.py                    # YAML 설정과 기본 필터 규칙
  filtering.py                 # 키워드 점수 필터
  dedupe.py                    # URL 정규화 및 job_key 생성
  google_sheets.py             # 시트 생성, 원문/Tracker/로그 업서트
  notify.py                    # 선택적 Slack Webhook 알림
  site_data.py                 # GitHub Pages용 공고 JSON 내보내기
docs/                          # GitHub Pages 정적 대시보드
config.example.yaml            # 설정 예시
.env.example                   # 환경변수 이름 예시
requirements.txt
.github/workflows/job-tracker.yml
tests/test_core.py             # 네트워크 없는 핵심 로직 테스트
```

## 설치 및 로컬 실행

Python 3.11 이상을 권장합니다.

```bash
python -m venv .venv
# Windows PowerShell
.\.venv\Scripts\Activate.ps1
# macOS/Linux
# source .venv/bin/activate

python -m pip install -r requirements.txt
python -m playwright install chromium
Copy-Item config.example.yaml config.yaml       # macOS/Linux: cp config.example.yaml config.yaml
Copy-Item .env.example .env                     # macOS/Linux: cp .env.example .env
```

환경변수는 `.env` 또는 셸 환경에 넣습니다. `.env`, `config.yaml`은 Git에 커밋하지 마세요.

```env
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

드라이런은 대시보드 데이터에 쓰지 않고 필터링된 공고를 JSON으로 출력합니다.

```bash
python job_tracker.py --config config.yaml --dry-run
python job_tracker.py --config config.yaml --dry-run --source saramin
python job_tracker.py --config config.yaml --dry-run --source jumpit
python job_tracker.py --config config.yaml --export-json docs/data/jobs.json
python -m pytest -q
```

GitHub Pages 운영에는 `--export-json` 명령을 사용합니다. 이 명령은 Google Sheets 인증 없이 모든 `enabled: true` 소스를 실행합니다.

```bash
python job_tracker.py --config config.yaml
```

기본 설정에서는 사람인 수집을 실행하지 않습니다. 특정 사이트가 실패해도 다른 소스는 계속 실행되며 실패 내용은 로그와 `Run_Log`에 기록됩니다.

## GitHub Pages 대시보드

대시보드는 [docs/index.html](docs/index.html)과 `docs/data/jobs.json`으로 동작합니다. 공고 카드의 `+` 버튼을 눌러 상태와 메모를 관리할 수 있으며, 이 변경 사항은 현재 브라우저에 저장됩니다. 다른 기기에서도 보관하려면 **내 관리 내용 내려받기**로 JSON 파일을 저장하세요.

공유 상태/메모는 `docs/data/jobs.json`의 공고별 `status`, `memo`를 GitHub에서 편집해 관리할 수 있습니다. 다음 자동 수집에서도 같은 `job_key`의 값은 보존됩니다.

## 검증된 공고 출처

대시보드에는 실제 채용 상세 공고만 올립니다. 현재 자동 수집은 **사람인 공식 API**를 기준으로 하며, GitHub Repository Secret `SARAMIN_ACCESS_KEY`가 필요합니다. `Settings → Secrets and variables → Actions → New repository secret`에서 이름을 `SARAMIN_ACCESS_KEY`로 넣어 주세요.

잡코리아는 현재 `robots.txt`가 검색 수집을 허용하지 않아 비활성화했고, 잡플래닛은 공개 API/상세 공고 수집기를 제공하지 않아 포함하지 않았습니다. 자소설·점핏·기업 채용 페이지도 실제 상세 공고만 안정적으로 검증할 수 있을 때까지 비활성화합니다. 일반 메뉴·SNS·FAQ 링크를 공고로 처리하지 않습니다.

## 필터 설정

`config.yaml`의 `filter`에서 다음을 조정합니다.

```yaml
filter:
  strict_entry_level: false
  min_score: 6
  rules:
    - {type: include, keyword: "AI Engineer", weight: 5, enabled: true}
    - {type: include, keyword: "신입", weight: 5, enabled: true}
    - {type: exclude, keyword: "Senior", weight: -10, enabled: true}
```

`strict_entry_level: true`이면 신입·Junior·Entry·경력무관 키워드가 없는 공고를 제외합니다. `false`이면 AI/ML 관련성이 충분히 높은 공고를 포함할 수 있습니다. 키워드는 대소문자를 구분하지 않으며, `AI`, `ML`, `PM`, `PO` 같은 짧은 영문 토큰은 단어 단위로만 매칭합니다.

## GitHub Actions와 Pages 배포

1. 코드를 GitHub 저장소에 올립니다.
2. `Settings → Pages → Build and deployment`에서 **GitHub Actions**를 선택합니다.
3. `.github/workflows/job-tracker.yml`과 `.github/workflows/deploy-pages.yml`을 활성화합니다. 공고 수집을 위해 `SARAMIN_ACCESS_KEY`를 Repository Secret으로 추가하고, Slack 알림을 원하면 `SLACK_WEBHOOK_URL`도 추가하세요.
4. Actions 탭에서 **Collect AI job postings**을 수동 실행합니다. 공고 데이터가 자동 커밋되고 이어서 Pages가 배포됩니다.

수집 워크플로는 UTC 00, 06, 12, 18시에 실행되며 한국 시간으로 09, 15, 21, 03시입니다. `workflow_dispatch`로 수동 실행할 수도 있습니다. 수집 결과가 바뀌었을 때만 `docs/data/jobs.json`을 커밋합니다.

## 수집 안전 규칙

- 공개 페이지와 공식 API만 사용하며 로그인·CAPTCHA·접근 제한 우회는 하지 않습니다.
- 기본적으로 `robots.txt`를 확인하고, 호스트별 요청 간격과 User-Agent를 적용합니다.
- HTTP 일시 오류는 제한된 횟수만 재시도합니다.
- 사이트별 오류는 `Run_Log`에 남기고 전체 실행은 가능한 범위에서 계속합니다.
- 사이트 HTML 구조가 바뀌면 해당 `crawlers/<source>.py`의 선택자/응답 파서만 수정하면 됩니다.

## 운영 메모

GitHub Pages는 정적 사이트이므로 공고 수집은 GitHub Actions에서 수행합니다. 웹에서 바꾼 상태와 메모를 팀 전체에 실시간 저장하려면 별도 인증/DB가 필요합니다. 현재 구성은 개인 관리에는 브라우저 저장소, 공유 관리에는 GitHub의 JSON 편집을 사용합니다.
