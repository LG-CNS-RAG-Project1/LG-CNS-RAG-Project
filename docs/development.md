# 개발 환경 가이드

README의 실행 방법을 보완하는 상세 문서. 개발 환경, 코드 포맷, CI, PR 자동화의 동작과 설정 방법을 정리한다.

## Docker 개발 환경

| 파일 | 역할 |
|---|---|
| `Dockerfile` | `base`(실행 의존성) → `dev`(black·pytest·pre-commit·git, 비루트 사용자 `app`) 2단계 이미지 |
| `compose.yaml` | `app` 개발 컨테이너. 저장소를 `/app`에 마운트하고 `.env`가 있으면 환경변수로 읽는다 |
| `.dockerignore` | `.env`, `data/`, `reports/` 등을 빌드 컨텍스트에서 제외 |
| `Makefile` | `make up`, `make test`, `make format` 등 공용 명령 |

- 벡터 저장소는 로컬 Chroma(`data/patents/chroma/`)를 사용하며 별도 DB 컨테이너는 두지 않는다.
- 컨테이너 사용자는 UID 1000이다. Linux에서 호스트 UID가 다르면 `docker compose build --build-arg APP_UID=$(id -u) --build-arg APP_GID=$(id -g) app`으로 다시 빌드한다.
- Windows에서 `make`가 없으면 README의 `docker compose` 명령을 직접 실행한다.

## 코드 포맷 (black)

```bash
make format         # docker compose run --rm app black .
make format-check   # CI와 같은 검사
```

- 설정은 `pyproject.toml`의 `[tool.black]`에 있다(줄 길이 88, Python 3.12 대상).
- black 버전은 `requirements-dev.txt`와 `.pre-commit-config.yaml` 두 곳에 같은 값으로 고정한다. 버전을 올릴 때는 두 파일을 함께 수정한다.
- `required-version = "26"`이므로 다른 주 버전의 black은 실행이 거부된다. black은 매년 1월 주 버전에서만 안정 스타일을 바꾸므로, 주 버전을 올릴 때는 `required-version`도 함께 바꾸고 전체 포맷을 한 번에 적용한다.
- VS Code는 `.vscode/settings.json`에 따라 저장 시 black을 적용한다. 권장 확장은 `.vscode/extensions.json`에 있다.

## pre-commit

```bash
pip install -r requirements-dev.txt   # 호스트 가상환경 기준
pre-commit install                    # 커밋 시 자동 검사 등록
pre-commit run --all-files            # 전체 파일 검사 (make precommit)
```

검사 항목: black, 병합 충돌 표시, YAML·TOML 문법, 1MB 초과 파일, 개인키, 파일 끝 개행, 줄끝 공백.

## CI (`.github/workflows/ci.yml`)

| job | 내용 |
|---|---|
| `format` | `requirements-dev.txt`에 고정된 black으로 `black --check --diff .` |
| `test` | `python -m pytest`. 수집된 테스트가 없으면(종료 코드 5) 통과 처리 |
| `scripts` | `node --test "scripts/**/*.test.mjs"` — Notion·리뷰어·PR 분석 자동화 테스트 |
| `docker` | `docker compose config` 검증과 `app` 이미지 빌드 |

## PR 리뷰어 자동 지정 (`.github/workflows/assign-reviewer.yml`)

- PR이 열리거나 초안에서 전환되거나 리뷰 요청이 해제되어 **리뷰어가 0명**이 되면, 작성자를 제외한 후보 중 한 명을 무작위로 지정한다.
- 이미 리뷰어가 요청되어 있거나 작성자 외 리뷰가 있으면 변경하지 않는다.
- 후보 기본값은 저장소 협업자 GitHub ID 목록이며, 저장소 **Settings → Secrets and variables → Actions → Variables**에 `REVIEWER_POOL`(쉼표 구분)을 만들면 그 값을 우선한다.
- 후보 전원에게 요청이 실패하면 job이 실패로 표시된다.
- `pull_request_target`으로 실행되며 PR 코드가 아닌 base 브랜치의 `scripts/github/`만 체크아웃한다.

