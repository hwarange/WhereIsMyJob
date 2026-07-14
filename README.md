# WhereIsMyJob

신입·주니어 AI/ML 채용 공고를 수집하고, 조건에 맞는 공고를 GitHub Pages 대시보드로 내보내는 Python 프로젝트입니다.

## 대시보드

[https://hwarange.github.io/WhereIsMyJob/](https://hwarange.github.io/WhereIsMyJob/)

대시보드에서는 공고 검색, 지원 상태 변경, 메모 작성, 상태·메모 백업 JSON 내려받기를 사용할 수 있습니다. 지원 상태와 메모는 **현재 브라우저의 로컬 저장소**에만 저장되므로, 다른 브라우저나 기기와 자동 동기화되지 않습니다.

## 동작 방식

1. 설정에서 활성화한 채용 소스를 수집합니다.
2. 동일 공고를 제거하고, 키워드 점수·신입 조건·학력 조건으로 공고를 필터링합니다.
3. 필터링된 결과를 `docs/data/jobs.json`에 저장합니다.
4. GitHub Pages가 `docs/` 디렉터리를 정적 대시보드로 배포합니다.

수집 중 특정 소스가 실패해도 다른 소스의 수집은 계속 진행됩니다.

## 수집 소스

기본 예시 설정에는 다음 소스가 포함되어 있습니다.

- 사람인 공개 검색 결과
- 자소설닷컴 검색 결과
- 점핏 검색 결과와 공개 상세 페이지
- 설정한 기업 채용 페이지의 JSON-LD 또는 지정한 공고 상세 URL 패턴

잡코리아 수집기는 포함되어 있지만 기본적으로 비활성화되어 있습니다. 각 사이트의 `robots.txt`와 공개 범위를 확인하며, 로그인·CAPTCHA 등 접근 제어를 우회하지 않습니다.

## 로컬 실행

Python 3.11 이상을 권장합니다.

```powershell
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
python -m playwright install chromium
Copy-Item config.example.yaml config.yaml
Copy-Item .env.example .env
```

수집 결과를 확인만 하려면 다음을 실행합니다.

```powershell
python job_tracker.py --config config.yaml --dry-run
```

대시보드용 JSON을 생성하려면 다음을 실행합니다.

```powershell
python job_tracker.py --config config.yaml --export-json docs/data/jobs.json
```

Google Sheets 동기화까지 실행하려면 `--dry-run`과 `--export-json` 없이 실행합니다. 이 경우 Google 인증 정보가 필요합니다. Slack 알림은 설정에서 활성화하고 `SLACK_WEBHOOK_URL` 환경 변수를 제공했을 때만 전송됩니다.

## 설정

`config.yaml`에서 수집 소스, 검색어, 요청 간격, 필터 규칙을 조정할 수 있습니다.

- `sources.<source>.enabled`: 수집 소스 활성화 여부
- `filter.min_score`: 대시보드에 포함할 최소 키워드 점수
- `filter.strict_entry_level`: 신입·주니어·엔트리 등의 조건을 요구할지 여부
- `filter.allow_bachelor_or_lower`: 학사 이하 지원 가능 여부를 확인할지 여부
- `filter.rules`: 포함·제외 키워드와 점수

비밀 값은 `.env`에 두고 저장소에 커밋하지 마세요.

## 자동 수집 및 배포

GitHub Actions의 `Collect AI job postings` 워크플로가 UTC 기준 00:00, 06:00, 12:00, 18:00에 실행됩니다. 한국 시간으로는 09:00, 15:00, 21:00, 03:00입니다. 결과가 바뀌면 `docs/data/jobs.json`을 커밋하고, Pages 배포 워크플로가 `docs/`를 배포합니다.

수동 실행은 GitHub Actions의 **Collect AI job postings** 워크플로에서 `Run workflow`를 선택하면 됩니다.

## 테스트

```powershell
python -m pytest -q
```
