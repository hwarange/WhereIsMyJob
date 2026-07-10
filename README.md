# WhereIsMyJob

신입·Junior·Entry-level AI/ML 채용공고를 여러 공개 채용 페이지에서 수집해 Google Sheets에 누적하는 Python 자동 트래커입니다. 각 수집기는 독립적으로 실행되므로 한 사이트의 HTML 변경이나 일시적인 오류가 다른 사이트의 수집을 중단시키지 않습니다.

## 동작 흐름

1. 자소설·잡코리아·점핏·기업 채용 페이지의 공개 검색/채용 페이지를 수집합니다. 사람인 수집기는 현재 기본 비활성화되어 있습니다.
2. `Job` 표준 모델로 회사명·공고명·직무·근무지·링크·게시일·마감일·경력·고용형태·원문을 통일합니다.
3. AI/ML 및 신입 관련 키워드에는 가점을 주고 Senior/Lead/경력 연차/마케팅·영업 등에는 감점을 주어 `min_score` 이상만 Tracker에 반영합니다.
4. `source + source_job_id` → `source + 정규화 URL` → `회사 + 제목 + 마감일` 순으로 SHA-256 `job_key`를 만들어 중복을 제거합니다.
5. `Raw_Jobs`에는 수집 원문을 보관하고, `Tracker`에는 필터 결과를 업서트합니다. 기존 Tracker 행의 `상태`와 `메모`는 자동 실행에서 보존됩니다.

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

환경변수는 `.env` 또는 셸 환경에 넣습니다. `.env`, `config.yaml`, 서비스 계정 JSON은 Git에 커밋하지 마세요.

```env
GOOGLE_SHEET_ID=Google_Sheet_ID
GOOGLE_SERVICE_ACCOUNT_JSON={"type":"service_account", ...}
SLACK_WEBHOOK_URL=https://hooks.slack.com/services/...
```

드라이런은 Google Sheets에 쓰지 않고 필터링된 공고를 JSON으로 출력합니다.

```bash
python job_tracker.py --config config.yaml --dry-run
python job_tracker.py --config config.yaml --dry-run --source saramin
python job_tracker.py --config config.yaml --dry-run --source jumpit
python -m pytest -q
```

일반 실행은 모든 `enabled: true` 소스를 실행합니다.

```bash
python job_tracker.py --config config.yaml
```

기본 설정에서는 사람인 수집을 실행하지 않습니다. 특정 사이트가 실패해도 다른 소스는 계속 실행되며 실패 내용은 로그와 `Run_Log`에 기록됩니다.

## Google Cloud와 Google Sheets 설정

1. [Google Cloud Console](https://console.cloud.google.com/)에서 프로젝트를 만듭니다.
2. `APIs & Services → Library`에서 **Google Sheets API**와 **Google Drive API**를 활성화합니다.
3. `IAM & Admin → Service Accounts`에서 서비스 계정을 만들고 JSON 키를 발급합니다.
4. Google Sheets를 만들고 서비스 계정의 `client_email` 주소를 편집자 권한으로 공유합니다.
5. 시트 ID를 `https://docs.google.com/spreadsheets/d/<여기>/edit`에서 복사해 `GOOGLE_SHEET_ID`에 넣습니다.
6. 서비스 계정 JSON 전체를 `GOOGLE_SERVICE_ACCOUNT_JSON`에 넣습니다. GitHub Actions에서는 Repository Secret으로 등록합니다.

첫 실행 시 다음 워크시트를 자동 생성하고 첫 행의 컬럼을 보장합니다.

| 시트 | 컬럼 |
|---|---|
| `Tracker` | 게시일, 마감일, 기업명, 공고명, 직무, 근무지, 링크, 출처, 상태, 메모, job_key, first_seen_at, last_seen_at, updated_at, score, matched_keywords |
| `Raw_Jobs` | collected_at, source, source_job_id, company, title, position, location, url, posted_at, deadline, experience, employment_type, raw_text, job_key |
| `Search_Rules` | type, keyword, weight, enabled, note |
| `Sources` | source, enabled, method, url, frequency, note |
| `Company_Targets` | company, enabled, url, query_hint, note |
| `Run_Log` | run_at, status, source, fetched_count, filtered_count, new_count, updated_count, error_message, duration_sec |

`Tracker`는 `job_key`가 같은 행을 갱신하고, 새 공고만 `상태=신규`로 추가합니다. 기존 `상태`, `메모`, `first_seen_at`은 유지하고 `last_seen_at`, `updated_at`은 실행 시각으로 갱신합니다. 삭제된 공고는 행을 삭제하지 않고 마지막 확인 시각을 보존합니다.

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

## GitHub Actions 배포

1. 코드를 GitHub 저장소에 올립니다.
2. `Settings → Secrets and variables → Actions`에 다음 Repository Secrets를 추가합니다.
   - `GOOGLE_SHEET_ID`
   - `GOOGLE_SERVICE_ACCOUNT_JSON`
   - `SLACK_WEBHOOK_URL` (선택)
3. `.github/workflows/job-tracker.yml`을 활성화합니다.
4. Actions 탭에서 `Run workflow`로 수동 실행해 첫 동작을 확인합니다.

워크플로는 UTC 00, 06, 12, 18시에 실행되며 한국 시간으로 09, 15, 21, 03시입니다. `workflow_dispatch`로 수동 실행할 수도 있습니다. 의존성, Chromium, `config.example.yaml` 복사, 트래커 실행, 실패 로그 업로드가 모두 포함되어 있습니다.

## 수집 안전 규칙

- 공개 페이지와 공식 API만 사용하며 로그인·CAPTCHA·접근 제한 우회는 하지 않습니다.
- 기본적으로 `robots.txt`를 확인하고, 호스트별 요청 간격과 User-Agent를 적용합니다.
- HTTP 일시 오류는 제한된 횟수만 재시도합니다.
- 사이트별 오류는 `Run_Log`에 남기고 전체 실행은 가능한 범위에서 계속합니다.
- 사이트 HTML 구조가 바뀌면 해당 `crawlers/<source>.py`의 선택자/응답 파서만 수정하면 됩니다.

## Vercel 확장 방향

수집과 스케줄링은 GitHub Actions에 두고, 이후 Vercel은 Google Sheets 또는 별도 DB를 읽는 읽기 전용 대시보드로 확장하는 구성이 적합합니다. `job_tracker.py`의 수집·필터·시트 서비스는 UI와 분리되어 있으므로, 추후 FastAPI/서버리스 함수에서 `load_sheet_records("Tracker")`와 동일한 저장소 계층을 호출하고 Next.js 화면에서 상태·점수·출처별 필터를 제공할 수 있습니다. Vercel 함수에서 장시간 Playwright를 실행하는 구조는 피하고, 수집은 현재처럼 Actions에서 수행하세요.