## PR 자동 분석 (`.github/workflows/pr-analysis.yml`)

develop 대상 PR을 OpenAI GPT(Responses API, 기본 모델 `gpt-6-luna`)로 분석해 Notion `RAG 기반 미니 프로젝트: IdeaLens` 바로 아래 `PR 분석` 표에 **PR마다 페이지 하나**로 기록한다. PR이 병합되면 검증된 카드 변경만 `영역 요약 카드` 표에 반영한다. 분석기는 GPT 하나뿐이며, 실패해도 다른 모델·제공자로 넘기지 않는다. 참고용이며 승인·병합·GitHub 댓글·라벨은 하지 않는다. 필수 체크가 아니다.

용어:
- **버전(head)**: PR 브랜치의 최신 커밋
- **파일 지문**: 파일별 변경 내용(추가·삭제 줄)의 해시. 같으면 PR 변경 내용이 그대로라는 뜻이다.
- **force**: Run workflow 화면의 체크박스
- **DB ID**: Notion 표 주소의 32자리 ID. 표 안의 data source ID와 다르며, `task=notion-check`가 둘을 함께 보여 준다.

### 처음 설정(리더, 1회)

1. OpenAI 플랫폼에서 이 자동화 전용 프로젝트와 API 키를 만들고, 그 프로젝트의 월 지출 상한을 정한다.
2. 키를 GitHub 저장소 **Settings → Environments → `pr-analysis` → Environment secrets**에 `OPENAI_API_KEY` 이름으로 등록한다. 키는 화면·채팅·파일에 남기지 않는다.
3. **Settings → Secrets and variables → Actions → Variables**에서 설정한다.
   - `REVIEW_PROVIDER=openai`
   - `REVIEW_MODEL=gpt-6-luna`: 다른 값(예: `claude-…`)이 남아 있으면 모델을 부르지 않는다.
   - `REVIEW_ENABLED=true`
4. `REVIEW_LLM_ENABLED=false`인 채로 **Actions → PR Analysis → Run workflow**(develop)를 두 번 실행한다.
   - `task=verify-model`과 최근 PR 번호: 모델 호출 1회로 상태·응답 모델·사용량만 확인한다(API 비용 발생).
   - `task=notion-check`: Notion 읽기·쓰기를 확인한다.
5. 두 점검이 통과하면 `REVIEW_LLM_ENABLED=true`로 바꾼다.
6. 아래 '쓰지 않는 설정 정리'를 한다.

### 구성과 인증

| 구성 | 인증 | 하는 일 |
|---|---|---|
| GitHub Actions(`pull_request_target`) | `GITHUB_TOKEN`(읽기 전용 권한) | develop의 워크플로·스크립트만 받아 실행한다. PR 코드는 checkout·실행하지 않고, 충돌·그림 계산에 필요한 git 객체만 받는다 |
| OpenAI Responses API | Environment `pr-analysis`의 `OPENAI_API_KEY` | PR 1건 분석(보고서 + 영역 카드 변경 후보)을 구조화 출력으로 받는다. 요청에는 이 키 외의 자격 증명을 넣지 않고 `store: false`로 보낸다 |
| Notion REST API | Environment `pr-analysis`의 `NOTION_REVIEW_TOKEN`(연결 `PR_Analysis`) | PR 페이지·분석 상태·영역 카드를 읽고 쓴다. 모델에는 Notion 자격 증명이 전달되지 않는다 |

- Environment `pr-analysis`는 배포 브랜치를 develop으로 제한한다. 기능 브랜치의 워크플로는 비밀값을 읽지 못한다.
- 이 자동화의 `OPENAI_API_KEY`는 앱이 `.env`로 읽는 같은 이름의 키와 별개다. GitHub Environment에만 둔다.
- PR 제목·본문·커밋 메시지·변경 내용이 OpenAI API로 전송된다. 비밀값으로 보이는 값은 가려서 보내고, 현재 버전에 비밀값이 있으면 모델을 부르지 않는다.
- API 사용료는 OpenAI API 결제로 따로 청구된다. Claude·ChatGPT 구독과 관계없다.

