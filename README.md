# 아이디어 사업 검토 RAG

- 신제품·사업 아이디어의 시장 수요, 기업 동향, 관련 특허와 구현 비용을 연결하는 프로젝트.
- 주요 사용자: 사업 아이디어를 검토하는 기획자와 개발팀.
- 산출물: 확정 브리프, 근거가 연결된 조사 노트, 비용표와 다음 검증 과제.
- UI에는 가상 자료를 사용하는 시연 흐름과, API 키·로컬 색인이 있을 때 실제 아이디어 구조화·특허/시장 조사·근거 연결을 실행하는 흐름이 있다.

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
├── .streamlit/              # 화면 테마 설정, 호스팅 Secrets 형식 예시(secrets.toml.example)
├── AGENTS.md                # 팀 공용 Git·GitHub 및 코딩 에이전트 작업 규칙
├── configs/                 # 산업별 검색어·분류·검색 설정
├── data/
│   ├── raw/                 # 수집한 원문
│   ├── processed/           # 정규화 문서와 검색 청크
│   ├── indexes/             # 검색 색인
│   ├── patents/             # 특허 원문·정제 데이터·Chroma 벡터 저장소
│   ├── market/              # 시장 자료 원문·정제 데이터
│   └── samples/             # 시연용 샘플 아이디어·시장 결과(MarketReport) 예시
├── deploy/                  # 공용 Chroma·HTTPS 중계·개인 키 인증 배포 설정
├── docs/                    # 기획·설계·개발 환경 문서, 프로젝트 목표·PR 분석 안내서(review-baseline.md)
├── evaluation/              # 평가 질문·정답 근거·평가 실행
├── frontend/                # 아이디어 검토 UI, 실제 분석 화면 보조(live.py), 스타일, 비용 계산과 예시 보고서
├── prompts/                 # 아이디어 구조화·근거 검증·보고서 프롬프트
├── reports/                 # 생성한 경영진·R&D 보고서
├── scripts/
│   ├── idealens.py          # 팀원용 통합 실행 도구(환경 점검·화면 실행·수집·색인·테스트, 표준 라이브러리만 사용)
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

## 빠른 시작 (팀원용)

필요: Docker Desktop 실행, Python 3.9 이상(통합 실행 도구용). macOS는 `python3`, Windows는 `py`(없으면 `python`)를 쓴다.

```bash
python3 scripts/idealens.py setup      # .env가 없을 때만 예시 복사 → 키 입력 후 이미지 빌드
python3 scripts/idealens.py doctor     # Docker·키(이름만 표시)·공용 Chroma·색인·포트 점검
python3 scripts/idealens.py ui         # 화면 실행 → http://localhost:8505 (make ui)
python3 scripts/idealens.py logs | stop | test
```

| 명령 | 필요한 키 |
|---|---|
| `ui`(실제 분석) | `OPENAI_API_KEY`, `KIPRIS_API_KEY`(특허 실시간 검색), 공용 색인을 쓰면 `CHROMA_*` |
| `data market` | `NAVER_CLIENT_ID`·`NAVER_CLIENT_SECRET`, `OPENAI_API_KEY` |
| `data patents` | `KIPRIS_API_KEY`, `OPENAI_API_KEY` |

- `data market`·`data patents [--field-id SF-02]`는 호출량을 보여 주고 확인을 받은 뒤 실행한다(API 비용 발생). 공용 Chroma에 적재할 때는 `--yes`로도 확인을 생략할 수 없으며, 색인은 한 사람만 실행한다. 시장 수집이 중간에 실패하면 같은 명령으로 오늘 미수집 키워드만 이어서 수집한다.
- 공용 Chroma 키는 관리자에게 개인 메시지로 받아 개인 `.env`에만 둔다(Notion·GitHub 게시 금지). HTTPS 키 접속은 `CHROMA_PORT=443`·`CHROMA_SSL=true`다.
- Python이 없으면 `docker compose up -d ui`로 화면만 실행할 수 있다.

**문제 해결**

