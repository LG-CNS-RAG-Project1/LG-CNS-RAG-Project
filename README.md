# 아이디어 사업 검토 RAG

홈 첫 진입은 제목 윗줄·아랫줄 → 읽기 시간 → 제목 이동 → 설명·문서·돋보기 순으로 재생한다. 완료 여부는 브라우저 연출 종료 후 전달하므로 초기 화면 갱신만으로 연출을 생략하지 않는다. 같은 세션의 메뉴 왕복에는 반복하지 않고, 동작 줄이기 설정이나 사용자 직접 조작 시 즉시 최종 화면을 표시한다. 홈페이지 전용 파일의 검토 담당자는 `.github/CODEOWNERS`에 지정하며, 분석·보고서 변경 시 홈 보존 원칙은 `AGENTS.md`를 따른다.

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
│   ├── workflows/           # CI, 리뷰어 자동 지정, PR 분석, main 승격 PR, SCC 배포 스모크
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
│   ├── market/              # 시장 자료 원문·정제 데이터·검색 관심도·조달 공고 캐시
│   └── samples/             # 시연용 샘플 아이디어·시장 결과(MarketReport) 예시
├── deploy/                  # 공용 Chroma·HTTPS 중계·개인 키 인증 배포 설정
├── docs/                    # 기획·설계·개발 환경 문서, 프로젝트 목표·PR 분석 안내서(review-baseline.md)
├── evaluation/              # 평가 질문·정답 근거·평가 실행
├── frontend/                # 아이디어 검토 UI, 실제 분석 화면 보조(live.py), 스타일, 비용 계산과 예시 보고서, SCC 전용 의존성(requirements.txt)
├── prompts/                 # 아이디어 구조화·근거 검증·보고서 프롬프트
├── reports/                 # 생성한 경영진·R&D 보고서
├── scripts/
│   ├── idealens.py          # 팀원용 통합 실행 도구(환경 점검·화면 실행·수집·색인·테스트, 표준 라이브러리만 사용)
│   ├── *.py                 # 특허 수집·색인 생성 실행 스크립트
│   ├── scc_smoke.py · check_scc_deps.py  # SCC 배포 스모크(브라우저 확인)·SCC 의존성 점검
│   ├── notion/              # Notion 블록 도우미, 코드 해석 기반 서비스 아키텍처 그림(mermaid) 생성
│   ├── github/              # PR 리뷰어 무작위 지정, develop → main 승격 PR
│   └── review/              # PR 자동 분석(규칙 점검·GPT 분석(Codex 구독 또는 API)·Notion PR 페이지와 영역 요약 카드 기록)
├── src/
│   ├── main.py · pipeline.py · schemas.py  # API 진입점·분석 흐름·공통 모델
│   ├── analysis/           # 특허 분류통계와 기술 동향 집계
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
- 서비스 연결 구조는 [docs/architecture.md](docs/architecture.md)의 mermaid 다이어그램으로 관리. 실제 구현·데이터 준비·V1.0 출시 게이트 기준선은 [RAG 서비스 현황](docs/rag-service-baseline.md)을 참고한다.

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

홈은 서비스 소개·왜 IdeaLens인가·내 기록과 돋보기 시작 버튼으로 구성한다. 상단에는 홈으로 이동하는 IdeaLens 로고만 표시하고, 페이지 이동은 고정 바로가기 바에서 제공한다. 첫 방문에는 다른 내용을 감춘 채 메인 문구의 윗줄·아랫줄이 차례로 나타나고, 두 줄을 읽을 시간을 둔 뒤 실제 제목이 제자리로 이동한다. 이어서 메뉴·설명·문서·돋보기가 나타난다. 새로고침하면 연출을 다시 볼 수 있고 같은 세션에서 홈으로 돌아올 때는 반복하지 않는다. 클릭·키 입력·스크롤·크기 변경 시 연출을 마무리하며, 동작 줄이기 설정에서는 즉시 표시한다. 시작 전에는 입력 폼을 표시하지 않는다. 조사 화면은 **아이디어 구체화 → 특허·시장 검토 → 종합 보고서**의 세 단계이며 가운데 단계의 특허·시장 탭으로 결과를 나눠 본다.

`frontend/quick_nav.py`의 고정 바로가기 바는 넓은 화면에서는 오른쪽, 좁은 화면에서는 하단에 표시한다. 조사 화면에서는 홈·아이디어·특허·시장·보고서·내 기록·맨 위로, 홈·소개·차별점·기록 화면에서는 페이지 메뉴와 조사 시작/계속을 제공한다. 처음 홈에서는 돋보기만 조사 시작 버튼으로 사용한다. 다른 페이지로 이동한 후 조사 계속을 누르면 입력과 결과·기존 단계를 복원하며, 페이지를 바꾸면 맨 위에서 시작한다. 아직 열 수 없는 단계는 비활성화하고 분석 중에는 완료된 단계의 읽기 전용 미리보기를 연다. 이동만으로 재분석하거나 결과를 초기화하지 않으며 로그인 전에는 표시하지 않는다.

아이디어 초안은 제목·문제·기술·고객·대안·세그먼트·구성요소·가치 가설을 확인·수정할 수 있다. 분석 실행 후에는 백그라운드에서 특허 조사 → 시장 분석 → 최종 검토를 진행한다. 실제 완료 콜백으로 대기·분석 중·완료·근거 부족·실패를 표시하고 경과 시간과 현재 작업을 설명한다. 화면을 이동해도 분석은 계속되며 읽던 결과 화면은 자동 전환하지 않는다. 취소 후 새 입력과 늦은 결과가 섞이지 않게 한다. 이미 전송한 요청은 즉시 중단되지 않아 비용이 발생할 수 있다.

특허 보고서는 최종 비교 문헌 5~8건을 목표로 하고, 관련 근거가 부족하면 문헌 수를 임의로 채우지 않는다. 특허 비교 궤도를 바로 보여주며, 주의점·공통 개선 제안과 문헌별 설계 대안은 짧은 요약 및 한국어 상세 팝업으로 구분한다. 특허 통계는 종합보고서에서 검색 후보와 색인 범위를 분리해 표시하며, 출원연도·IPC 분포와 메타데이터 보유율을 함께 보여준다. 시장 보고서는 검색 관심도 시계열, 뉴스 키워드 동시 출현, 인용이 연결된 차원별 관찰과 추가 확인 항목을 중심으로 구성한다. 관련 검색에서 연결된 DART 기업의 공시 발췌는 회사·사업연도·섹션·근거 ID로 추적할 수 있지만, 경쟁사 여부나 특허 보유 관계를 단정하지 않는다. 종합 보고서는 `보고서 요약`과 `보고서 원문` 두 탭으로 구성한다. 요약에는 양쪽 근거 ID가 연결된 결론, 영역별 근거, 특허 검색 통계, 한계와 다음 확인을 우선 보여준다. 원문 탭에는 상세 인용 추적, 비용 분석·메모, PDF·Markdown 다운로드와 기록 보관을 둔다. 검색 관심도는 상대 지수이고 키워드 네트워크는 뉴스 내 동시 출현이므로 시장 수요 증거로 사용하지 않는다. 상세 인용은 보고서 원문 및 판단 근거에서 확인한다. 한 영역이 미완료이거나 양쪽 근거 연결이 없으면 통합 결론을 보류한다. 누락된 항목이나 수치를 추정하지 않으며 UI에서 추가 LLM 호출이나 데이터 재정제를 하지 않는다. 뉴스·기업 자료를 직접 구매 수요로 간주하지 않는다.