### 이벤트별 동작과 모델 호출 수

| 이벤트 | 모델 호출 | 동작 |
|---|---|---|
| 초안 열림·초안 수정본 | 0회 | 잡을 시작하지 않는다(스크립트도 한 번 더 막는다). 페이지·그림을 만들지 않는다 |
| 초안 전환(`converted_to_draft`) | 0회 | 이미 있는 행의 `상태`만 `초안`으로 바꾼다 |
| 검토 요청 상태의 첫 분석(`opened`·`ready_for_review`·`reopened`) | 1회 | 한 응답에 보고서와 영역 카드 변경 후보가 함께 온다. 서비스 아키텍처 그림을 코드로 한 번 그린다. 보고서·그림·리더 메모가 같은 페이지에 들어간다 |
| 수정본(`synchronize`) | 의미 있는 변경이 있을 때만 1회 | 지난 **성공한** 분석과 파일 지문을 비교한다. 바뀐 파일과 관련 카드·지난 요약만 넘기고, 바뀌지 않은 파일의 결과와 카드 후보는 프로그램이 이어받는다. 그림은 다시 그리지 않고 '최초 구조' 표시만 붙인다 |
| 같은 버전 재실행 | 0회 | 같은 버전·같은 설정(분석기·프롬프트·스키마·제공자·모델)으로 이미 성공했으면 건너뛴다. `ready_for_review`·`reopened`이면 `상태`만 `열림`으로 고친다 |
| 병합 | 0회 | 분석 잡은 `상태`만 `병합`으로 바꾼다. `cards` 잡이 검증된 카드 변경만 반영한다. 별도 문서 페이지나 요약 호출은 없다 |
| 병합 없이 닫힘 | 0회 | `상태`만 `닫힘`으로 바꾼다. 카드는 고치지 않는다 |

분석 방식은 다음 기준으로 정한다.
- **처음부터 전체 분석**: 성공한 분석이 없을 때, `force`, 분석기 설정 변경, 계약 파일(`src/schemas.py`·`src/main.py`) 변경, 파일 60% 이상 변경. 파일이 아주 많아 파일별 지문을 버린 PR도 내용이 바뀌면 전체 분석한다.
- **바뀐 부분만**: 그 밖의 수정본. 지난번에 AI가 보지 못한 파일도 다시 넣는다.
- **의미 있는 변경 없음**: develop 반영만 한 경우 등. 모델을 부르지 않고 규칙 점검·준비 상태만 새로 계산한다.

### 입력·출력과 검증

- **입력 예산:** 지시문·안내서·스키마를 포함한 전체 입력을 `REVIEW_INPUT_BUDGET_BYTES`(기본 160,000바이트) 안에서 채운다. patch는 예산과 관계없이 최대 80,000바이트다.
- **채우는 순서:** 프로그램이 확인한 사실 → PR 글(본문 6KB·커밋 3KB·파일 목록 20KB까지) → 지난 성공 분석의 짧은 요약과 열린 확인할 점 → 영역 카드 → patch → 카드가 없거나 오래된 계층의 develop 원본.
- **일부 범위:** 다음 경우는 `AI 분석 완료(일부 범위)`로 기록하고, 보지 못한 파일·자료를 입력과 보고서에 명시한다. 이미지·글꼴 같은 바이너리는 범위에서 빼지 않는다.
  - 예산으로 뺀 patch가 있다.
  - patch가 없는 텍스트 파일이 있다.
  - 참고 자료를 줄였다.
