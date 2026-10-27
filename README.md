# 아이디어 사업 검토 RAG

- 신제품·사업 아이디어의 시장 수요, 기업 동향, 관련 특허와 구현 비용을 연결하는 프로젝트.
- 주요 사용자: 사업 아이디어를 검토하는 기획자와 개발팀.
- 산출물: 확정 브리프, 근거가 연결된 조사 노트, 비용표와 다음 검증 과제.
- 현재 UI는 로컬 시연이다. AI 구조화·실제 검색·분석 API는 미연결이며, 예시를 변경하면 가상 결과를 적용하지 않는다.

## 코딩 에이전트 사용 전 필독

- Git·GitHub 공용 작업 규칙은 저장소 최상위의 [AGENTS.md](AGENTS.md)에 관리.
- 저장소를 복제한 뒤 `LG-CNS-RAG-Project/` 루트 폴더를 작업 폴더로 열고 에이전트 세션 시작.
- 매 새 작업 세션의 첫 요청에 아래 프롬프트를 전달하고, 에이전트가 읽은 파일 경로와 규칙 요약을 확인한 뒤 개발 진행.
- Codex는 세션 시작 시 프로젝트의 `AGENTS.md`를 읽으며, 지침을 추가·수정한 경우 새 세션에서 적용 여부 확인. ([OpenAI 공식 문서](https://learn.chatgpt.com/docs/agent-configuration/agents-md))
- 사용하는 도구가 `AGENTS.md`를 자동으로 읽지 않는 경우 프로젝트 지침 설정에서 참조하도록 지정하거나 파일을 직접 첨부.

```text
작업을 시작하기 전에 저장소 루트의 AGENTS.md와 README.md를 끝까지 읽어라.
읽은 파일 경로와 적용할 Git·GitHub 규칙을 간단히 요약한 뒤 요청한 작업을 수행하라.
기존 변경사항을 보호하고 AGENTS.md의 브랜치·커밋·push·PR·보안 규칙을 준수하라.
파일을 읽을 수 없거나 지침을 적용할 수 없으면 임의로 진행하지 말고 원인과 필요한 조치를 보고하라.
```

## 디렉토리 구성

```text
.
├── .github/
│   ├── workflows/           # CI, 리뷰어 자동 지정, PR 분석
│   ├── ISSUE_TEMPLATE/      # 작업·버그 이슈 양식
│   └── pull_request_template.md
├── .vscode/                 # 저장 시 black 적용 등 공용 편집기 설정
├── .streamlit/              # 아이디어 검토 화면의 테마 설정
├── AGENTS.md                # 팀 공용 Git·GitHub 및 코딩 에이전트 작업 규칙
├── configs/                 # 산업별 검색어·분류·검색 설정
├── data/
│   ├── raw/                 # 수집한 원문
│   ├── processed/           # 정규화 문서와 검색 청크
│   ├── indexes/             # 검색 색인
│   ├── patents/             # 특허 원문·정제 데이터·Chroma 벡터 저장소
│   ├── market/              # 시장 자료 원문·정제 데이터
│   └── samples/             # 시연용 샘플 아이디어·시장 결과(MarketReport) 예시
├── deploy/                  # 공용 Chroma 서버 시작 스크립트·Compose 설정
├── docs/                    # 기획·설계·개발 환경 문서, 프로젝트 목표·PR 분석 안내서(review-baseline.md)
├── evaluation/              # 평가 질문·정답 근거·평가 실행
├── frontend/                # 아이디어 검토 UI, 스타일, 비용 계산과 예시 보고서
├── prompts/                 # 아이디어 구조화·근거 검증·보고서 프롬프트
├── reports/                 # 생성한 경영진·R&D 보고서
├── scripts/
│   ├── *.py                 # 특허 수집·색인 생성 실행 스크립트
│   ├── notion/              # Notion 블록 도우미, 코드 해석 기반 서비스 아키텍처 그림(mermaid) 생성
│   ├── github/              # PR 리뷰어 무작위 지정
│   └── review/              # PR 자동 분석(규칙 점검·GPT 분석(Codex 구독 또는 API)·Notion PR 페이지와 영역 요약 카드 기록)
├── src/
│   ├── main.py · pipeline.py · schemas.py  # API 진입점·분석 흐름·공통 모델
│   ├── ingestion/           # 자료 수집·전처리·청크 생성
│   ├── retrieval/           # 공통 Dense·BM25·Hybrid 검색·색인 구축
│   ├── generation/          # 근거 검증·역할별 보고서 생성
│   └── services/            # 특허·시장 분석 진입점
├── tests/                   # pytest 테스트
├── Dockerfile · compose.yaml · Makefile  # Docker 개발 환경과 공용 명령
├── pyproject.toml           # black·pytest 설정
├── requirements.txt         # 실행 의존성
├── requirements-dev.txt     # 개발 도구(black·pytest·pre-commit)
├── .env.example             # 환경변수 이름 예시
└── README.md
```

- 원문·가공 데이터·검색 색인·생성 보고서는 Git 추적에서 제외. Chroma 색인은 로컬 또는 공용 서버에 보관.
- 서비스 연결 구조는 [docs/architecture.md](docs/architecture.md)의 mermaid 다이어그램으로 관리.

## 실행 방법

Docker Desktop(또는 Docker Engine + Compose v2.24 이상)을 기준으로 한다.

```bash
cp .env.example .env              # API 키 입력 (make env와 동일)
docker compose up -d --build      # 개발 컨테이너 실행 (make up)
docker compose exec app bash      # 컨테이너 셸 접속 (make shell)
docker compose run --rm app python -m pytest   # 테스트 (make test)
docker compose down               # 종료 (make down)
```

- `app` 컨테이너는 저장소 전체를 `/app`에 마운트하므로 코드 수정이 바로 반영되고, Chroma 저장소(`data/patents/chroma/`, `data/market/chroma/`)와 수집 데이터는 호스트에 유지된다.
- 의존성을 바꾸면 `docker compose build app`(`make build`)으로 이미지를 다시 만든다.
- Docker 없이 실행할 때는 Python 3.12 가상환경에서 `pip install -r requirements-dev.txt`를 실행한다.
- `make help`로 공용 명령 목록을 확인한다. 상세 내용은 [docs/development.md](docs/development.md)를 참고한다.

## 공용 Chroma 연결

기본값은 기존 로컬 Chroma다. 팀 공용 서버를 쓰려면 Google IAP 보호 터널을 열고 `.env`에 `CHROMA_HOST=127.0.0.1`, `CHROMA_PORT=18000`, `CHROMA_SSL=false`를 설정한다. 팀원은 서버 관리자·결제 권한 없이 DB 포트만 이용한다. 특허·시장 저장과 검색이 같은 원격 DB를 사용하며 연결 실패 시 로컬로 전환하지 않는다. 기존 로컬 자료는 자동 이관되지 않는다. 서버 배포·팀원 접속·백업은 [공용 Chroma 안내](docs/shared-chroma.md)를 참고한다. 웹 화면과 실제 검색 API 연결은 별도 구현 범위다.

## Streamlit 화면 시연

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ui.txt
.\.venv\Scripts\python.exe -m streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8505
```

홈 로고와 클릭 가능한 상단 1~4단계·본문 버튼으로 **아이디어 입력 → 핵심 구성 확인 → 문헌 선정·근거 검토 → 종합 보고서**를 진행한다. 왼쪽 단계 사이드바는 사용하지 않는다.
홈은 배경과 경계 없이 이어지는 조사 문서 비주얼과 입력 바로가기를 제공한다. 표지에는 특허 구성 도면·시장 흐름 그래프·근거 연결선과 유리 반사·그림자를 표현한 장식 돋보기를 배치하며 실제 특허·수요 데이터로 표시하지 않는다. 단계마다 아이보리·연녹색·크림·연청색으로 종이 색이 바뀌며 남은 장수가 3→2→1→0장으로 줄어든다. 앞뒤 이동 시 종이의 들림·회전·그림자를 표현하고 동작 줄이기 설정을 따른다. `frontend/assets/idealens-symbol.svg`와 `idealens-logo.svg`는 문서·돋보기·근거 연결을 결합한 심볼과 글자 로고다. 로고 버튼은 홈 이동 기능을 유지한다. `frontend/presentation.py`가 홈 비주얼을, `frontend/styles.css`가 종이 재질과 전환을 관리한다. 제공된 사진은 디자인 참고로만 사용하며 화면의 도해와 종이는 코드로 표현한다.
입력 화면은 큰 본문과 우측 최근 입력, 조사 화면은 좌측 구성·중앙 특허/시장 후보·우측 선택 목록, 보고서는 좌측 선택 문헌·우측 본문으로 구성한다.
핵심 구성은 최대 7개, 검토 질문은 최대 5개를 조건과 함께 확정한다. 3단계는 자동 연결 결과를 먼저 보여주며 사용 맥락·해결 과제·기술 구성·요구 성능·도입 제약·근거 범위의 판단 과정을 펼쳐 확인한다. 문헌 제외와 결과 수정은 선택 사항이다. 최소 2개 자료로 부분 보고서를 열 수 있으며, 질문별 근거 부족은 통합 판단 보류로 표시한다.
정확한 기본 예시에만 가상 자료 4건과 사전 작성된 연결 초안을 자동 배치한다. 입력·구성·질문·조건을 바꾸면 해당 시연 판단을 재사용하지 않는다. 실제 AI 추출·검색·통합 판단은 UI에 미연결이며 예시도 실제 수요·성능 검증으로 표시하지 않는다.
`frontend/automatic.py`는 시연 규칙과 팀 `MarketReport`/`PatentReport` 검증 모델의 근거 변환을 담당한다. 변환은 인용 ID를 영역별로 구분하고 출처·시점·인용문을 보존하는 준비 코드이며 실제 API 호출은 하지 않는다. `frontend/quick.py`는 보고서 규칙, `frontend/app.py`는 화면을 담당한다. 수정·제외는 보고서에도 반영하고 이전 스냅샷을 무효화한다.
[실행·시연 가이드](docs/ui-guide.md)와 [참고 화면 구조 및 연결 계약](docs/quick-research-ui.md)을 참고한다. 기존 비용 함수는 후속 활용을 위해 유지한다.

### 시장 뉴스 수집·정제

시장 조사 전체 흐름(아이디어 구조화 → 수집·색인 → 차원별 검색 → 분석 생성·인용 검증 → 평가)과
단계별 코드 위치는 [docs/market_research.md](docs/market_research.md)를 참고한다.

```bash
python -m src.ingestion.news_client --keyword-id smart_factory --max-items 10   # 키워드 1개 수집
python -m src.ingestion.news_client                                             # 전체 키워드 수집
python -m src.ingestion.market_processor                                        # 원본 → MarketDocument 정제
```

- 키워드·수집 기준은 `configs/market_keywords.yaml`에서 관리한다.
- NAVER API HUB 뉴스 검색 API의 제목·요약·링크·발행일만 `data/market/raw/news_{keyword_id}_{수집일}.json`에 저장한다.
- 정제 단계는 같은 URL 기사를 합치고, 제목 유사도 0.8 초과·발행일 3일 이내 기사를 같은 `dup_group`으로 묶어 대표 1건만 `data/market/processed/market_docs.jsonl`에 저장한다.

### 시장 근거 색인·검색

```bash
python -m src.retrieval.market_search build                                     # market_docs.jsonl 색인
python -m src.retrieval.market_search search "협동로봇 도입 확대" --idea-id SF-01   # 질의 검색
```

- `data/market/processed/market_docs.jsonl`을 `text-embedding-3-small`로 임베딩해 `data/market/chroma/`의 `news` 컬렉션(cosine)에 저장한다. `OPENAI_API_KEY`가 필요하다.
- 이미 색인된 문서는 다시 임베딩하지 않으며, `--rebuild`로 전체를 다시 임베딩한다.
- 에이전트 툴은 `search_market`(질의 1건)과 `search_by_dimensions`(수요·경쟁·가격·구매자·도입장벽 차원별 질의)이며, 같은 `dup_group` 결과는 1건만 반환한다.
- 차원별 질의는 아이디어 5개 항목으로 만든다: 수요(고객·문제·기술), 경쟁(차별점·기술), 가격(고객·기술·수익모델), 구매자·도입장벽(고객·기술). 빈 항목은 질의에서 빠진다.

```bash
python -m src.retrieval.market_relevance --idea-id SF-01   # 차원별 검색 + 관련성 판정·충분성 상태
```

- `search_with_relevance`는 차원별 검색 결과마다 `gpt-4o`로 관련 여부·이유를 판정하고(기준: `prompts/market_label_judge.md`), 관련 건수로 차원별 충분성 상태(`sufficient` 2건 이상 · `limited` 1건 · `insufficient` 0건 · `no_results` · `error`)를 붙여 반환한다. `OPENAI_API_KEY`가 필요하다.
- 검색 거리는 관련성을 구분하지 못해(평가 라벨 기준 AUC 0.52) 충분성 판단에 쓰지 않는다. 판정 모델 선택 근거는 [docs/market_research.md](docs/market_research.md#충분성-판정).

### 시장 조사 실행 (MarketReport)

```bash
python -m src.services.market_service --idea-id SF-01                                         # MarketReport JSON 출력
python -m src.services.market_service --idea-id SF-01 --out data/samples/market_reports/SF-01.json   # 파일로 저장
```

- `run_market_research(MarketSearchRequest)`가 차원별 검색 → 관련성 판정 → 시장 분석 생성·인용 검증을 실행해 `MarketReport`(`src/schemas.py`)를 반환한다. 분석 규칙은 `prompts/market_analysis.md`, 생성·검증은 `src/generation/market_analysis.py`에서 관리한다. `OPENAI_API_KEY`가 필요하다.
- 사실 문장은 인용 근거(`evidence`의 `citation_id`)가 있어야 하고, 인용 기사·아이디어 입력에 없는 숫자가 있거나 수치에 기준 연도가 없으면 재생성(최대 2회)하거나 해당 문장을 제거한다. 판정은 차원별 충분성 상태로 제한하고(근거 1건이면 최대 '신호만 확인'), 기대는 아이디어 항목이 모름이면 미확인으로 둔다(가격 ← 수익모델, 구매자 ← 고객).
- `data/samples/market_reports/`에는 SF-01~SF-05 실행 결과 예시가 있다. 로컬 수집 뉴스 기준이므로 다시 수집하면 내용이 달라진다.

### 아이디어 구조화

```bash
python -m src.generation.idea_parser "중소 부품 공장에 협동로봇과 비전 카메라를 턴키로 설치해 준다"
```

- 아이디어 한 문장을 `gpt-4o-mini`로 문제(`problem`)·기술(`technology`)·고객(`customers`)·차별점(`difference`)·수익모델(`revenue`)로 나눈다. 규칙은 `prompts/idea_parser.md`에서 관리하며, 문장에 없는 항목은 추측하지 않고 비워 둔다. `OPENAI_API_KEY`가 필요하다.
- 빈 항목은 사용자에게 최대 2회 재질문한다. '모름'으로 답했거나 끝까지 비어 있는 항목은 `unknown`으로 확정하고, 항목별 출처(`extracted`·`user_answer`·`unknown`)를 함께 남긴다.
- 완성된 결과(`IdeaDraft`)는 `build_requests`로 특허·시장 공통 입력(`StructuredIdea`)과 검색 요청(`PatentSearchRequest`·`MarketSearchRequest`)으로 변환한다.
- 입력 가드레일: LLM 호출 전 규칙 검사(`src/generation/input_guard.py`: 길이, 지시 무시·시스템 프롬프트 공개 등 조작 표현)와 같은 LLM 호출의 `input_status` 판정(`ok`·`off_topic`·`unsafe`)으로 주제 이탈·프롬프트 조작·유해 목적 입력을 거절한다. 거절되면 `status="rejected"`와 안내 문구(`rejection_reason`)를 반환하고 검색 요청을 만들지 않는다. 재질문 답변도 규칙 검사를 거친다. 기준은 [docs/market_research.md](docs/market_research.md#입력-가드레일).

## 환경변수

`.env.example`을 `.env`로 복사해 값을 채운다. `.env`는 Git에 커밋하지 않는다.

| 이름 | 용도 |
|---|---|
| `OPENAI_API_KEY` | 앱의 임베딩·답변 생성용 OpenAI API 키 |
| `KIPRIS_API_KEY` | KIPRIS Plus 특허 API 키 |
| `DART_API_KEY` | DART OpenAPI 공시 API 키 |
| `NAVER_CLIENT_ID` · `NAVER_CLIENT_SECRET` | NAVER API HUB(네이버클라우드) Application의 Client ID·Secret. 해당 Application에서 뉴스 검색 API 활성화 필요 |

PR 분석 자동화용 `CODEX_AUTH_JSON`(ChatGPT 구독 로그인, `make review-codex-login`으로 등록)·`CODEX_AUTH_WRITE_TOKEN`·`NOTION_REVIEW_TOKEN`은 `.env`가 아니라 develop에서만 열리는 GitHub Environment `pr-analysis`에 저장한다([docs/development.md](docs/development.md#pr-자동-분석-githubworkflowspr-analysisyml)).

## 개발 도구와 협업 자동화

- **코드 포맷**: Python 코드는 [black](https://black.readthedocs.io/)으로 통일한다. 버전은 `requirements-dev.txt`에 고정하고, `pyproject.toml`의 `required-version`으로 다른 주 버전 실행을 막는다.
- **커밋 전 검사**: `pre-commit install` 후 커밋마다 black, 병합 충돌 표시, 개인키 노출, 대용량 파일, 줄끝 공백을 검사한다.
- **CI**: develop·main 대상 PR과 push에서 black 검사, pytest, 자동화 스크립트 테스트, Docker 이미지 빌드를 실행한다.
- **리뷰어 자동 지정**: PR에 리뷰어가 없으면 작성자를 제외한 팀원 중 한 명을 무작위로 지정한다. 후보는 저장소 변수 `REVIEWER_POOL`로 바꿀 수 있다.
- **PR 자동 분석**: develop 대상 PR이 검토 요청 상태로 열리거나 수정되면 규칙 점검과 GPT(`gpt-6-sol`, 기본은 Codex CLI + 리더 ChatGPT 구독 로그인, API 키 방식도 선택 가능) 분석 결과를 Notion 'RAG 기반 미니 프로젝트: IdeaLens' 아래 'PR 분석' 표의 PR별 페이지 하나에 기록한다. 페이지에는 태그(서비스 계층)·키워드·분석 내용, AI 병합 판단(4등급과 근거 3문장, 참고용), 첫 분석 때 코드로 한 번 그린 서비스 아키텍처 그림이 들어간다. 초안·병합·닫힘에는 모델을 부르지 않고, 수정본은 의미 있는 변경이 있을 때 바뀐 파일만 다시 분석한다. 병합되면 분석한 변경과 최종 변경이 같을 때만 카드 변경 후보를 태그별 '영역 요약 카드'에 항목 단위로 반영한다. 구독 방식은 리더의 Codex 사용량을 쓰고, API 키 방식은 OpenAI API 결제로 따로 청구된다. 구독 로그인은 OpenAI 문서가 공개 저장소에 권하지 않는 방식이라 위험과 대응을 운영 안내에 둔다. 참고용이며 승인·병합·GitHub 댓글은 하지 않는다. 판단 기준은 [docs/review-baseline.md](docs/review-baseline.md), 운영 안내는 [docs/development.md](docs/development.md#pr-자동-분석-githubworkflowspr-analysisyml).
- **Codex 구독 경로 주의:** 도구 비활성화 설정과 기능 점검만으로 실제 도구 노출이나 파일 읽기 차단을 보장할 수 없다. 공개 저장소에서 구독 로그인을 사용하는 위험과 운영 절차를 확인한다.
- **의존성 갱신**: Dependabot이 pip·pre-commit·GitHub Actions 버전 갱신 PR을 월 1회 묶어서 만든다.

## 구현 방향

- 프로젝트 목표·세부 단계·이번 시기 우선순위·범위의 기준은 [docs/review-baseline.md](docs/review-baseline.md)이며, PR 자동 분석도 이 문서로 목표 연결을 판단한다.
- 목표 흐름: 아이디어 구조화 → 특허·시장 수집·정제 → 색인·검색 → 판정·분석 생성 → 인용 검증 → 질문별 연결 → 종합 보고서(구현 비용표 포함) → 평가.
- 기존 백엔드의 아이디어·특허·시장 모델(`src/schemas.py`)을 결과 계약으로 유지하며, 실제 검색·분석 결과를 받는 UI 연결은 별도 구현한다.
- 데이터 출처: KIPRIS Plus, NAVER 뉴스 검색 API(교육 목적, 프로젝트 종료 시 폐기), DART, 공공기관·연구기관·기업의 공식 자료. 사내자료 연계는 향후 검토 범위.
- 원문 구획과 청구항 구조를 보존하고, 각 주장에 출처·문헌 버전·원문 위치·링크를 연결.
- 검색은 공통 엔진에서 의미 검색(dense)·단어 검색(BM25)·결합(hybrid) 중 선택하며, 임베딩은 `text-embedding-3-small`, 색인은 로컬 Chroma 또는 환경변수로 지정한 공용 Chroma를 사용.
- 시연은 로컬 PC의 Streamlit UI로 한다. 기본 색인은 로컬 Chroma(`data/patents/chroma/`·`data/market/chroma/`)이며 공용 DB 접속은 선택 설정이다. UI 호스팅과 실제 분석 API 연결은 별도 구현한다.
- 사실·해석·가설·미확인을 구분하고, 근거가 부족하면 판단을 보류. 최종 판단은 사용자가 수행.

## 평가 계획

- 검색 품질: Hit@K, Recall@K, Precision@K, MRR, nDCG@K 및 검색 지연시간.
- 답변 품질: 정확성, 근거 충실성, 인용 정확성.
- 동일 자료집에서 검색 방식을 비교하고, 동일 질문의 일반 LLM 응답과 RAG 응답을 평가.

### 시장 검색 평가

```bash
python -m evaluation.market_labeling init      # ideas.json × 5개 차원 → evaluation/market_cases.json 문항 생성
python -m evaluation.market_labeling export    # 라벨링 후보 → evaluation/labels/market_candidates.csv
python -m evaluation.market_judge prelabel     # (선택) gpt-4o 라벨 초안 → evaluation/labels/market_llm_labels.csv
python -m evaluation.market_judge agreement    # (선택) 사람 라벨과 LLM 초안의 일치율·kappa
python -m evaluation.market_judge merge        # (선택) 빈 relevant만 LLM 초안으로 채움
python -m evaluation.market_labeling import    # relevant(1/0)를 채운 CSV → 문항별 정답 source_id 반영
python -m evaluation.evaluate market --mode dense --label baseline
python -m evaluation.evaluate market --mode bm25 --label baseline
python -m evaluation.evaluate market --mode hybrid --label baseline
python -m evaluation.evaluate market --mode hybrid --rerank --label baseline  # 선택 의존성 필요
python -m evaluation.evaluate relevance --model gpt-4o  # 관련성 판정 vs 사람 라벨 → evaluation/results/
python -m evaluation.evaluate guardrail                 # 입력 가드레일 차단율·오차단율 → evaluation/results/
```

- 평가 아이디어는 `data/samples/ideas.json`의 SF-01~SF-05이며, 아이디어 5개 × 시장 차원 5개 = 25문항이다.
- 라벨링 후보는 문항마다 벡터 검색 상위 8건과 그 아래 순위에서 차원 표현(가격·비용, 도입·사례 등)이 들어간 4건이다. 라벨 기준과 LLM 초안·사람 검토 절차는 [evaluation/market_labeling.md](evaluation/market_labeling.md).
- 관련 문서가 없는 문항은 평균에서 빼고 따로 센다. 라벨 후보에 없던 문서가 상위 5건에 나오면 `unjudged`로 표시한다.
- 관련성 판정 평가는 사람이 직접 라벨한 행(`label_source=human`)만 비교해 정확도·정밀도·재현율·kappa를 계산하고, 사람 라벨만 있는 문항의 충분성 상태 일치를 함께 출력한다.
- 정답 `source_id`는 로컬에 수집한 뉴스 기준이므로, 다시 수집하면 문서가 달라질 수 있다.
- `--mode`는 `dense`(기본, 기존 Chroma 검색), `bm25`, `hybrid`(RRF 결합) 중 선택한다. 검색 함수 기본 동작은 dense로 유지한다.
- `--rerank`는 `pip install sentence-transformers` 후 `BAAI/bge-reranker-v2-m3` Cross-Encoder를 적용한다. 모델 파일은 최초 실행 때 내려받으며, 기본 실행 의존성에는 포함하지 않는다.
- 평가는 문항별 Hit/Recall/Precision/MRR/nDCG와 검색 지연시간을 CSV로 저장한다. OpenAI 비용은 토큰 사용량 정보가 제공되지 않는 현 검색 인터페이스에서 계산하지 않는다.
- 라벨이 완료된 시장 25문항은 평가 대상이다. 특허 평가 질의 5개는 준비되어 있지만 사람 관련도 라벨과 로컬 특허 색인이 준비되기 전까지 특허 품질 수치는 만들지 않는다.

### 특허 검색 평가

- `evaluation/patent_cases.json`은 샘플 아이디어에서 고정한 5개 특허 검색 질의로 시작하며, 정답 문헌 라벨은 비어 있다.
- 특허 원문을 수집·색인한 뒤 `python -m evaluation.patent_labeling export`로 Dense·BM25·Hybrid 상위 후보를 같은 CSV에 모은다. 선택적으로 `--rerank`를 주면 Hybrid+Cross-Encoder 후보도 포함한다.
- 후보 CSV에서 각 문헌의 `relevant`를 `1`(관련) 또는 `0`(비관련)으로 사람 검토 후 채우고 `python -m evaluation.patent_labeling import`로 라벨을 반영한다. 모든 후보를 판정한 문항만 평가에 포함한다.
- 동일한 문헌 단위 정답셋으로 `python -m evaluation.evaluate patent --mode dense --label baseline`, `--mode bm25`, `--mode hybrid`, `--mode hybrid --rerank`를 실행해 Hit@5·Recall@5·Precision@5·MRR·nDCG@5와 검색·리랭킹 지연시간을 비교한다. 결과 CSV는 `evaluation/results/`에 저장한다.
- 검색 결과에서 나온 적 없는 문헌이 top-K에 나타나면 `unjudged`로 따로 세므로 라벨 후보를 추가 검토한다. 평가 문항이 라벨되기 전에는 성능 수치를 보고하지 않는다.
- Dense·Hybrid 질의 임베딩은 `OPENAI_API_KEY`가 필요하며, 평가 도구는 현재 임베딩 사용 비용을 계산하지 않는다. Cross-Encoder는 `sentence-transformers`와 모델 파일을 별도로 설치해야 한다.

### 특허 청구항 분석

특허 분석 입력은 `PatentSearchRequest`, 반환 계약은 `PatentReport`이며 `src.services.patent_service.analyze_patents()`에서 호출한다. 문헌별 청구항 원문·버전·번호·종속항 참조를 인용 근거로 보존하고, KIPRIS 청구항 조회가 비어 있거나 실패하면 초록 근거와 미확인 상태를 반환한다. 구현 흐름과 Mock 통합 예제는 [docs/patent_rag.md](docs/patent_rag.md)를 참고한다.