| 증상 | 조치 |
|---|---|
| Docker 엔진에 연결할 수 없음 | Docker Desktop을 실행한다 |
| 이미지가 없음·streamlit 버전 다름 | `setup`으로 다시 빌드한다(첫 빌드는 수 분) |
| 공용 Chroma HTTP 401·403 | `CHROMA_API_KEY`를 확인하고, 폐기된 키면 재발급을 요청한다 |
| `CHROMA_API_KEY requires HTTPS` | `CHROMA_SSL=true`, `CHROMA_PORT=443`으로 바꾼다 |
| 공용 Chroma 연결 실패 | 네트워크·서버 상태를 확인한다. 시연은 예시 흐름(가상 시연)으로 전환할 수 있다 |
| 포트 8505 사용 중 | 다른 프로그램을 끄거나 `IDEALENS_UI_PORT`(셸 환경변수)로 포트를 바꾼다 |
| `.env` BOM·UTF-16 경고 | BOM 없는 UTF-8로 다시 저장한다(Windows 메모장 주의) |
| `.env`를 바꿨는데 반영되지 않음 | `python3 scripts/idealens.py ui --recreate` |

## 실행 방법

Docker Desktop(또는 Docker Engine + Compose v2.24 이상)을 기준으로 한다.

```bash
cp .env.example .env              # API 키 입력 (make env와 동일)
docker compose up -d --build      # 개발(app)·화면(ui) 컨테이너 실행 (make up)
docker compose up -d ui           # Streamlit 화면만 실행 → http://localhost:8505 (make ui)
docker compose exec app bash      # 컨테이너 셸 접속 (make shell)
docker compose run --rm app python -m pytest   # 테스트 (make test)
docker compose down               # 종료 (make down)
```

- `app`·`ui` 컨테이너는 같은 이미지를 쓰고 저장소 전체를 `/app`에 마운트하므로 코드 수정이 바로 반영된다. 로컬 Chroma 저장소(`data/patents/chroma/`, `data/market/chroma/`)와 수집 데이터는 호스트에 유지된다.
- `ui`는 호스트의 `127.0.0.1:8505`에만 열린다. 화면 오류에는 예외 종류만 표시하고 상세 내용은 `docker compose logs ui`(`make ui-logs`)로 본다. `.env`를 바꾸면 `docker compose up -d --force-recreate ui`로 다시 만든다.
- 의존성을 바꾸면 `docker compose build app`(`make build`)으로 이미지를 다시 만든다.
- Docker 없이 실행할 때는 Python 3.12 가상환경에 고정 버전을 설치한다. 다른 버전의 Streamlit에서는 화면이 정상 동작하지 않는다.

```bash
uv venv --python 3.12 .venv
uv pip install --python .venv/bin/python -r requirements-ui.txt   # Windows: .venv\Scripts\python.exe
.venv/bin/python -m streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8505   # make ui-host
```
- `make help`로 공용 명령 목록을 확인한다. 상세 내용은 [docs/development.md](docs/development.md)를 참고한다.

## 공용 Chroma 연결

기본값은 기존 로컬 Chroma다. 팀 공용 서버는 HTTPS 주소·포트 `443`·`CHROMA_SSL=true`·개인별 `CHROMA_API_KEY`로 접속한다. 이 방식은 Google 로그인이나 터널 실행이 필요 없다. API 키는 HTTPS에서만 전송하며 서버 앞의 인증 서비스가 해시를 검증한다. 기존 IAP 터널은 보조 접속 경로로 유지한다. 특허·시장 저장과 검색이 같은 원격 DB를 사용하며 연결 실패 시 로컬로 전환하지 않는다. 기존 로컬 자료는 자동 이관되지 않는다. 설정 예시·서버 배포·키 폐기·백업은 [공용 Chroma 안내](docs/shared-chroma.md)를 참고한다. 화면의 실제 분석은 `CHROMA_HOST`가 설정되면 이 공용 색인을 쓴다.

`pytest`는 공용 DB 설정을 격리하고 로컬 테스트 저장소를 사용한다. 실제 서버 연결 검증은 별도로 수행한다.

## Streamlit 화면 시연