- **준비 상태:** 파일을 보지 못했으면 '일부만 분석'이 붙는다.
- **넘기는 영역 카드:** 바뀐 파일의 계층과, 카드 근거에 바뀐 파일이 들어 있는 계층만 넘긴다. 카드가 충분하면 다른 PR 기록을 넣지 않는다. 카드가 없거나 기준 SHA 뒤 develop에서 그 계층이 바뀌었으면, 이 PR이 고친 파일의 develop 원본(최대 6개)을 함께 넘긴다.
- **데이터 구획:** 사람이 쓴 글·지난 AI 출력·카드는 nonce 구획 안에 넣고 지시가 아닌 데이터로 다룬다. '프로그램이 확인한 사실' 구획의 파일·브랜치 이름은 한 줄 따옴표 문자열로만 넣는다.
- **reasoning과 출력 상한:** 요청마다 명시한다. 전체 분석은 `medium`·32,000토큰, 바뀐 부분 분석은 `low`·25,000토큰이 기본값이다. 출력 상한에는 추론 토큰이 포함된다.
- **응답 검증:**
  - OpenAI strict 구조화 출력에 더해 로컬에서 JSON 스키마를 다시 확인한다.
  - 응답의 `head_sha`가 분석 대상과 다르면 결과 전체를 버린다. 응답 모델이 요청 모델(또는 그 날짜 스냅샷)이 아니어도 결과를 쓰지 않는다.
  - 대상 밖 파일의 지적과 없는 이전 지적 ID는 버린다. 지적의 줄 번호는 앵커를 실제 변경 줄과 대조해 프로그램이 정한다.
  - 카드 후보는 patch로 확인되는 것만 남긴다.
    - 계약 추가: 그 계층 파일의 추가 줄에 근거 심볼(3자 이상 식별자)이 있어야 한다.
    - 계약 삭제: 삭제 줄에 근거가 있어야 한다.
    - 범위 추가: 그 계층에 변경 파일이 있어야 한다.
    - 범위 삭제: 사람이 한다.

### 페이지·카드·그림 갱신 정책

- **PR 페이지:**
  - 저장소 + PR 번호로 찾는다. 제목이 바뀌어도 새 페이지를 만들지 않는다. `기록`이 `이전 분석`인 행은 건드리지 않는다.
  - 본문은 보고서 → 서비스 아키텍처 그림 → 리더 메모 순서다. 갱신하면 새 보고서를 맨 앞에 넣고, 직전 실행이 넣은 보고서 블록만 휴지통으로 보낸다.
  - 사람이 적은 블록·하위 페이지는 지우지 않는다. 메모는 맨 아래 '리더 메모'에 적는다.
- **그림:**
  - PR당 한 번, 첫 분석 때 그린다. develop과 'develop에 이 PR을 합친 코드'(충돌이면 PR 브랜치 코드)를 글자로 해석한다.
  - 상태 줄에 최초 생성 버전·시각을 남긴다. 이후 수정본이 생기면 '최초 구조' 표시를 붙인다.
- **AI 실패 시:**
  - 보고서의 AI 내용은 마지막 성공 버전의 것으로 유지한다.
  - 속성: `분석 상태`는 `AI 분석 실패`, `분석한 버전`은 성공 버전, `현재 버전`·`마지막 시도`는 이번 버전과 실패 사유다.
  - 규칙 점검 결과만 있는 페이지는 GPT 성공으로 표시하지 않는다.