PDF·Markdown 다운로드와 현재 세션 최대 20개 기록 보관, JSON 내보내기·불러오기를 제공한다. PDF는 ReportLab과 포함된 Nanum Gothic OFL 글꼴을 사용한다. 구조화된 시각화도 기록에 보관하지만 계정별 영구 DB 기록은 연결하지 않았다. 세션이 종료될 수 있으므로 개인 기록 파일로 보관한다. PDF는 인용과 표를 포함한 보고서 원문·비용·메모를 내보내며 화면 차트 이미지는 포함하지 않는다. 키는 기록이나 다운로드에 포함하지 않는다.

화면은 `frontend/app.py`, 홈 연출은 `frontend/landing_motion.py`, 소개는 `frontend/introduction.py`, 보고서·기록은 `frontend/workspace_view.py`, 시각화는 `frontend/report_overview.py`, PDF는 `frontend/report_export.py`, 백그라운드 상태는 `frontend/workflow.py`에서 관리한다. [실행·시연 가이드](docs/ui-guide.md)와 [분석 계약](docs/idea-business-review.md)을 참고한다. `python scripts/idealens.py ui`로 실행하고 `.env` 변경은 `ui --recreate`로 반영한다. 실제 분석은 API 비용이 발생하며 시연 자료는 가상임을 표시한다.

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
- 정제 단계는 기사의 아이디어 연결(`idea_ids`)을 수집 당시 값이 아니라 현재 `configs/technology_areas.yaml`의 키워드 설정으로 정하고, 설정에 없는 키워드로 수집한 기사는 제외한다(원본 파일은 유지). 같은 URL 기사를 합치고, 제목 유사도 0.8 초과·발행일 3일 이내 기사를 같은 `dup_group`으로 묶어 대표 1건만 `data/market/processed/market_docs.jsonl`에 저장한다.

### DART 사업보고서 수집·정제

시장 근거는 뉴스와 DART 사업보고서를 함께 쓴다. 두 자료가 모두 있어야 시장 색인을 만든다.

```bash
python -m src.ingestion.dart_client                         # 설정 기업의 최신 사업보고서 원문 수집
python -m src.ingestion.dart_processor                      # '사업의 내용' 본문 → 청크 MarketDocument
```