```bash
make ui                         # ui 컨테이너로 Streamlit 실행 → http://localhost:8505
make patent-collect ARGS="--field-id SF-02 --limit 20 --include-claims"
make patent-index ARGS="--field-id SF-02"
```

홈 로고와 클릭 가능한 상단 1~4단계·본문 버튼으로 **아이디어 입력 → 핵심 구성 확인 → 문헌 선정·근거 검토 → 종합 보고서**를 진행한다. 왼쪽 단계 사이드바는 사용하지 않는다.
홈은 배경과 경계 없이 이어지는 조사 문서 비주얼과 입력 바로가기를 제공한다. 표지에는 특허 구성 도면·시장 흐름 그래프·근거 연결선과 유리 반사·그림자를 표현한 장식 돋보기를 배치하며 실제 특허·수요 데이터로 표시하지 않는다. 단계마다 아이보리·연녹색·크림·연청색으로 종이 색이 바뀌며 남은 장수가 3→2→1→0장으로 줄어든다. 앞뒤 이동 시 종이의 들림·회전·그림자를 표현하고 동작 줄이기 설정을 따른다. `frontend/assets/idealens-symbol.svg`와 `idealens-logo.svg`는 문서·돋보기·근거 연결을 결합한 심볼과 글자 로고다. 로고 버튼은 홈 이동 기능을 유지한다. `frontend/presentation.py`가 홈 비주얼을, `frontend/styles.css`가 종이 재질과 전환을 관리한다. 제공된 사진은 디자인 참고로만 사용하며 화면의 도해와 종이는 코드로 표현한다.
입력 화면은 큰 본문과 우측 최근 입력, 조사 화면은 좌측 구성·중앙 특허/시장 후보·우측 선택 목록, 보고서는 좌측 선택 문헌·우측 본문으로 구성한다.
핵심 구성은 최대 7개, 검토 질문은 최대 5개를 조건과 함께 확정한다. 3단계는 자동 연결 결과를 먼저 보여주며 사용 맥락·해결 과제·기술 구성·요구 성능·도입 제약·근거 범위의 판단 과정을 펼쳐 확인한다. 문헌 제외와 결과 수정은 선택 사항이다. 최소 2개 자료로 부분 보고서를 열 수 있으며, 질문별 근거 부족은 통합 판단 보류로 표시한다.
정확한 기본 예시에만 가상 자료 4건과 사전 작성된 연결 초안을 자동 배치한다. `OPENAI_API_KEY`가 있으면 직접 입력한 아이디어는 `핵심 구성 확인하기 →`에서 AI 구조화(빈 항목은 최대 2회 재질문)를 거쳐 실제 분석 흐름으로 이어진다. 3단계에서 특허(선택 분야 색인·KIPRIS)와 시장 조사를 병렬로 실행하고 영역별 상태·소요 시간·근거를 보여 준다. 구성·분야가 그대로면 조사 결과를 재사용해 질문 연결만 다시 만들며, 한 번에 하나의 분석만 실행한다. 키가 없으면 구성만 작성하는 시연 경로로 진행한다. 예시도 실제 수요·성능 검증으로 표시하지 않는다.
`frontend/automatic.py`는 시연 규칙과 팀 보고서 모델의 근거 변환을 담당한다. 실제 실행은 `src.pipeline.run_pipeline`에서 특허·시장 서비스를 호출하고 `src.generation.report_builder`가 질문별 6개 기준으로 연결한다. 인용 ID는 영역별로 구분하며 한쪽 근거가 없으면 연결 판단을 보류한다. `frontend/quick.py`는 보고서 규칙, `frontend/app.py`는 화면을 담당한다. 수정·제외는 보고서에도 반영하고 이전 스냅샷을 무효화한다.
[실행·시연 가이드](docs/ui-guide.md)와 [참고 화면 구조 및 연결 계약](docs/quick-research-ui.md)을 참고한다. 실제 보고서에는 구현 비용 항목을 입력할 수 있고, 누락 금액을 0으로 간주하지 않는 소계를 함께 표시한다. Streamlit 포트는 8505이며 `make ui`(Docker) 또는 `make ui-host`(고정 버전 가상환경)로 실행한다.