- **영역 카드:** develop에 병합된 사실만 둔다(범위·핵심 계약(key별)·근거 파일·심볼·기준 SHA·리비전). 반영 순서는 다음과 같다.
  1. 분석 때 받은 카드 변경 후보는 PR 상태에만 보관한다. 수정본 분석은 다시 본 파일의 후보만 바꾸고 나머지는 이어받는다.
  2. 병합 때 '분석한 변경'과 '최종 병합된 PR 변경'을 파일 지문으로 대조한다. 병합·squash·rebase 커밋 SHA는 직접 비교하지 않는다. 다르면 반영하지 않는다.
  3. 같으면 항목 단위로 3-way 반영한다. 3-way는 분석 당시 카드 값과 지금 카드 값이 같은 항목만 고친다는 뜻이다. 분석 뒤 사람이나 다른 PR이 고친 항목은 덮어쓰지 않고 충돌로 남긴다.
  4. 반영 결과는 카드의 `적용 기록`(PR마다 한 줄)에 쓴다. 최근 PR 표시 목록인 `반영한 PR`과는 따로 둔다.
  5. 카드 반영은 concurrency 그룹 `pr-analysis-cards`(`queue: max`)에서 한 줄로 처리한다. 쓰기 직전에 리비전을 다시 읽어, 바뀌었으면 다시 계산한다.
  6. 이전 형식 열(요약·인터페이스·계약·알려진 위험)은 읽기만 한다.
- **분석 상태 JSON:** 리더 전용 '분석 메모리' 페이지의 `분석 상태` 표에 둔다.
  - `last_attempt`와 `last_successful_analysis`를 따로 둔다.
  - 기록하는 값은 저장소·PR·버전·develop 기준·제공자·모델·응답 모델·프롬프트/스키마 버전·사용한 카드 리비전·분석 범위·성공 여부다.
  - Notion 칸 한도를 넘으면 기록·목록·파일별 지문(요약 해시는 남김)·출력 원문 순으로 줄인다.
- **상태 저장 실패 시:** Notion 쓰기는 됐는데 상태 저장이 실패하면, 다음 실행이 PR 번호로 기존 페이지·그림을 먼저 찾는다. 그래서 페이지·그림·카드 반영이 중복되지 않는다. 다만 상태가 없으면 분석은 한 번 더 할 수 있다.

### 실패 해석과 대응

| `마지막 시도`의 사유 | 뜻 | 자동 처리 | 리더가 할 일 |
|---|---|---|---|
| 속도 제한 | 429 `rate_limit`·`slow_down` | Retry-After(없으면 `x-ratelimit-reset-*`)만큼 기다려 최대 2번 다시 보낸다. 60초를 넘으면 다시 보내지 않고 그 시각까지 저장소 전체 AI 호출을 멈춘다 | 대부분 없음. 자주 나면 OpenAI 사용 등급 확인 |
| 사용·결제 한도 초과 | 429 `insufficient_quota`·`*_spend_limit_exceeded` 등 | 다시 보내지 않고 저장소 전체 AI 호출을 6시간 멈춘다 | 결제·지출 상한 확인 |
| 인증 오류·모델 접근 불가·응답 모델 불일치·요청 형식 오류 | 401·403·404·400, 응답 모델이 요청과 다름 | 다시 보내지 않고 저장소 전체 AI 호출을 6시간 멈춘다. 다른 모델로 바꾸지 않는다 | Secret 교체, OpenAI 프로젝트의 모델 권한·`REVIEW_MODEL` 확인 |
| OpenAI 서버 오류·연결 오류 | 5xx·연결 실패 | 최대 2번 다시 보낸다 | 반복되면 OpenAI 상태 페이지 확인 |
| 응답 미완료(출력 한도)·모델 거절·출력 형식 검증 실패·시간 초과(280초) | 응답을 쓸 수 없음 | 다시 보내지 않는다 | 같은 PR에서 반복되면 `force`로 다시 실행하거나 출력 상한 조정 |

- 같은 버전에서 실패가 2번 쌓이면 이후 자동 실행은 모델을 부르지 않는다(`같은 버전 2회 실패로 자동 중단`). 대기로 건너뛴 실행도 실패 횟수를 이어받는다.
- 멈춘 시각이 지나도 자동으로 다시 실행하지 않는다. 다음 수정본이나 수동 실행 때 다시 부른다.
- 실패해도 팀원 PR에 실패 표시가 남지 않도록 job은 경고만 남기고 성공으로 끝난다.

### 사용량과 비용 확인

