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
│   ├── workflows/           # CI, 리뷰어 자동 지정, Notion PR 문서화, PR 분석
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
│   └── samples/             # 시연용 샘플
├── docs/                    # 기획·설계·개발 환경 문서, PR 분석 안내서(review-baseline.md)
├── evaluation/              # 평가 질문·정답 근거·평가 실행
├── frontend/                # 아이디어 검토 UI, 스타일, 비용 계산과 예시 보고서
├── prompts/                 # 아이디어 구조화·근거 검증·보고서 프롬프트
├── reports/                 # 생성한 경영진·R&D 보고서
├── scripts/
│   ├── *.py                 # 특허 수집·색인 생성 실행 스크립트
│   ├── create_notion_pr_page.mjs  # 병합 PR의 Notion 문서화 진입점
│   ├── notion/              # PR 본문 → Notion 블록·mermaid 다이어그램 변환
│   ├── github/              # PR 리뷰어 무작위 지정
│   └── review/              # PR 자동 분석(규칙 점검·Claude 분석·Notion 'PR 분석' 표와 영역 요약 카드 기록)
├── src/
│   ├── main.py · pipeline.py · schemas.py  # API 진입점·분석 흐름·공통 모델
│   ├── ingestion/           # 자료 수집·전처리·청크 생성
│   ├── retrieval/           # 색인 구축·정확 검색·의미 검색
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

- 원문·가공 데이터·검색 색인·생성 보고서는 로컬에 보관하며 Git 추적에서 제외.
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

## Streamlit 화면 시연

```powershell
.\.venv\Scripts\python.exe -m pip install -r requirements-ui.txt
.\.venv\Scripts\python.exe -m streamlit run frontend/app.py --server.address 127.0.0.1 --server.port 8505
```

상단 단계 표시와 본문 버튼으로 **아이디어 입력 → 핵심 구성 확인 → 문헌 선정·근거 검토 → 종합 보고서**를 진행한다. 왼쪽 단계 사이드바는 사용하지 않는다.
입력 화면은 큰 본문과 우측 최근 입력, 조사 화면은 좌측 구성·중앙 특허/시장 후보·우측 선택 목록, 보고서는 좌측 선택 문헌·우측 본문으로 구성한다.
핵심 구성은 최대 7개를 직접 편집·이동·삭제하며, 최소 2개 자료를 선택하면 보고서를 생성한다. 한 영역만 선택하면 다른 영역은 미확인으로 남긴다.
AI 추출·실검색·병렬 분석·가격 수집은 미연결이다. 정확한 예시 입력에만 가상 자료를 표시하고 보고서에 선택 자료만 포함한다.
`frontend/quick.py`가 입력·문헌 선택·보고서 규칙, `frontend/app.py`가 화면, `tests/test_quick_ui.py`가 단계별 검증을 담당한다.
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

## 환경변수

`.env.example`을 `.env`로 복사해 값을 채운다. `.env`는 Git에 커밋하지 않는다.

| 이름 | 용도 |
|---|---|
| `OPENAI_API_KEY` | 임베딩·답변 생성용 OpenAI API 키 |
| `KIPRIS_API_KEY` | KIPRIS Plus 특허 API 키 |
| `DART_API_KEY` | DART OpenAPI 공시 API 키 |
| `NAVER_CLIENT_ID` · `NAVER_CLIENT_SECRET` | NAVER API HUB(네이버클라우드) Application의 Client ID·Secret. 해당 Application에서 뉴스 검색 API 활성화 필요 |

GitHub Actions용 `NOTION_API_TOKEN`은 `.env`가 아니라 저장소의 **Settings → Secrets and variables → Actions**에 저장한다.
PR 분석용 `CLAUDE_CODE_OAUTH_TOKEN`·`NOTION_REVIEW_TOKEN`은 develop에서만 열리는 Environment `pr-analysis`에 저장한다([docs/development.md](docs/development.md#pr-자동-분석-githubworkflowspr-analysisyml)).

## 개발 도구와 협업 자동화

- **코드 포맷**: Python 코드는 [black](https://black.readthedocs.io/)으로 통일한다. 버전은 `requirements-dev.txt`에 고정하고, `pyproject.toml`의 `required-version`으로 다른 주 버전 실행을 막는다.
- **커밋 전 검사**: `pre-commit install` 후 커밋마다 black, 병합 충돌 표시, 개인키 노출, 대용량 파일, 줄끝 공백을 검사한다.
- **CI**: develop·main 대상 PR과 push에서 black 검사, pytest, 자동화 스크립트 테스트, Docker 이미지 빌드를 실행한다.
- **리뷰어 자동 지정**: PR에 리뷰어가 없으면 작성자를 제외한 팀원 중 한 명을 무작위로 지정한다. 후보는 저장소 변수 `REVIEWER_POOL`로 바꿀 수 있다.
- **Notion PR 문서화**: develop에 병합된 PR의 설명을 Notion 블록으로 변환하고, 원문·커밋·변경 파일을 코드 블록으로, 변경 구조와 서비스 연결 구조를 mermaid 다이어그램으로 기록한다.
- **PR 자동 분석**: develop 대상 PR이 열리거나 수정되면 규칙 점검과 Claude 분석 결과를 Notion 'RAG 기반 미니 프로젝트: IdeaLens' 아래 'PR 분석' 표에 태그(서비스 계층)·키워드·분석 내용과 함께 기록한다. 분석마다 새 행을 남기고, 수정본은 바뀐 파일만 다시 분석한다. 병합된 PR은 태그별 '영역 요약 카드' 표에 반영해 다음 분석의 출발점으로 쓴다. 참고용이며 승인·병합·GitHub 댓글은 하지 않는다. 판단 기준은 [docs/review-baseline.md](docs/review-baseline.md).
- **의존성 갱신**: Dependabot이 pip·pre-commit·GitHub Actions 버전 갱신 PR을 월 1회 묶어서 만든다.

## 구현 방향

- 목표 흐름: 아이디어·브리프 확정 → 시장·기업·특허 자료 수집 및 검색 → 근거 대조 → 구현 비용 검토 → 종합 보고서.
- 기존 백엔드의 아이디어·특허·시장 모델은 유지하며, 실제 검색 결과와 가격 데이터를 받는 UI 연결은 별도 구현한다.
- 데이터 출처: KIPRIS Plus, DART, 공공기관·연구기관·기업의 공식 자료.
- 뉴스는 이용조건 확인 후 활용하며, 사내자료 연계는 향후 확장 범위.
- 원문 구획과 청구항 구조를 보존하고, 각 주장에 출처·문헌 버전·원문 위치·링크를 연결.
- 정확 검색과 의미 검색을 병행하며, Chroma와 `text-embedding-3-small`을 초기 검토 대상으로 사용.
- 사실·해석·가설·미확인을 구분하고, 근거가 부족하면 판단을 보류. 최종 판단은 사용자가 수행.

## 평가 계획

- 검색 품질: Hit Rate@K, Recall@K, MRR.
- 답변 품질: 정확성, 근거 충실성, 인용 정확성.
- 동일 자료집에서 검색 방식을 비교하고, 동일 질문의 일반 LLM 응답과 RAG 응답을 평가.