### 시장 뉴스 수집·정제

시장 조사 전체 흐름(아이디어 구조화 → 수집·색인 → 차원별 검색 → 분석 생성·인용 검증 → 평가)과
단계별 코드 위치는 [docs/market_research.md](docs/market_research.md)를 참고한다.

```bash
python -m src.ingestion.news_client --keyword-id smart_factory --max-items 10   # 키워드 1개 수집
python -m src.ingestion.news_client                                             # 전체 키워드 수집
python -m src.ingestion.market_processor                                        # 원본 → MarketDocument 정제
```

- 시장·특허 공통 기술 분야, 분야별 검색어 및 시장 수집 기준은 `configs/technology_areas.yaml`에서 관리한다. 공통 시장 키워드는 `shared_market_keywords`, 분야별 시장 키워드와 특허 키워드는 각 `technology_areas` 항목에 둔다.
- NAVER API HUB 뉴스 검색 API의 제목·요약·링크·발행일만 `data/market/raw/news_{keyword_id}_{수집일}.json`에 저장한다.
- 정제 단계는 같은 URL 기사를 합치고, 제목 유사도 0.8 초과·발행일 3일 이내 기사를 같은 `dup_group`으로 묶어 대표 1건만 `data/market/processed/market_docs.jsonl`에 저장한다.

### 특허 문서 수집·분야별 사전 색인

```bash
python -m src.ingestion.patent_processor --field-id SF-02 --limit 20 --include-claims
python -m src.ingestion.patent_processor --field-id SF-05 --limit 20 --include-claims
```

- 공통 분야 분류와 초기 검색어는 `configs/technology_areas.yaml`에서 SF-01~SF-08로 관리한다. 현재 우선 특허 색인 대상은 SF-02 AI 비전 품질검사와 SF-05 지능형 공정제어다.
- `--field-id`는 분야 설정의 검색어로 KIPRIS 자료를 수집해 `data/patents/processed/patent_docs.jsonl`에 누적하고, 새 초록·청구항 청크를 `data/patents/chroma/`에 색인한다. 기존 색인 청크는 변경이 없으면 다시 임베딩하지 않는다.
- `--include-claims`는 문헌별 청구항 상세 API를 조회한다. API에서 확보하지 못한 청구항은 생성하지 않고 초록만 색인한다. `KIPRIS_API_KEY`와 청구항 API 이용 권한이 필요하다.
- 검색어 계획으로 별도 수집·색인을 하려면 `python -m scripts.collect_patents --request <PatentSearchRequest.json> --field-id SF-02 --include-claims` 후 `python -m scripts.build_patent_index --field-id SF-02`를 실행한다. `PatentQueryPlan`은 기술 요소를 최대 5개까지 허용한다.
- KIPRIS 검색·청구항 API 원본 XML과 키를 제외한 요청 메타데이터는 `data/patents/raw/`에 저장한다. 해당 폴더는 로컬 전용이며 Git 추적 대상에서 제외된다.
- 색인 시 문서 임베딩 API 호출이 필요하다(`OPENAI_API_KEY`). 이후 문서 벡터는 로컬 Chroma에서 재사용한다. Dense/Hybrid 검색의 질의 임베딩은 검색 때 별도로 생성된다.
- `PatentSearchRequest.technology_area_id`를 지정하면 검색 결과를 해당 분야로 제한한다. 원문 JSONL과 Chroma DB는 로컬에 저장되고 Git에는 포함되지 않는다.
- 기존 SF-05 시장 평가 샘플·라벨은 현장 작업자용 LLM 음성 어시스턴트 기준이다. 과거 검색어는 `legacy_market_keywords`에 기록하며 신규 뉴스 수집에는 사용하지 않는다. 새 SF-05 시장 성능을 평가하려면 아이디어 샘플을 갱신하고 자료를 다시 수집·라벨링해야 한다.

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