- 호출마다 Actions 로그에 `PR_ANALYSIS_USAGE {…}` 한 줄이 남는다. 담는 값은 PR·버전·이벤트·목적·제공자·모델·실제 응답 모델·입력/캐시/캐시 쓰기/출력/추론 토큰·입력 구획별 바이트·시간·재시도·결과(success·failed:사유·skipped:사유)다.
- 실행 요약에 같은 줄을 남긴다. PR 페이지의 '분석 기록' 표에는 토큰 수를 보여 준다.
- 공식 정의대로 캐시 토큰은 입력의 일부, 추론 토큰은 출력의 일부이므로 더하지 않는다.
- 응답을 받은 실패(미완료·형식 오류 등)도 입력·추론 토큰이 청구될 수 있다. 시간 초과·연결 오류는 사용량을 받지 못해 0으로 기록되므로 실제 청구는 OpenAI 플랫폼의 Usage·Billing 화면에서 확인한다.
- 측정하지 않은 절감 추정치는 기록하지 않는다.

### 설정

| 이름 | 위치 | 내용 |
|---|---|---|
| `OPENAI_API_KEY` | Environment `pr-analysis` 비밀값 | OpenAI API 키(이 자동화 전용 프로젝트 키 권장). 분석 단계에만 전달하고 병합·닫힘·초안 전환·카드 잡에는 넘기지 않는다 |
| `NOTION_REVIEW_TOKEN` | Environment `pr-analysis` 비밀값 | Notion 연결 `PR_Analysis`(읽기·업데이트·삽입) 토큰 |
| `REVIEW_ENABLED`·`REVIEW_LLM_ENABLED` | 저장소 변수 | `true`일 때 실행·AI 분석. 끄면 다음 실행부터 즉시 멈춘다 |
| `REVIEW_PROVIDER`·`REVIEW_MODEL` | 저장소 변수 | `openai`·`gpt-6-luna`(비우면 이 값). 다른 제공자나 `gpt-`로 시작하지 않는 모델이면 모델을 부르지 않는다 |
| `REVIEW_EFFORT_FULL`·`REVIEW_EFFORT_INCREMENTAL` | 저장소 변수(선택) | reasoning 강도. 기본 `medium`·`low` |
| `REVIEW_MAX_OUTPUT_TOKENS_FULL`·`REVIEW_MAX_OUTPUT_TOKENS_INCREMENTAL` | 저장소 변수(선택) | 출력 상한(추론 포함). 기본 32000·25000 |
| `REVIEW_INPUT_BUDGET_BYTES` | 저장소 변수(선택) | 전체 입력 예산(바이트). 기본 160000 |
| `REVIEW_ADMINS` | 저장소 변수(선택) | 수동 실행에서 AI 분석을 허용할 GitHub ID(쉼표 구분). 비우면 Run workflow 권한이 있는 누구나 실행해 API 비용을 쓸 수 있다 |
| `NOTION_PR_DATABASE_ID` | 저장소 변수 | `PR 분석` 표의 DB ID. 연결 `PR_Analysis`에 접근 권한이 있어야 한다 |
| `NOTION_CARD_DATABASE_ID` | 저장소 변수 | `영역 요약 카드` 표의 DB ID. 없으면 카드를 읽거나 갱신하지 않는다 |
| `NOTION_MEMORY_PAGE_ID` | 저장소 변수 | 상태 저장 페이지('분석 메모리') ID |
| `NOTION_DASHBOARD_PAGE_ID` | 저장소 변수(선택) | `NOTION_PR_DATABASE_ID`가 없을 때만 사용 |
| `NOTION_SANDBOX_PAGE_ID` | 저장소 변수 | Notion 연결 점검에 쓰는 시험용 페이지 ID |

비밀값은 채팅, 코드, README, 커밋, Notion, 터미널 화면에 남기지 않는다.

### 수동 실행·점검·복구