- 기업 목록·관련 아이디어·선정 이유는 `configs/dart_companies.yaml`에서 관리한다. `DART_API_KEY`가 필요하다.
- 기업마다 최신 사업연도 사업보고서를 고르고, 기재정정 보고서가 있으면 가장 늦게 접수된 것을 쓴다. 원문 XML과 메타데이터는 `data/market/raw/dart/`에 저장한다.
- 정제 단계는 'II. 사업의 내용'의 사업의 개요·주요 제품·매출 및 수주상황·주요계약·기타 참고사항 본문(표 제외)을 800자 이하 청크로 나눠 `data/market/processed/dart_docs.jsonl`에 저장한다. 청크는 줄·문장 끝에서 끝나고, 다음 청크는 최대 150자 겹치되 줄·문장 시작에서 시작한다. 표 구조 보존 추출은 별도 작업이다(#29).
- 기업은 `idea_terms`의 아이디어 용어가 '사업의 내용'에 나올 때만 그 아이디어에 연결하고, 용어별 등장 횟수를 `data/market/processed/dart_selection.json`에 남긴다.
- DART 본문은 모두 기업 주장(`company_claim`)으로 저장한다. 표를 뺀 매출 및 수주상황 본문은 판매 경로·결제 조건·판매 전략 설명이다. 공시일(`published_at`)과 보고 대상 사업연도(`period`, 예: `FY2025`)를 구분한다.

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
- `data/samples/ideas.json`의 SF-05와 시장 뉴스·DART 기업 연결은 지능형 공정제어 기준이다. 이전 SF-05(현장 작업자용 LLM 음성 어시스턴트)의 검색어는 `legacy_market_keywords`에 기록만 하며, 그 검색어로 수집한 기사는 정제 단계(`market_processor`)에서 제외한다. 시장 평가 라벨은 아직 이전 SF-05 기준이라 새 SF-05 시장 성능을 평가하려면 다시 라벨링해야 한다.

### 시장 근거 색인·검색

```bash
python -m src.retrieval.market_search build                                     # market_docs.jsonl·dart_docs.jsonl 색인
python -m src.retrieval.market_search search "협동로봇 도입 확대" --idea-id SF-01   # 질의 검색
```

- `data/market/processed/market_docs.jsonl`(뉴스)과 `dart_docs.jsonl`(DART)을 `text-embedding-3-small`로 임베딩해 `data/market/chroma/`의 `news` 컬렉션(cosine)에 저장한다. 출처는 `source_type`(`news`·`dart`)으로 구분한다. `OPENAI_API_KEY`가 필요하다.
- `search_by_dimensions`는 차원마다 뉴스 5건과 DART를 따로 검색해 합친다. DART는 먼저 기업을 최대 3곳 고르고 차원마다 그 기업에서 기업당 1건씩 가져온다. 기업은 관련성 판정 모델이 아이디어 항목과 기업별 주요 사업(`configs/dart_companies.yaml`의 `reason`)을 보고 같은 제품·공정 범주인 곳을 고르며(`choose_dart_companies`, `prompts/market_dart_companies.md`, 맞는 기업이 없으면 DART 없이 검색), 이 호출이 실패하면 아이디어 전체 문장과 가까운 기업을 쓴다(`route_dart_companies`). 보고서 검색 범위에 검색한 DART 기업을 표시한다. 통합 실행 준비 점검은 시장 색인에 DART가 없으면 사유를 표시한다.
- 같은 텍스트로 이미 색인된 문서는 다시 임베딩하지 않고 메타데이터만 갱신하며, `--rebuild`로 전체를 다시 임베딩한다.
- DART 청크를 다시 만들면 청크 수가 달라질 수 있다. `build --prune`은 색인이 끝난 뒤 정제 문서에 없는 ID를 지운다. 임베딩이 중간에 실패하면 기존 색인은 그대로 남는다.
- 에이전트 툴은 `search_market`(질의 1건)과 `search_by_dimensions`(수요·경쟁·가격·구매자·도입장벽 차원별 질의)이며, 같은 `dup_group` 결과는 1건만 반환한다.
- 차원별 질의는 목표 세그먼트·고객·문제·현재 대안·기술·차별점·수익모델을 해당 차원에 맞게 결합한다. 빈 항목은 질의에서 빠진다.

```bash
python -m src.retrieval.market_relevance --idea-id SF-01   # 차원별 검색 + 관련성 판정·충분성 상태
```

- `search_with_relevance`는 차원별 검색 결과마다 `gpt-4o-mini`로 관련 여부·이유를 판정하고(기준: `prompts/market_label_judge.md`), 관련 건수로 차원별 충분성 상태(`sufficient` 2건 이상 · `limited` 1건 · `insufficient` 0건 · `no_results` · `error`)를 붙여 반환한다. `OPENAI_API_KEY`가 필요하다.
- 검색 거리는 관련성을 구분하지 못해(평가 라벨 기준 AUC 0.52) 충분성 판단에 쓰지 않는다. 판정 모델 선택 근거는 [docs/market_research.md](docs/market_research.md#충분성-판정).

### 시장 조사 실행 (MarketReport)

```bash
python -m src.services.market_service --idea-id SF-01                                         # MarketReport JSON 출력
python -m src.services.market_service --idea-id SF-01 --out data/samples/market_reports/SF-01.json   # 파일로 저장
python -m src.services.market_service --idea-id SF-01 --idea-filter                           # 아이디어 연결 자료로 한정
python -m src.services.market_service --idea-id SF-01 --no-trend                              # 검색 관심도 흐름 생략
python -m src.services.market_service --idea-id SF-01 --no-network                            # 키워드 동시 출현 네트워크 생략
python -m src.services.market_service --idea-id SF-01 --no-financials                         # 검색한 DART 기업 재무 현황 생략
python -m src.services.market_service --idea-id SF-01 --no-procurement                        # 공공 조달 입찰공고 생략
python -m src.ingestion.procurement_client 협동로봇 202609                                     # 주제어 한 달 입찰공고 직접 조회
python -m src.ingestion.trend_client 예지보전 예측정비                                         # 주제어 검색 관심도 직접 조회
```

- `--idea-id`는 `data/samples/ideas.json`에서 아이디어를 고르는 데 쓴다. 기본 실행은 화면 통합 실행과 같이 전체 색인을 검색하며, `--idea-filter`를 주면 그 아이디어에 연결된 뉴스·DART 기업으로 좁힌다. 답변 평가(`evaluation.market_answer_eval`)는 아이디어 연결 자료로 한정해 실행한다.

- `run_market_research(MarketSearchRequest)`가 차원별 검색 → 관련성 판정 → 시장 분석 생성·인용 검증을 실행해 `MarketReport`(`src/schemas.py`)를 반환한다. 분석 규칙은 `prompts/market_analysis.md`, 생성·검증은 `src/generation/market_analysis.py`에서 관리한다. `OPENAI_API_KEY`가 필요하다.
- 사실 문장은 인용 근거(`evidence`의 `citation_id`)가 있어야 하고, 인용 기사·아이디어 입력에 없는 숫자가 있거나 수치에 기준 연도가 없으면 재생성(최대 2회)하거나 해당 문장을 제거한다. 판정은 차원별 충분성 상태와 근거 성격으로 제한하고(근거 1건이거나 사업 신호뿐이면 최대 '신호만 확인'), 기대는 아이디어 항목이 모름이면 미확인으로 둔다(가격 ← 수익모델, 구매자 ← 고객). 뉴스의 근거 성격(구매 신호·간접 수요·사업 신호 등)은 관련성 판정과 같은 호출에서 정하고, 차원마다 확인되지 않은 이유(`limitation`)를 붙인다. DART 사업보고서를 인용한 문장은 "기업 사업보고서(FY연도)에 따르면"처럼 공시 기업을 밝힌다.
- 검색 관심도 흐름(`MarketReport.search_trend`): 아이디어 5개 항목에서 LLM이 검색 주제어(대표 범주 + 같은 범주의 다른 이름, 최대 3개, `prompts/market_trend_terms.md`)를 고르고, 네이버 검색어 트렌드로 기준 주제어(스마트공장·스마트팩토리)와 함께 최근 24개월 월별 검색량을 조회한다(`src/ingestion/trend_client.py`, 설정 `configs/search_trend.yaml`). 월별 '주제어 ÷ 기준 × 100' 지수의 최근 6개월 평균을 직전 6개월과 비교해 ±10% 이상이면 상승·둔화, 그 사이는 유지로 표시하고, 평균 검색량이 적으면 판단하지 않는다(`src/services/market_trend.py`). 시장 화면에 월별 선 그래프로 나오며(`frontend/market_trend_view.py`), 차원별 판정에는 쓰지 않는다. 화면 통합 실행과 CLI에서만 붙고, 같은 요청은 그날 `data/market/trends/`에 캐시한다. `NAVER_TREND_CLIENT_ID`·`NAVER_TREND_CLIENT_SECRET`이 필요하다.
- 키워드 동시 출현 네트워크(`MarketReport.keyword_network`): 아이디어 전체 문장과 가까운 뉴스 100건의 제목·요약에서 `kiwipiepy`로 명사를 뽑고(붙어 쓴 명사는 합침), 전체 뉴스보다 이 아이디어 주변에서 두드러진 명사 30개(lift ≥ 1.5, 기사 수 × ln(lift) 순)를 같은 기사에 함께 나온 기사 수로 잇는다. `networkx`로 키워드 묶음(가중 모듈성)과 배치를 계산해 시장 화면에 연결망 그림과 묶음 목록으로 보여 준다(`src/services/market_network.py`, 설정 `configs/keyword_network.yaml`, 화면 `frontend/market_network_view.py`). LLM 없이 질의 임베딩 1회만 쓰며, 함께 나온 것은 같은 기사에서 다뤄졌다는 뜻이라 차원별 판정에는 쓰지 않는다. 화면 통합 실행과 CLI에서만 붙는다.
- 인접 기업 재무 현황(`MarketReport.company_financials`): 차원별 검색에서 고른 DART 기업(최대 3곳)의 기준일 직전 사업연도 사업보고서 주요 재무 계정(OpenDART `fnlttSinglAcnt`)을 조회해, 최근 3개 사업연도 매출액과 최근 연도의 전년 대비 매출 증감·영업이익·영업이익률·당기순이익·연구개발비·연구개발비 비율을 억원 단위 표로 보여 준다. 연구개발비는 같은 사업보고서 본문의 '연구개발활동' 표에서 정부보조금 차감 전 총액을 우선해 뽑고(`src/ingestion/dart_processor.py` `extract_rnd_expense`), 비율은 회사 공시 비율 대신 같은 해 매출액으로 나눠 계산한다. 표 위에는 기업마다 세로축을 따로 둔 3개 연도 매출액 막대 그래프를 두고, 막대 색으로 그 연도 영업이익 흑자·적자를 구분한다(`src/services/market_financials.py`, 화면 `frontend/market_financials_view.py`). 연결재무제표가 없으면 별도재무제표를 쓰고, 직전 사업연도 공시가 아직 없으면 그 전 연도를 쓴다. 조회 결과는 `data/market/raw/dart/financials/`에, 사업보고서 본문은 수집 원본과 같은 `data/market/raw/dart/{rcept_no}.xml`에 캐시한다. 기업 실적일 뿐 시장 규모·구매 수요의 근거가 아니어서 차원별 판정에는 쓰지 않는다. 화면 통합 실행과 CLI에서만 붙고 `DART_API_KEY`가 필요하다.
- 공공 조달 공고(`MarketReport.procurement`): 검색 관심도 주제어로 조달청 나라장터 입찰공고정보서비스(공공데이터포털)에서 기준일 직전 달까지 6개월의 물품·용역 공고를 달마다 조회한다(API 조회 기간이 약 1개월로 제한, `src/ingestion/procurement_client.py`, 설정 `configs/procurement.yaml`). 같은 공고의 이전 차수·재공고·취소공고를 빼고, 공고명에 주제어 글자만 들어간 다른 물건은 LLM이 공고명·세부품명으로 걸러 낸다(`prompts/market_procurement_relevance.md`, `src/services/market_procurement.py`). 시장 화면에 관련 공고 수·예산 중앙값·범위, 구매 주체 유형(민간 기업·대학·학교·연구기관·공공기관), 최근 공고 10건 목록을 보여 준다(`frontend/market_procurement_view.py`). 관련 공고는 분석 전에 조회해 집계 1건과 공고 최대 3건(민간 기업 공고 우선)을 가격·구매자 차원의 구매 신호 근거(`source_type: procurement`)로 넣고(`attach_procurement`), 사업 승인 분석의 구매자·예산 보유자·구매 절차·가격 가설을 '공공 부문(나라장터 공고 기준)'으로 채울 수 있게 한다. 공공기관·대학·연구기관의 구매가 대부분이라 민간 고객 수요의 근거가 아니므로 수요 차원에는 넣지 않고, 아이디어 고객이 공공 부문이 아니면 구매자 차원을 '확인됨'으로 올리지 않으며 공공 부문으로 채운 사업 승인 항목에 '목표 고객은 미확인'을 붙인다(`src/generation/market_analysis.py`). 근거 문장에 기준 연도가 없으면 공고 기간을 앞에 붙인다. 담당 공무원 이름·연락처는 저장하지 않고, 끝난 달의 결과는 `data/market/procurement/`에 캐시한다. 화면 통합 실행과 CLI에서만 붙고 `DATA_GO_KR_SERVICE_KEY`가 필요하다.
- `data/samples/market_reports/`에는 SF-01~SF-05를 기본 실행(화면과 같은 전체 색인 검색)으로 만든 결과 예시가 있다. 로컬 수집 뉴스·DART 기준이므로 다시 수집하면 내용이 달라진다.

```bash
python -m src.generation.market_markdown data/samples/market_reports/SF-01.json   # 종합 보고서용 마크다운 섹션 출력
```

- `market_report_to_markdown(report)`는 `MarketReport`를 종합 보고서의 '시장 조사 및 분석 결과' 섹션(차원별 판정 요약 표, 차원별 문장·검증 과제, 검색 관심도 흐름, 키워드 동시 출현 묶음, 인접 기업 재무 현황 표, 공공 조달 공고, 미확인 사항, 근거 목록)으로 바꾼다. LLM을 부르지 않으며, 인용은 UI와 같은 `M:{citation_id}`로 쓴다.
- 아이디어 입력·시장 조사 진입점의 입력·출력·오류 처리 약속은 [docs/api_contract.md](docs/api_contract.md)에 정리한다.

### 아이디어 구조화

```bash
python -m src.generation.idea_parser "중소 부품 공장에 협동로봇과 비전 카메라를 턴키로 설치해 준다"
```

- 아이디어 한 문장을 `gpt-4o-mini`로 문제(`problem`)·기술(`technology`)·고객(`customers`)·차별점(`difference`)·수익모델(`revenue`)로 나눈다. 규칙은 `prompts/idea_parser.md`에서 관리하며, 문장에 없는 항목은 추측하지 않고 비워 둔다. `OPENAI_API_KEY`가 필요하다.
- 빈 항목은 사용자에게 최대 2회 재질문한다. 사용자는 빠진 항목을 미확인으로 두고 진행할 수 있다. 항목 출처(`extracted`·`user_answer`·`ai_hypothesis`·`unknown`)를 함께 남기며 AI 가치 가설은 입력 사실과 분리한다.
- 완성된 결과(`IdeaDraft`)는 `build_requests`로 특허·시장 공통 입력(`StructuredIdea`)과 검색 요청(`PatentSearchRequest`·`MarketSearchRequest`)으로 변환한다.
- Streamlit에서는 `아이디어 구조화·전체 보고서 시작`으로 구조화·재질문을 시작하고, SF-02/SF-05 특허 색인을 선택할 수 있다. 입력은 1,000자까지다. 초안이 완성되면 특허 보고서 → 시장성 보고서 → 최종 사업 검토 순서로 화면과 결과가 자동 진행한다.
- 사용자는 초안을 확인·수정하고 미확인 항목을 남긴 채 진행할 수 있다. 초안 출처는 `extracted`·`user_answer`·`ai_hypothesis`·`unknown`으로 기록한다.
- UI는 `아이디어 입력·초안 확인 → 특허 비교 보고서 → 시장성 보고서 → 최종 실행 검토`의 네 단계다. 전체 분석 시작 한 번으로 초안이 완성되면 특허·시장·최종 보고서를 차례로 보여준다. 특허 보고서는 최종 비교 문헌 5~8건을 목표로 하며 비교 궤도·주의점·개선 제안으로 정리한다. 시장 보고서는 직접 수요 근거와 산업 신호의 구분·다음 검증 계획을 제공한다. 종합 화면은 양쪽의 완료된 근거가 연결된 결론과 다음 확인사항을 우선 표시하고, 부족한 근거만으로 결론을 만들지 않는다.
- 최종 권고는 사업 성공 예측이나 특허 법률 판단이 아니다. 기사·기업 자료만으로 고객 구매 의사를 확인하지 않으며, 검색 결과가 없는 경우 특허 비유사나 시장 수요 부재로 단정하지 않는다.
- `src.pipeline.run_pipeline`의 입력·출력 및 보류 규칙은 [docs/api_contract.md](docs/api_contract.md#3-특허-조사-및-통합-파이프라인)에 명시한다. 종합 보고서는 양쪽 조사 상태가 완료이고 특허·시장 근거 ID가 함께 연결된 판단만 결론으로 제시한다. 화면 안내는 [docs/ui-guide.md](docs/ui-guide.md)를 참고한다.
- 종합 보고서에는 두 조사 결과를 아이디어 관점으로 정리한 예비 SWOT(강점·약점·기회·위협)이 붙는다(`src/generation/swot.py`, `prompts/idea_swot.md`, 화면 `frontend/swot_view.py`). gpt-4o-mini 1회로 사분면마다 최대 3개를 고르고, 코드가 항목마다 근거 ID(`M:`·`P:`·검색 관심도 `T`·기업 재무 현황 `F`)·숫자·과장 표현·검색 관심도 방향·빈 아이디어 항목 여부를 검증해 맞지 않는 항목을 버린다. 근거 ID가 없는 항목은 사용자 주장 또는 검증 전 가설로 표시한다.
- SWOT 뒤에는 예비 비즈니스 모델 캔버스(9개 블록)가 붙는다(`src/generation/business_canvas.py`, `prompts/business_canvas.md`, 화면 `frontend/canvas_view.py`). 아이디어 항목·핵심 구성요소·두 조사 결과·구축 비용 추정으로 gpt-4o-mini 1회에 블록마다 최대 3개(짧은 제목과 설명 한 문장)를 채우고 SWOT과 같은 규칙으로 검증한다. 아이디어에 없는 블록(채널·고객 관계·핵심 파트너 등)은 '가설'로 표시한 제안으로 채운다.

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
| `NAVER_TREND_CLIENT_ID` · `NAVER_TREND_CLIENT_SECRET` | 검색어 트렌드(Search Trend) API를 활성화한 NAVER API HUB Application의 Client ID·Secret. 없으면 시장 보고서의 검색 관심도 흐름만 오류로 표시된다 |
| `DATA_GO_KR_SERVICE_KEY` | 공공데이터포털 일반 인증키(Decoding 값). '조달청_나라장터 입찰공고정보서비스' 활용신청이 필요하다. 없으면 시장 보고서의 공공 조달 공고만 오류로 표시된다 |
| `IDEALENS_MARKET_TIMEOUT` · `IDEALENS_PATENT_TIMEOUT` | (선택) 통합 분석의 영역별 제한 시간(초). 기본 120·180 |
| `IDEALENS_PATENT_RETRIEVAL_MODE` | (선택) 특허 서비스 검색 방식: `dense`(기본), `bm25`, `hybrid` |
| `IDEALENS_PATENT_RERANKER` | (선택) `none`(기본) 또는 `bge-cross-encoder`. 후자는 `sentence-transformers`와 모델 다운로드가 필요 |
| `IDEALENS_SERIAL` | (선택) `1`이면 시장·특허 조사를 순차 실행 |
| `IDEALENS_APP_PASSWORD` | (호스팅 배포) 접속 비밀번호. 비어 있으면 비밀번호 화면을 띄우지 않는다(로컬 실행) |
| `CHROMA_HOST`·`CHROMA_PORT`·`CHROMA_SSL`·`CHROMA_API_KEY` | (선택) 팀 공용 Chroma 접속. 비우면 로컬 Chroma. HTTPS 키 접속은 `443`·`true` |

PR 분석 자동화용 `CODEX_AUTH_JSON`(ChatGPT 구독 로그인, `make review-codex-login`으로 등록)·`CODEX_AUTH_WRITE_TOKEN`·`NOTION_REVIEW_TOKEN`은 `.env`가 아니라 develop에서만 열리는 GitHub Environment `pr-analysis`에 저장한다([docs/development.md](docs/development.md#pr-자동-분석-githubworkflowspr-analysisyml)).

## 개발 도구와 협업 자동화

- **코드 포맷**: Python 코드는 [black](https://black.readthedocs.io/)으로 통일한다. 버전은 `requirements-dev.txt`에 고정하고, `pyproject.toml`의 `required-version`으로 다른 주 버전 실행을 막는다.
- **커밋 전 검사**: `pre-commit install` 후 커밋마다 black, 병합 충돌 표시, 개인키 노출, 대용량 파일, 줄끝 공백을 검사한다.
- **CI**: develop·main 대상 PR과 push에서 black 검사, pytest, 자동화 스크립트 테스트, Docker 이미지 빌드, SCC와 같은 Debian 11 환경의 SCC 전용 의존성 검사를 실행한다.
- **main 승격 PR**: develop push의 CI가 성공하면 develop → main 배포 승격 PR을 열거나 갱신하고 리뷰어 1명을 요청한다. 병합(= SCC 배포)은 사람이 승인하며 Create a merge commit만 쓴다([배포 안내](docs/deploy-streamlit-cloud.md)).
- **SCC 배포 스모크**: main push와 수동 실행 때 브라우저로 SCC 앱을 열어 비밀번호 화면과 버전(방금 커밋)을 확인한다. 앱 주소는 저장소 변수 `SCC_APP_URL`에 둔다.
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
- 시연은 Streamlit UI로 하며 Streamlit Community Cloud(`main` 병합 시 자동 배포, 앱 비밀번호, [배포 안내](docs/deploy-streamlit-cloud.md)) 또는 로컬 Docker로 실행한다. 팀 색인은 공용 Chroma, 로컬 Chroma(`data/patents/chroma/`·`data/market/chroma/`)는 개인 실험·테스트용이다.
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
python -m evaluation.market_answer_eval run             # LLM 단독·단순 RAG·IdeaLens 시장 분석 문장 단위 비교 (SF-01~04, API 비용 발생)
python -m evaluation.market_answer_eval sample          # 판정기 결과를 숨긴 사람 검토 표본 → evaluation/labels/
python -m evaluation.market_answer_eval agreement       # 사람 검토 vs 문장 판정기 일치율·kappa, 사람 보정 Citation Accuracy
python -m evaluation.patent_labeling export              # SF-02/SF-05 특허 후보 CSV 내보내기 (사람 라벨 필요)
```

- 시장 평가에는 사람 라벨 25문항이 있으나 SF-05 라벨은 이전 '현장 작업자용 LLM 음성 어시스턴트' 기준이다. 현재 SF-05(지능형 공정제어)와 맞지 않으므로 최신 비교는 `--idea-ids SF-01,SF-02,SF-03,SF-04`로 20문항을 실행하고, SF-05는 새 수집·라벨 이후 포함한다.
- 특허 평가셋은 SF-02·SF-05의 기술 요소 질의로 구성한다. 후보 CSV는 검색 방식과 순위를 숨겨 사람 라벨 편향을 줄이고, 원문 URL이 없으면 출원번호로 KIPRIS 검색 링크를 만든다. 판정 기준은 [특허 평가 라벨링 가이드](evaluation/patent_labeling.md)를 따르며, 사람 정답을 import한 뒤에만 검색 지표를 계산한다.
- 특허 검색 결과 CSV에는 검색 방식·모델·커밋·작업 트리 상태, 평가 데이터와 색인 지문, Top-K·후보 수·RRF 설정이 기록된다. LLM 단독/RAG 답변 비교는 `answer_eval`의 LLM 판정 점수이며 사람 정답 평가와 구분해야 한다.
- `market_answer_eval`은 실제 시장 조사 결과(`run_market_research`)를 LLM 단독·단순 RAG(검색 상위 5건 그대로)와 같은 문항으로 비교한다. 인용된 fact 문장마다 `prompts/market_claim_judge.md` 판정기가 인용 기사 제목·요약과 대조하고(Citation Accuracy), 사람 검토 표본으로 판정기 결과를 보정한다. 인용 기사의 관련성은 사람 정답 라벨로 센다. 결과와 해석은 [docs/market_research.md](docs/market_research.md#시장-답변-평가).
- 라벨링 후보는 문항마다 벡터 검색 상위 8건과 그 아래 순위에서 차원 표현(가격·비용, 도입·사례 등)이 들어간 4건, 그리고 `extend`로 추가한 bm25·hybrid 상위 5건 중 새 문서다. 방식 비교 결과는 [docs/market_research.md](docs/market_research.md#시장-검색-방식-비교). 라벨 기준과 LLM 초안·사람 검토 절차는 [evaluation/market_labeling.md](evaluation/market_labeling.md).
- 관련 문서가 없는 문항은 평균에서 빼고 따로 센다. 라벨 후보에 없던 문서가 상위 5건에 나오면 `unjudged`로 표시한다.
- 시장 조사의 Baseline·실험·결정과 오류 개선 기록은 [docs/experiments.md](docs/experiments.md)에 모은다.
- 관련성 판정 평가는 사람이 직접 라벨한 행(`label_source=human`)만 비교해 정확도·정밀도·재현율·kappa를 계산하고, 사람 라벨만 있는 문항의 충분성 상태 일치를 함께 출력한다.
- 정답 `source_id`는 로컬에 수집한 뉴스 기준이므로, 다시 수집하면 문서가 달라질 수 있다.
- `--mode`는 `dense`(기본, 기존 Chroma 검색), `bm25`, `hybrid`(RRF 결합) 중 선택한다. 검색 함수 기본 동작은 dense로 유지한다.
- `--rerank`는 `pip install sentence-transformers` 후 `BAAI/bge-reranker-v2-m3` Cross-Encoder를 적용한다. 모델 파일은 최초 실행 때 내려받으며, 기본 실행 의존성에는 포함하지 않는다.
- 평가는 문항별 Hit/Recall/Precision/MRR/nDCG와 검색 지연시간을 CSV로 저장한다. OpenAI 비용은 토큰 사용량 정보가 제공되지 않는 현 검색 인터페이스에서 계산하지 않는다.
- 라벨이 완료된 시장 25문항은 평가 대상이다. 특허 평가 질의 5개는 준비되어 있지만 사람 관련도 라벨과 로컬 특허 색인이 준비되기 전까지 특허 품질 수치는 만들지 않는다.

### 특허 검색 평가

- 라벨 검토 전 데이터 준비 상태는 `python -m evaluation.patent_preflight`로 확인한다. 이 명령은 API를 호출하지 않고 질의·후보 수, 케이스별 후보 분포, 중복·누락 링크, 라벨 진행 상태와 두 입력 파일의 SHA-256을 출력한다. JSON 출력은 `--json`을 사용한다.
- 검토 편의를 위해 로컬 처리 특허의 초록·전체 청구항·서지 정보와 후보 행의 일치 여부를 묶으려면 `python -m evaluation.patent_review_context`를 실행한다. 결과는 Git 제외 경로 `data/patents/processed/patent_eval_review_context.jsonl`에 생성되며 KIPRIS·OpenAI API를 호출하지 않는다. 관련도 라벨은 자동 판정하지 않는다.
- 오프라인 파이프라인 점검용 합성 데이터는 `evaluation/fixtures/patent_retrieval_synthetic_v1.json`에 있다. `python -m evaluation.patent_fixture`로 문헌·질의·관련도 참조 무결성과 데이터 SHA-256을 확인한다. 가상 데이터이므로 실제 특허 검색 성능 평가나 제품 성능 주장의 근거로 사용하지 않는다.
- `evaluation/patent_cases.json`은 샘플 아이디어에서 고정한 5개 특허 검색 질의로 시작하며, 정답 문헌 라벨은 비어 있다.
- 특허 원문을 수집·색인한 뒤 `python -m evaluation.patent_labeling export`로 Dense·BM25·Hybrid 상위 후보를 같은 CSV에 모은다. 선택적으로 `--reranker bi-encoder` 또는 `--reranker cross-encoder`를 주면 각 Hybrid 재정렬 후보도 포함한다.
- 후보 CSV에서 사람 검토를 끝낸 문헌은 `relevant`를 `1`(관련) 또는 `0`(비관련), `review_status=reviewed`, `label_source=human`으로 기록한다. 판정이 어려운 문헌은 `review_status=hold`로 남기며, AI 초안은 `label_source=ai_draft`로 표시해 사람 정답으로 집계하지 않는다. 모든 후보가 사람 검토 완료된 문항만 평가에 포함한다.
- 실제 `PatentReport` JSON의 구성요소 주장과 연결된 원문 인용을 검토하려면 `python -m evaluation.patent_groundedness export <report.json>`으로 사람 검토 CSV를 만들고, 라벨 입력 후 `python -m evaluation.patent_groundedness score <labels.csv>`로 분포·파일 지문을 저장한다. 라벨 기준은 [특허 주장 근거 지지 검토 가이드](evaluation/patent_groundedness.md)를 따른다.
- 동일한 문헌 단위 정답셋으로 `python -m evaluation.evaluate patent --mode dense --label baseline`, `--mode bm25`, `--mode hybrid`, `--mode hybrid --reranker bi-encoder`, `--mode hybrid --reranker cross-encoder --candidate-k 40`을 실행해 Hit@5·Recall@5·Precision@5·MRR·nDCG@5와 후보 풀 Recall@candidate-k, 검색·리랭킹 지연시간을 비교한다. 후보 풀 재현율의 분모는 해당 케이스에서 사람 검토된 관련 문헌이며, 라벨 후보에 포함되지 않은 전체 코퍼스 관련 문헌까지 의미하지 않는다. 결과 CSV는 `evaluation/results/`에 저장한다. `--candidate-k` 비교 시 다른 조건은 고정하고, 새 Top-5 문헌이 미판정이면 먼저 추가 라벨링한다.
- 검색 결과에서 나온 적 없는 문헌이 top-K에 나타나면 `unjudged`로 따로 세므로 라벨 후보를 추가 검토한다. 평가 문항이 라벨되기 전에는 성능 수치를 보고하지 않는다.
- Dense·Hybrid 검색과 Bi-Encoder 재정렬은 `OPENAI_API_KEY`가 필요하며 후보 문헌을 매 질의 다시 임베딩한다. 평가 도구는 임베딩 비용을 자동 계산하지 않는다. Cross-Encoder는 `sentence-transformers`와 모델 파일을 별도로 설치해야 한다.

### 지능형 공정제어 분야 검색 비교

```bash
python -m evaluation.patent_domain_experiment run   # SF-05 질문을 SF-05·SF-02 로컬 색인에서 검색
python -m evaluation.patent_domain_experiment score # 후보 사람 라벨 완료 후 지표 계산
python -m evaluation.patent_index_effect --rebuild-cache # SF-05 사전색인과 매 요청 임베딩 시간 비교
python -m evaluation.patent_candidate_budget run --limit 150 # 확장 코퍼스에서 고정 배치 후보 수 비교
python -m evaluation.patent_candidate_budget run --resume # 저장된 코퍼스·색인 재사용 후 비교 재개
python -m evaluation.patent_candidate_budget score # 후보 사람 라벨 완료 후 후보 제한별 품질 비교
```

- 비교 스크립트는 `data/patents/chroma/`의 로컬 `patents` 컬렉션을 직접 열어 공용 Chroma 설정과 분리한다. 기존 로컬 색인의 SF-05(지능형 공정제어)와 비교 분야 SF-02(AI 비전 품질검사) 임베딩을 분야별 필터로 검색한다. 새 특허를 추가할 때는 수집·정제 및 기존 특허 색인 구축 절차를 따른다.
- SF-05 평가 질의와 동일한 Top-20 후보 풀에서 Dense·BM25·Hybrid를 비교한다. 검색 순위가 포함된 `rankings.csv`와 순위·방식을 감춘 `candidates.csv`는 Git 제외 경로 `data/patents/processed/domain_experiment/`에 생성된다. 재실행할 때 같은 문헌의 기존 라벨과 검토 메모를 보존한다. 각 후보는 `relevant=0/1`, `review_status=reviewed`, `label_source=human`으로 표시하고, 애매한 후보는 `hold`로 남긴 뒤 `score`를 실행한다.
- Hit@5·Recall@5·Precision@5·MRR@5·nDCG@5와 실제 후보 풀 Recall을 사람 검토된 후보만으로 계산한다. Recall의 분모는 방식별 결과 합집합에서 판정한 관련 문헌이므로 전체 특허 코퍼스 기준 재현율이 아니다. 평가 문항과 특허 표본이 작으므로 결과는 해당 색인·질의의 예비 비교로 해석한다. Dense·Hybrid 검색은 질의 임베딩에 `OPENAI_API_KEY`가 필요하다.
- `patent_index_effect`는 SF-05 특허 청크를 실험 전용 로컬 Chroma에 한 번 색인한 경로와, 질의마다 문서 전체를 다시 임베딩하는 경로의 임베딩 입력 수·API 요청 수·시간·Top-5 순위 일치도를 비교한다. 전자는 색인 구축 시간을 별도로 기록하고, 실측 질의 시간 절감으로 단순 손익분기 질의 수를 계산한다. 결과는 Git 제외 경로 `data/patents/processed/domain_experiment/index_effect.json`에 저장된다. 비교 실행은 특허 본문을 임베딩 API로 보낸다. 단일 실행 시간은 네트워크 변동을 포함하며, 검색 품질 지표는 사람 라벨을 완료한 뒤 해석한다.
- `patent_candidate_budget`은 SF-05 설정 검색어당 KIPRIS 최대 150건을 수집해 별도 로컬 색인을 만든다. 질의마다 임베딩 API 입력을 최대 100개로 제한한 비교에서 무색인 경로는 BM25 상위 99개 후보와 질의를 함께 임베딩하고, 사전색인 경로는 미리 저장한 전체 특허 벡터를 검색한다. 따라서 이 실험은 고정된 쿼리 임베딩 예산에서 전체 벡터 후보를 검색할 때의 효과를 평가한다. 전체 코퍼스를 매 질의 임베딩할 수 있는 무색인 방식과 비교하면 후보 수와 의미 순위는 원칙적으로 같아야 하며, 사전색인 자체가 검색 품질을 자동으로 높인다고 해석하지 않는다. 각 방식의 Top-20 합집합만 블라인드 후보 CSV에 담아 관련도를 판정한 뒤 Hit@5·Precision@5·MRR@5·nDCG@5와 판정 후보 풀 기준 Recall@5를 계산한다. 판정 후보 풀 밖의 문헌 수는 미판정으로 별도 기록한다. CSV `note`가 `AI 초안`으로 시작하면 제목·초록을 이용한 자동 판정으로 간주하며, 지표 파일과 결과 JSON에도 해당 라벨 출처를 남긴다. AI 초안은 사람 판정을 대체하지 않는다. 특허 원문·색인·결과는 Git 제외 `data/patents/processed/domain_experiment/candidate_budget/`에 보관한다. 수집·임베딩은 각각 KIPRIS·OpenAI API를 사용하고 공유 Chroma에는 쓰지 않는다. 중단 후에는 `--resume`으로 저장된 코퍼스와 동일한 로컬 색인을 확인해 재사용한다.

### 특허 청킹·문헌 집계·리랭킹 실험

```bash
python -m evaluation.patent_chunk_rerank_experiment inventory
python -m evaluation.patent_chunk_rerank_experiment run
python -m evaluation.patent_chunk_rerank_experiment run --with-cross-encoder  # 선택 의존성·모델 사용
python -m evaluation.patent_chunk_rerank_experiment score  # 사람 라벨 작성 후 실행
```

- 실험은 정제된 `data/patents/processed/patent_docs.jsonl`과 5개 평가 질의로 SF-05 지능형 공정제어 및 SF-02 AI 비전 품질검사를 비교한다. 인벤토리는 코퍼스 fingerprint, 분야별 초록·청구항 수, 로컬 Chroma snapshot fingerprint와 기존 246개 청크 내용의 일치 여부를 기록한다.
- BM25 기준에서 `baseline_max`, 독립항 중심, 상위항 문맥 결합, 상위 3개 청크 평균, 초록·독립항·종속항 가중 집계를 비교한다. 가중치는 실험 상수이며 최적값으로 학습된 값이 아니다. 특허 버전 중복이 발견되면 문헌 단위로 잘못 합치지 않도록 실험을 중단한다.
- Cross-Encoder는 `--with-cross-encoder`를 명시한 경우에만 실행한다. `sentence-transformers` 및 BGE 모델 사용이 가능하면 같은 질의·분야의 baseline Top-K 후보를 고정하고 제목+초록+독립항 입력과 청구항 전용 입력을 비교한다. 모델 로드·검색·리랭킹 시간을 분리한다. 기본 서비스 검색 설정은 바뀌지 않는다.
- 순위와 실험 방식은 `rankings.csv`에, 원문·청구항·KIPRIS 링크가 포함된 방식 비공개 검토 후보는 `candidates.csv`에 기록한다. 두 파일, 인벤토리, 지표는 Git 제외 경로 `data/patents/processed/chunk_rerank_experiment/`에 저장되고 재실행해도 같은 후보의 사람 라벨과 메모를 보존한다. 라벨은 원문과 청구항을 확인해 `relevant=0/1`, `review_status=reviewed`, `label_source=human`으로 작성한다. 판단 보류는 `review_status=hold`로 남긴다.
- `score`는 각 질의·분야 후보 풀 전체가 사람에 의해 판정된 경우에만 지표를 계산한다. Candidate Recall@K의 분모는 해당 실험 후보 풀의 사람 검토 관련 문헌이며 전체 특허 모집단 재현율이 아니다. 무관련 후보만 나온 질의는 별도 집계하고 macro 지표에서 제외한다. 미판정·보류·AI 초안은 정답이 아니다.
- 현재 로컬 분야별 문헌 수는 14건이고 후보 K 기본값은 20이므로 후보 단계가 코퍼스를 줄이지 않는다. Cross-Encoder 의존성이나 사람 라벨을 사용할 수 없으면 비교·품질 지표가 제한되며, 이 실험만으로 품질 개선을 주장하지 않는다. 자세한 라벨 기준은 [특허 평가 라벨링 가이드](evaluation/patent_labeling.md)를 참고한다.

### 특허 질의·필드 순위 결합 실험

```bash
python -m evaluation.patent_fusion_experiment run
```

- 동일한 5개 질의·분야별 로컬 코퍼스에서 기준 BM25와 질의 표현 순위 RRF, 초록·독립항·종속항 순위 RRF, 필드별 가중 RRF를 비교한다. 기본 가중치는 실험 가설이며 학습되거나 운영 검색에 적용된 값이 아니다.
- 결과 순위와 지표는 Git 제외 경로 `data/patents/processed/query_fusion_experiment/`에 기록한다. 기존 청킹 실험 후보 CSV의 출처별 라벨을 사용하며 AI 초안 지표는 탐색용으로만 표시한다. 사람 라벨 지표는 해당 질의·분야 후보 풀 전체가 `review_status=reviewed`, `label_source=human`으로 판정된 경우에만 별도로 계산한다.
- 현재 코퍼스는 분야별 14건이고 후보 풀이 코퍼스 전체를 포함하므로 Recall@20은 후보 생성 개선을 판별하지 못한다. 사람 검토 라벨과 더 넓은 후보 풀을 확보하기 전에는 운영 검색 품질 개선으로 해석하지 않는다. 분류코드가 현재 정제 데이터에 없으면 IPC/CPC 보조 점수는 비교하지 않는다.

### 특허 청구항 분석

특허 분석 입력은 `PatentSearchRequest`, 반환 계약은 `PatentReport`이며 `src.services.patent_service.analyze_patents()`에서 호출한다. 기본적으로 관련 특허 문헌을 최대 8건까지 비교하고 화면에도 선택된 8건을 표시한다. 문헌별 청구항 원문·버전·번호·종속항 참조와 UTC 수집 시각을 인용 근거 및 색인에 보존한다. 보고서는 색인 IPC 분류·출원연도·주요 출원인 통계와 넓은 검색 후보의 관련 기술 분포를 제공하며, 최종 통합보고서에는 특허 예비 신호와 시장 근거 상태를 교차 요약한다. 통계는 보유 색인 메타데이터 범위에 한정된다. 비교 문맥은 상위항 관계와 문헌당 약 1,800 토큰, 보고서 분석 전체 약 6,000 토큰의 보수적 추정 예산을 고려해 구성한다. 원문 확보 후 비교 생성만 실패하면 `partial` 상태로 원문과 오류를 보존하며, KIPRIS 청구항 조회가 비거나 실패하면 초록 근거와 미확인 상태를 반환한다. 구현 흐름과 통계 한계는 [docs/patent_rag.md](docs/patent_rag.md)를 참고한다.

특허 비교 뒤에는 `PatentDesignAnalysis`가 사용자 기술 구성요소와 기존 문헌별 비교 결과를 받아 최대 3개의 구체적 설계 대안을 생성한다. 각 대안에는 변경 대상, 구현 접근, 기술적 차이, 장점·제약, 정성적 실현 가능성, 검증 계획과 확인 가능한 인용 ID가 포함된다. 청구항을 확보하지 못하면 초록 기반으로 제한됨을 표시하며, 제안 생성이 실패해도 검색 근거와 기존 비교 결과는 보존한다. 결과는 기술 검토용이며 특허 침해·등록 가능성·실시 자유의 법률 판단을 제공하지 않는다. 상세 계약과 테스트 안내는 [docs/patent_rag.md](docs/patent_rag.md)를 참고한다.

## 통합 분석 화면

서비스 소개 안의 ‘서비스 개요 / 특허 조사 흐름 / 시장 조사 흐름’에서 분석 방식을 확인한다. 개요의 두 조사 카드도 해당 안내로 연결된다. 각 흐름은 자료 사전 준비와 실제 요청을 구분하며, 선택한 단계의 입력·처리·출력·사용 이유와 구현 근거를 보여준다(`frontend/process_guide.py`). 안내에서는 조사·API·평가를 실행하지 않고 운영 자료 수나 성능 점수를 추정하지 않는다. 홈 연출 및 분석 파이프라인은 변경하지 않는다.

‘왜 IdeaLens인가’의 ‘화면 예시·검증’은 특허·시장·종합 결과를 읽는 방법과 실험 자료를 안내한다(`frontend/showcase.py`). 초기 화면 구성 도식은 실제 조사 결과가 아니며, 확정 실험 캡처가 없는 항목은 준비 중으로 표시한다. 이미지·설명·분석 조건은 `frontend/assets/showcase/manifest.json`에서 교체한다. 교체 방법은 같은 폴더의 README를 따른다. 실제 결과와 실험 비교를 생성하거나 운영 보고서에 자동 첨부하지 않는다.

상단 ‘2 특허·시장 검토’는 특허와 시장 화면 모두에서 현재 단계로 강조하며, 하위 탭과 바로가기 바는 실제로 열려 있는 영역만 강조한다.

시장 검토는 근거 성격을 구매 신호·간접 수요·기업 주장 등으로 구분하고, 차원별 자료 상태·관련 검색 자료 수·확인되지 않은 이유·다음 검증 과제를 표시한다. 동일한 확인 범위를 최종 원문·PDF·기록에도 포함한다. 관련 검색 자료 수와 인용 건수는 구분하며, 미제공 값은 0으로 채우지 않는다. 기존 기록에 새 항목이 없으면 미제공으로 표시한다.

특허 분류 시각화·상세 팝업, 시장 사업 검토, 사용자 초안 확정 흐름을 3단계 화면에 연결한다. 비용·메모 탭에서 LLM 비용 가설을 견적과 구분해 편집하고 동일한 결과를 원문·PDF·기록에 반영한다. 비용 분석에는 추가 모델 호출이 발생한다. 분야 기본값은 자동이며 자료가 없는 선택 분야는 전체 색인으로 보완한다.

분석 중에도 홈·서비스 소개·차별점·내 기록으로 이동할 수 있다. 다른 화면에서도 진행 상태를 갱신하며, 완료 결과는 조사 화면으로 돌아가 확인한다. 진행 중 홈의 돋보기를 눌러도 새 분석을 시작하거나 기존 단계를 초기화하지 않는다. 새로고침·탭 닫기·서버 재시작 뒤 실행 중 작업 복구는 보장하지 않는다.

시장 보고서는 기존 분석에서 인용된 사실 최대 3개와 다음 검증 과제를 먼저 제시하고, 그래프·상세 분석은 펼쳐 확인한다(`frontend/report_reading.py`). 요약은 추가 모델 호출이나 새 사업성 판단을 만들지 않는다. 최종 보고서 표시 전 세션 결과를 현재 PipelineReport 계약으로 다시 검증해 새 선택 항목의 기본값을 채우며, 복원할 수 없는 예전 결과는 재분석 안내를 표시한다.

내 기록에서는 보관한 보고서를 선택한 뒤 PDF 준비·다운로드를 사용할 수 있다. PDF는 읽기·공유용이며 앱의 기록 복원에는 JSON을 사용한다. PDF는 기존 보고서 원문과 저장된 메모로 생성하며 새 분석을 실행하지 않는다.

종합 보고서 요약은 모든 인용 ID가 실제 발췌 원문에 연결된 판단만 사용하며, 미확인 항목은 별도로 유지한다. 연결이 빠진 판단은 제외하고 이를 안내한다. 분석 당시 보고서 원문은 별도 탭에 보존하며 검증된 요약과 구분한다. 요약 탭의 ‘판단 근거와 원문 인용 따라가기’에서 판단·아이디어에 대한 의미·원문을 함께 확인한다. 인용 연결 확인은 문장의 의미적 정확성까지 보장하지 않는다.


종합 보고서의 ‘판단 근거 따라보기’는 기존 최종 판단에서 연결된 특허·시장 인용을 선택해 원문 발췌와 출처를 확인하는 화면이다. 실제 판단을 먼저 보여주고 기준 설명은 펼쳐 확인한다. 새로운 모델 호출·점수·결론을 만들지 않으며, 원문이 누락된 인용은 미제공으로 표시한다. `frontend/decision_trace.py`가 이 화면과 기록용 계약을 관리한다.

내 기록은 세션별로 분리하며 공용 DB에 저장하지 않는다. ‘내 기록’의 ‘이 브라우저에 저장’을 직접 누르면 최대 20개·5MB의 기록을 현재 사이트의 브라우저 localStorage에 보관한다(`frontend/browser_records.py`). 다시 방문한 뒤 ‘저장한 기록 불러오기’로 복원할 수 있고, 브라우저 보관분과 현재 세션 기록을 각각 지울 수 있다. 복원 내용은 표시를 위해 현재 앱 세션으로 전달된다. 다른 기기·브라우저·사이트 주소와 동기화되지 않으며 공용 브라우저 프로필 사용자와는 공유될 수 있으므로 공용 기기에서는 파일 보관 또는 삭제를 권한다. API 키·환경변수는 저장 대상이 아니다. JSON 백업도 계속 지원한다.

상단 서비스 소개·차별점·내 기록과 3단계 메뉴를 제공한다. 같은 탭에서 새로고침한 뒤에는 ‘이전 분석 이어보기’로 서버에 남은 작업을 다시 연결할 수 있다. sessionStorage에는 무작위 작업 번호만 남기며, 입력·결과는 서버 메모리에 유지한다. 다른 탭·기기나 서버 재시작 후에는 복구되지 않으며 공용 실행 잠금을 강제로 해제하지 않는다.