- `search_with_relevance`는 차원별 검색 결과마다 `gpt-4o-mini`로 관련 여부·이유를 판정하고(기준: `prompts/market_label_judge.md`), 관련 건수로 차원별 충분성 상태(`sufficient` 2건 이상 · `limited` 1건 · `insufficient` 0건 · `no_results` · `error`)를 붙여 반환한다. `OPENAI_API_KEY`가 필요하다.
- 검색 거리는 관련성을 구분하지 못해(평가 라벨 기준 AUC 0.52) 충분성 판단에 쓰지 않는다. 판정 모델 선택 근거는 [docs/market_research.md](docs/market_research.md#충분성-판정).

### 시장 조사 실행 (MarketReport)

```bash
python -m src.services.market_service --idea-id SF-01                                         # MarketReport JSON 출력
python -m src.services.market_service --idea-id SF-01 --out data/samples/market_reports/SF-01.json   # 파일로 저장
```

- `run_market_research(MarketSearchRequest)`가 차원별 검색 → 관련성 판정 → 시장 분석 생성·인용 검증을 실행해 `MarketReport`(`src/schemas.py`)를 반환한다. 분석 규칙은 `prompts/market_analysis.md`, 생성·검증은 `src/generation/market_analysis.py`에서 관리한다. `OPENAI_API_KEY`가 필요하다.
- 사실 문장은 인용 근거(`evidence`의 `citation_id`)가 있어야 하고, 인용 기사·아이디어 입력에 없는 숫자가 있거나 수치에 기준 연도가 없으면 재생성(최대 2회)하거나 해당 문장을 제거한다. 판정은 차원별 충분성 상태와 근거 성격으로 제한하고(근거 1건이거나 뉴스 같은 사업 신호뿐이면 최대 '신호만 확인'), 기대는 아이디어 항목이 모름이면 미확인으로 둔다(가격 ← 수익모델, 구매자 ← 고객).
- `data/samples/market_reports/`에는 SF-01~SF-05 실행 결과 예시가 있다. 로컬 수집 뉴스 기준이므로 다시 수집하면 내용이 달라진다.

```bash
python -m src.generation.market_markdown data/samples/market_reports/SF-01.json   # 종합 보고서용 마크다운 섹션 출력
```

- `market_report_to_markdown(report)`는 `MarketReport`를 종합 보고서의 '시장 조사 및 분석 결과' 섹션(차원별 판정 요약 표, 차원별 문장·검증 과제, 미확인 사항, 근거 목록)으로 바꾼다. LLM을 부르지 않으며, 인용은 UI와 같은 `M:{citation_id}`로 쓴다.
- 아이디어 입력·시장 조사 진입점의 입력·출력·오류 처리 약속은 [docs/api_contract.md](docs/api_contract.md)에 정리한다.

### 아이디어 구조화

```bash
python -m src.generation.idea_parser "중소 부품 공장에 협동로봇과 비전 카메라를 턴키로 설치해 준다"
```

- 아이디어 한 문장을 `gpt-4o-mini`로 문제(`problem`)·기술(`technology`)·고객(`customers`)·차별점(`difference`)·수익모델(`revenue`)로 나눈다. 규칙은 `prompts/idea_parser.md`에서 관리하며, 문장에 없는 항목은 추측하지 않고 비워 둔다. `OPENAI_API_KEY`가 필요하다.
- 빈 항목은 사용자에게 최대 2회 재질문한다. '모름'으로 답했거나 끝까지 비어 있는 항목은 `unknown`으로 확정하고, 항목별 출처(`extracted`·`user_answer`·`unknown`)를 함께 남긴다.
- 완성된 결과(`IdeaDraft`)는 `build_requests`로 특허·시장 공통 입력(`StructuredIdea`)과 검색 요청(`PatentSearchRequest`·`MarketSearchRequest`)으로 변환한다.
- Streamlit에서 `핵심 구성 확인하기 →`(키가 있을 때) 또는 `AI로 항목 초안 만들기 · 재질문`으로 구조화·재질문을 실행하고 SF-02/SF-05 특허 색인을 선택할 수 있다. 입력은 1,000자까지다. 확인한 질문으로 특허·시장 통합 조사를 실행하고 원문 근거(청구항 위치)와 출원·공개일을 확인한다.
- `src.pipeline.run_pipeline`의 입력·출력 및 보류 규칙은 [docs/api_contract.md](docs/api_contract.md#3-특허-조사-및-통합-파이프라인)에 명시한다.

### 통합 분석 실행·점검

```bash
docker compose run --rm -T app python -m src.pipeline status --json          # 키·색인 준비 상태(값 미출력, 생성 호출 없음)
docker compose run --rm app python -m src.pipeline run --idea-id SF-02 --out report.json  # 샘플 아이디어 실분석(API 비용 발생)
```

- 시장·특허 조사는 병렬로 실행하며 영역별 제한 시간과 오류를 따로 기록한다. 색인이 없거나 키가 없는 영역은 호출하지 않고 '실행 안 함'으로 표시한다.
- 색인 점검은 컬렉션을 새로 만들지 않는다. 오류 문구의 API 키는 가린 뒤 표시한다. 상세 규칙은 [연결 계약](docs/api_contract.md#통합-흐름의-실행오류-처리)을 참고한다.

- 입력 가드레일: LLM 호출 전 규칙 검사(`src/generation/input_guard.py`: 길이, 지시 무시·시스템 프롬프트 공개 등 조작 표현)와 같은 LLM 호출의 `input_status` 판정(`ok`·`off_topic`·`unsafe`)으로 주제 이탈·프롬프트 조작·유해 목적 입력을 거절한다. 거절되면 `status="rejected"`와 안내 문구(`rejection_reason`)를 반환하고 검색 요청을 만들지 않는다. 재질문 답변도 규칙 검사를 거친다. 기준은 [docs/market_research.md](docs/market_research.md#입력-가드레일).

## 환경변수

`.env.example`을 `.env`로 복사해 값을 채운다. `.env`는 Git에 커밋하지 않는다.

| 이름 | 용도 |
|---|---|
| `OPENAI_API_KEY` | 앱의 임베딩·답변 생성용 OpenAI API 키 |
| `KIPRIS_API_KEY` | KIPRIS Plus 특허 API 키 |
| `DART_API_KEY` | DART OpenAPI 공시 API 키 |
| `NAVER_CLIENT_ID` · `NAVER_CLIENT_SECRET` | NAVER API HUB(네이버클라우드) Application의 Client ID·Secret. 해당 Application에서 뉴스 검색 API 활성화 필요 |
| `IDEALENS_MARKET_TIMEOUT` · `IDEALENS_PATENT_TIMEOUT` | (선택) 통합 분석의 영역별 제한 시간(초). 기본 120·180 |
| `IDEALENS_SERIAL` | (선택) `1`이면 시장·특허 조사를 순차 실행 |
| `IDEALENS_APP_PASSWORD` | (호스팅 배포) 접속 비밀번호. 비어 있으면 비밀번호 화면을 띄우지 않는다(로컬 실행) |
| `CHROMA_HOST`·`CHROMA_PORT`·`CHROMA_SSL`·`CHROMA_API_KEY` | (선택) 팀 공용 Chroma 접속. 비우면 로컬 Chroma. HTTPS 키 접속은 `443`·`true` |

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
- 백엔드 아이디어·특허·시장 모델(`src/schemas.py`)을 결과 계약으로 유지하고 `src.pipeline.run_pipeline`에서 두 조사와 통합 보고서 생성을 연결한다.
- 데이터 출처: KIPRIS Plus, NAVER 뉴스 검색 API(교육 목적, 프로젝트 종료 시 폐기), DART, 공공기관·연구기관·기업의 공식 자료. 사내자료 연계는 향후 검토 범위.
- 원문 구획과 청구항 구조를 보존하고, 각 주장에 출처·문헌 버전·원문 위치·링크를 연결.
- 검색은 공통 엔진에서 의미 검색(dense)·단어 검색(BM25)·결합(hybrid) 중 선택하며, 임베딩은 `text-embedding-3-small`, 색인은 로컬 Chroma 또는 환경변수로 지정한 공용 Chroma를 사용.
- 시연은 Streamlit UI로 하며 Streamlit Community Cloud(`main` 배포, 앱 비밀번호, [배포 안내](docs/deploy-streamlit-cloud.md)) 또는 로컬 Docker로 실행한다. 팀 색인은 공용 Chroma, 로컬 Chroma(`data/patents/chroma/`·`data/market/chroma/`)는 개인 실험·테스트용이다.
- 사실·해석·가설·미확인을 구분하고, 근거가 부족하면 판단을 보류. 최종 판단은 사용자가 수행.

## 평가 계획

- 검색 품질: Hit@K, Recall@K, Precision@K, MRR, nDCG@K 및 검색 지연시간.
- 답변 품질: 정확성, 근거 충실성, 인용 정확성.
- 동일 자료집에서 검색 방식을 비교하고, 동일 질문의 일반 LLM 응답과 RAG 응답을 평가.

### 시장 검색 평가

```bash
python -m evaluation.market_labeling init      # ideas.json × 5개 차원 → evaluation/market_cases.json 문항 생성
python -m evaluation.market_labeling export    # 라벨링 후보 → evaluation/labels/market_candidates.csv
python -m evaluation.market_judge prelabel     # (선택) gpt-4o-mini 라벨 초안 → evaluation/labels/market_llm_labels.csv
python -m evaluation.market_judge agreement    # (선택) 사람 라벨과 LLM 초안의 일치율·kappa
python -m evaluation.market_judge merge        # (선택) 빈 relevant만 LLM 초안으로 채움
python -m evaluation.market_labeling extend    # (방식 비교 전) dense·bm25·hybrid 상위 5건 중 새 문서를 후보에 추가
python -m evaluation.market_labeling import    # relevant(1/0)를 채운 CSV → 문항별 정답 source_id 반영
python -m evaluation.evaluate market --idea-ids SF-01,SF-02,SF-03,SF-04 --mode dense --label refreshed
python -m evaluation.evaluate market --idea-ids SF-01,SF-02,SF-03,SF-04 --mode bm25 --label refreshed
python -m evaluation.evaluate market --idea-ids SF-01,SF-02,SF-03,SF-04 --mode hybrid --label refreshed
python -m evaluation.evaluate market --mode hybrid --rerank --label baseline  # 선택 의존성 필요
python -m evaluation.evaluate relevance                 # 관련성 판정(gpt-4o-mini) vs 사람 라벨 → evaluation/results/
python -m evaluation.evaluate guardrail                 # 입력 가드레일 차단율·오차단율 → evaluation/results/
python -m evaluation.answer_eval --limit 5              # LLM 단독 vs RAG 답변 품질(LLM 평가, API 비용 발생)
python -m evaluation.patent_labeling export              # SF-02/SF-05 특허 후보 CSV 내보내기 (사람 라벨 필요)
```

- 시장 평가에는 사람 라벨 25문항이 있으나 SF-05 라벨은 이전 '현장 작업자용 LLM 음성 어시스턴트' 기준이다. 현재 SF-05(지능형 공정제어)와 맞지 않으므로 최신 비교는 `--idea-ids SF-01,SF-02,SF-03,SF-04`로 20문항을 실행하고, SF-05는 새 수집·라벨 이후 포함한다.
- 특허 평가셋은 현재 로컬 색인이 준비된 SF-02·SF-05에서 각각 기술 요소 질의로 구성한다. `patent_cases.json`의 사람 정답은 초기화 상태이며, CSV 라벨을 작성해 import한 뒤에만 검색 지표를 계산한다.
- 검색 CSV에는 mode, 모델, prompt 적용 여부, 커밋 ID가 기록된다. LLM 단독/RAG 답변 비교는 `answer_eval`의 LLM 판정 점수이며 사람 정답 평가와 구분해야 한다.
- 라벨링 후보는 문항마다 벡터 검색 상위 8건과 그 아래 순위에서 차원 표현(가격·비용, 도입·사례 등)이 들어간 4건, 그리고 `extend`로 추가한 bm25·hybrid 상위 5건 중 새 문서다. 방식 비교 결과는 [docs/market_research.md](docs/market_research.md#시장-검색-방식-비교). 라벨 기준과 LLM 초안·사람 검토 절차는 [evaluation/market_labeling.md](evaluation/market_labeling.md).
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