```bash
make review-preview PR=26                 # 규칙 점검만, Notion에 쓰지 않고 결과를 $TMPDIR/review-preview-26.json에 저장
make review-preview PR=26 LLM=true        # 셸 환경변수 OPENAI_API_KEY가 있으면 GPT 분석까지 미리보기(Notion에 쓰지 않음, API 비용 발생)
make review-model-check                   # 셸 환경변수 OPENAI_API_KEY로 gpt-6-luna 최소 호출 1회(상태·응답 모델·사용량만 출력, API 비용 발생)
```

**Actions → PR Analysis → Run workflow**(develop에서 실행):
- `task=analyze`
  - PR 번호로 분석·기록한다.
  - `force`는 같은 버전·재시도 한도·대기 시간을 무시한다(API 비용 발생).
  - 병합된 PR이면 이어서 카드 반영도 다시 시도한다. 이미 처리한 병합은 건너뛴다.
- `task=verify-model`
  - 실제 PR 입력으로 모델을 한 번 부른다(API 비용 발생).
  - Notion에는 읽지도 쓰지도 않는다. 로그에는 상태·사용량만 남는다.
  - PR 이벤트와 대기열을 나눠 쓴다.
- `task=notion-check`
  - 표·페이지 ID를 읽어 DB ID와 data source ID를 구분해 보여 준다.
  - 시험용 페이지 아래 '연결 점검' 하위 페이지에서 만들기 → 다시 읽기 → 고치기 → 다시 읽기를 확인한다.

워크플로는 develop의 스크립트만 쓰므로 분석기 변경은 develop 병합 후에 반영된다.

**멈추는 법:**
- AI만 멈춤: 저장소 변수 `REVIEW_LLM_ENABLED=false`. 규칙 점검·상태 갱신은 계속된다.
- 전체 멈춤: `REVIEW_ENABLED=false`.
- 진행 중인 실행: Actions에서 취소한다.
- 키 노출이 의심되면: OpenAI 플랫폼에서 키를 폐기하고 새 키로 Secret을 교체한다.

**복구:**
- 잘못 기록된 페이지는 Notion 페이지 기록(버전 기록)에서 되돌린다. 지운 보고서 블록은 Notion 휴지통에 남는다.
- 전체 대기(한도·설정 오류)를 일찍 풀려면 원인을 고친 뒤 '분석 메모리' 페이지 `분석 상태` 표의 PR 번호 0 행(`운영 상태(자동)`)을 지운다. 또는 `force`로 실행한다.
- 카드 충돌은 카드의 `적용 기록`을 보고 사람이 고친다.
- 분석 상태가 깨졌으면 해당 PR 행을 지우고 `force`로 다시 실행한다.

### 쓰지 않는 설정 정리(1회)

이 자동화는 Claude CLI·Claude 인증을 쓰지 않는다. 운영 경로에 Claude 호출이 들어오면 `scripts/review/workflow.test.mjs`가 실패한다.

워크플로가 참조하지 않는 다음 설정은 저장소 관리자가 지운다.
- Environment `pr-analysis`의 `CLAUDE_CODE_OAUTH_TOKEN`
- 저장소 변수 `CLAUDE_TOKEN_EXPIRES_ON`
- 저장소 Secret `NOTION_API_TOKEN`

발급자 쪽 무효화는 GitHub 설정 삭제와 별개로 한다.
- Claude OAuth 토큰: 발급한 Claude 계정에서 폐기한다.
- `NOTION_API_TOKEN`에 해당하는 Notion 연결: 'GitHub PR 자동 문서화' 페이지에 공유된 연결이다. 다른 곳에 쓰지 않으면 Notion 연결 설정에서 정리한다.

'GitHub PR 자동 문서화' 페이지 아래 기존 기록은 그대로 둔다.

## Dependabot (`.github/dependabot.yml`)

pip, pre-commit, GitHub Actions 버전 갱신 PR을 생태계별로 묶어 월 1회 develop(기본 브랜치)에 만든다.
