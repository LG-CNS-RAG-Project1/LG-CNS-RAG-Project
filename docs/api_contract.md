# 서비스 연결 계약

파이프라인(`src/pipeline.py`)과 Streamlit UI가 각 파트의 진입점을 부를 때의 입력·출력·오류 처리 약속이다.
데이터 형식은 모두 `src/schemas.py`의 Pydantic 모델이며, JSON으로 주고받을 때는 `model_dump_json()`·`model_validate_json()`을 쓴다.
특허 파트와 통합 흐름의 계약은 각 담당이 이 문서에 추가한다.

## 1. 아이디어 입력

| 함수 | 입력 | 출력 |
|---|---|---|
| `src.generation.idea_parser.parse_idea(text)` | 아이디어 문장 (str) | `IdeaDraft` |
| `src.generation.idea_parser.apply_answers(draft, answers)` | `IdeaDraft`, `{항목: 답변}` (항목: `problem`·`technology`·`customers`·`difference`·`revenue`) | `IdeaDraft` |
| `src.generation.idea_parser.confirm_unknowns(draft)` | 거절되지 않은 `IdeaDraft` | 빈 재질문 항목을 `unknown`으로 확정한 `IdeaDraft` |
| `src.generation.idea_parser.build_requests(draft)` | `status="complete"`인 `IdeaDraft` | `(PatentSearchRequest, MarketSearchRequest)` |

`IdeaDraft.status`로 다음 단계를 정한다.

| status | 의미 | 다음 단계 |
|---|---|---|
| `rejected` | 주제 이탈(`input_status="off_topic"`) 또는 프롬프트 조작·유해 목적(`"unsafe"`) | `rejection_reason`을 사용자에게 보여 주고 종료. 특허·시장 검색을 부르지 않는다 |
| `needs_input` | 빈 항목이 있음 (재질문 최대 2회) | `questions`(`{항목: 질문}`)를 보여 주고 답변으로 `apply_answers` |
| `complete` | 5개 항목 확정 (끝까지 비어 있으면 `field_sources`가 `unknown`) | `build_requests`로 특허·시장 검색 요청 생성 |

- 초안은 기술 구성요소·현재 대안·목표 세그먼트·가치 가설을 포함한다. 가치는 `ai_hypothesis`로 표시해 입력 사실과 분리한다.
- LLM 호출은 `parse_idea`의 1회뿐이다. `apply_answers`와 `confirm_unknowns`는 LLM을 부르지 않는다. 사용자는 미확인 항목을 확정하고 진행할 수 있다.
- 예외: 빈 문장은 `parse_idea`가 `ValueError`, `OPENAI_API_KEY`가 없으면 `RuntimeError`, OpenAI API 오류는 그대로 올라온다. `rejected` 초안에 `apply_answers`를 부르거나 미완성 초안에 `build_requests`를 부르면 `ValueError`다.
- JSON Schema: `IdeaDraft.model_json_schema()`

## 2. 시장 조사

| 함수 | 입력 | 출력 |
|---|---|---|
| `src.services.market_service.run_market_research(request, idea_id=None, trend_fn=None, network_fn=None)` | `MarketSearchRequest` (`build_requests`의 두 번째 값) | `MarketReport` |
| `src.generation.market_markdown.market_report_to_markdown(report, heading_level=2)` | `MarketReport` | 종합 보고서용 마크다운 섹션 (str) |

- `idea_id`는 평가·시연용 샘플 아이디어(`data/samples/ideas.json`)의 수집 범위로 검색을 좁힐 때만 준다. 사용자가 새로 입력한 아이디어는 `None`.
- `trend_fn`(`src.services.market_trend.build_search_trend`)을 주면 `search_trend`를 붙인다. 통합 실행(`src/pipeline.py`)과 CLI는 기본으로 넘기고, 평가·테스트는 넘기지 않는다. 주제어 선정 gpt-4o-mini 1회와 검색어 트렌드 API 1회가 추가된다.
- `network_fn`(`src.services.market_network.build_keyword_network`)을 주면 같은 컬렉션·임베딩 함수로 `keyword_network`를 붙인다. 통합 실행과 CLI는 기본으로 넘긴다. 질의 임베딩 1회가 추가되고, 프로세스에서 처음 실행할 때 전체 뉴스 명사 분석(수 초)을 한 번 한다.
- 소요 시간: 아이디어 1건당 약 13~20초 (DART 기업 선택 gpt-4o-mini 1회 + 관련성 판정 gpt-4o-mini 차원별 뉴스 5건·DART 최대 3건 + 분석 gpt-4o-mini 1~3회). 특허 조사와 입력·저장소가 독립적이라 병렬로 부를 수 있다(스레드 병렬 실행은 아직 검증하지 않음).
- 로컬 색인 `data/market/chroma/`와 `OPENAI_API_KEY`가 필요하다.
- 결과 예시: `data/samples/market_reports/SF-0{1..5}.json`

### MarketReport

| 필드 | 내용 |
|---|---|
| `status` | `completed` · `no_results`(검색 결과 없음, `evidence` 비어 있음) · `error`(`error_message`에 원인, 수집된 근거는 남을 수 있음) |
| `dimensions` | 차원별 결과 (`demand` 수요 · `competition` 경쟁·대체재 · `price` 가격 · `buyer` 구매자 · `adoption_barrier` 도입장벽) |
| `dimensions[].verdict` | `confirmed` 확인됨 · `signal_only` 신호만 확인 · `unverified` 미확인 |
| `dimensions[].claims` | 최대 3문장. `claim_type`: `fact`(사실, `citation_ids` 1개 이상) · `user_claim`(사용자 주장) · `ai_hypothesis`(AI 가설) |
| `dimensions[].next_check` | 다음 검증 과제 (`unverified`이면 항상 있음) |
| `dimensions[].evidence_status` · `relevant_count` | 검색·관련성 판정 상태(`sufficient`·`limited`·`insufficient`·`no_results`·`error`)와 관련 판정된 기사 수 |
| `dimensions[].limitation` | `confirmed`가 아닌 이유 (아이디어 항목 공백·검색 결과 없음·판정 실패·관련 기사 없음·1건뿐·사업 신호만·수요는 고객 검증 자료 필요). `confirmed`이면 `null` |
| `evidence` | 인용 근거. `citation_id`·`source_type`(`news` 뉴스 · `dart` DART 사업보고서)·제목·출처·`quote`(기사 요약 또는 사업보고서 본문 발췌, 최대 800자)·`url`·`published_at`(YYYYMMDD, 뉴스 발행일·DART 공시일)·`period`(DART 보고 대상 사업연도, 예: `FY2025`)·`section`(DART 원문 위치)·`evidence_nature`·신뢰도·최신성·직접성 |
| `unknowns` | 미확인 사항 (비어 있는 아이디어 항목, 미확인 차원) |
| `opportunity_review` | 목표 세그먼트·가치 가설·직접 수요 상태·시장 근거와 인용·미확인 사항·다음 고객 검증 행동 |
| `search_trend` | 검색 관심도 흐름 (없으면 `null`). `status`(`completed`·`insufficient_volume` 검색량 부족·`error`)·`keywords`(주제어)·`reference_keywords`(기준 주제어)·`points[]`(`period` YYYY-MM, `theme_ratio`·`reference_ratio` 요청 안 최댓값 100 기준 상대값, `relative_index` 주제어÷기준×100)·`recent_change_pct`(최근 6개월 지수 평균의 직전 6개월 대비 %)·`direction`(`rising`·`stable`·`cooling`·`unknown`)·`note`·`error_message`. 검색 관심도이며 시장 규모·수요 근거가 아니어서 차원별 판정에 쓰지 않는다. 실패해도 보고서 `status`는 바뀌지 않는다 |
| `keyword_network` | 키워드 동시 출현 네트워크 (없으면 `null`). `status`(`completed`·`insufficient` 기사·연결 부족·`error`)·`document_count`(분석 기사 수)·`nodes[]`(`term`·`document_count`·`cluster` 묶음 번호·`x`·`y` 배치 좌표 -1~1)·`edges[]`(`source`·`target`·`weight` 함께 나온 기사 수)·`clusters`(묶음별 명사, 인덱스 = `cluster`)·`note`·`error_message`. 같은 기사에 함께 나왔다는 뜻이며 수요·인과 근거가 아니다. 실패해도 보고서 `status`는 바뀌지 않는다 |
| `company_financials` | 인접 기업 재무 현황 (없으면 `null`). `status`(`completed`·`no_companies` 검색한 DART 기업 없음·`error`)·`companies[]`(`company`·`stock_code`·`statement` `연결`/`별도`·`rcept_no` 사업보고서 접수번호·`years[]` 오래된 연도부터 `year`·`revenue` 매출액·`operating_income` 영업이익·`net_income` 당기순이익·`rnd_expense` 연구개발비용(정부보조금 차감 전 총액 우선), 단위 원, 공시에 없으면 `null`)·`rnd_basis`(연구개발비용을 뽑은 표의 행 이름·단위, 찾지 못하면 그 사유)·`missing`(재무 계정을 찾지 못한 기업과 사유)·`note`·`error_message`. 기업 실적이며 시장 규모·수요 근거가 아니어서 차원별 판정에 쓰지 않는다. 실패해도 보고서 `status`는 바뀌지 않는다 |
| `search_scope` · `data_as_of` | 검색 범위 설명, 분석 기준일(YYYYMMDD) |

- 오류는 예외 대신 `status="error"` 보고서로 돌려준다(검색·판정·분석 생성 실패 모두).
- 인용 표기: UI와 마크다운 모두 시장 근거를 `M:{citation_id}`로 쓴다(특허는 `P:`). 같은 기사는 여러 차원에서 같은 `citation_id`를 쓴다.
- 해석 규칙: 뉴스의 `evidence_nature`는 관련성 판정 때 정한다. 이름이 드러난 고객의 실제 도입·계약 보도는 `purchase_signal`(구매 신호), 조사기관 통계는 `indirect_demand`(간접 수요), 그 밖은 `business_signal`(사업 신호)이다. 수요 외 차원의 `confirmed`는 구매 신호·간접 수요 근거를 인용한 사실 문장이 있을 때만, 수요 `confirmed`는 고객 검증 자료(`direct_demand`)가 있을 때만 나온다. 종합 보고서에서도 '신호만 확인'이나 구매 신호를 수요 확인으로 바꿔 쓰지 않는다.
- 화면에서 미확인을 보여 줄 때는 `limitation`을 함께 표시한다. 검색 결과가 없다는 것은 수요가 없다는 뜻이 아니다.
- JSON Schema: `MarketReport.model_json_schema()`


## 3. 특허 조사 및 통합 파이프라인

| 함수 | 입력 | 출력 |
|---|---|---|
| `src.services.patent_service.analyze_patents(request, ...)` | `PatentSearchRequest` | `PatentReport` |
| `src.pipeline.run_pipeline(draft, questions, ...)` | complete `IdeaDraft`, `{id, question, condition}` 목록, 선택 `technology_area_id` | `PipelineReport` (특허·시장 보고서, 질문별 연결, 사업 실행 검토, Markdown) |
| `src.generation.report_builder.build_question_links(questions, market, patent)` | 질문 목록, `MarketReport`, `PatentReport` | 질문별 6개 기준 연결 (`QuestionLink`) |

- 특허 검색은 요청별 기술요소 검색 결과를 문헌 단위로 합친 뒤 최대 20개 후보를 관련성 판정하고, 관련 후보에서 최대 8개 문헌을 분석한다. 후보가 부족하면 KIPRIS 검색 결과도 같은 판정을 통과해야 사용한다.
- `PatentReport.status`는 `completed`·`no_results`·`error`다. 근거는 초록 또는 청구항 원문 인용과 출처 URL·문헌 번호·출원/공개일을 보존한다. 인용은 제공 원문에 포함되는지 검사한다. 기본 분석은 문헌별 `patent_reviews`에 구성요소 대응과 인용 ID를 묶고, `patentability_precheck`에 `overlap_concern`·`potentially_distinct`·`insufficient_evidence` 예비 신호를 기록한다. 레거시 호출자가 `comparison_fn`을 주입하면 citation별 `comparisons` 계약을 유지한다. 어느 상태도 등록 가능성이나 침해 여부를 법적으로 확정하지 않는다.
- 통합 연결은 사용 맥락·해결 과제·기술 구성·요구 성능·도입 제약·근거 범위 여섯 기준을 포함한다. 각 질문에서 시장(M:)과 특허(P:) 근거 중 하나라도 연결되지 않으면 `status="hold"`다.
- API 키, KIPRIS 권한, 특허·시장 로컬 색인과 네트워크가 필요하다. Streamlit에서 `AI로 항목 초안 만들기 · 재질문`으로 시작하고 SF-02 또는 SF-05 색인을 선택한다. 실제 색인이 없는 분야는 해당 로컬 색인의 범위가 비어 있으므로 후보가 없을 수 있다.
- 비용 입력은 `frontend.workspace.cost_summary` 규칙으로 계산한다. 비어 있는 금액은 0원 처리하지 않고 미입력 항목으로 남긴다.
- JSON Schema: `PipelineReport.model_json_schema()` (`src.pipeline`)

### 통합 흐름의 실행·오류 처리

| 함수 | 입력 | 출력 |
|---|---|---|
| `src.pipeline.check_readiness(technology_area_id=None)` | 선택 특허 분야 ID | `Readiness`: 키 이름별 설정 여부(값 없음), 로컬·공용 Chroma 구분, 시장·특허 색인 건수와 분야별 건수, 실행 가능 여부·사유 |
| `src.pipeline.analyze_sources(draft, ...)` | complete `IdeaDraft`, 구성, 분야 | `SourceAnalysis`: 두 보고서, 영역별 실행 상태(`PartRun`), 분석일 |
| `src.pipeline.run_pipeline(draft, questions, ..., sources=None)` | 위와 같음. `sources`를 넘기면 조사를 다시 하지 않음 | `PipelineReport`(기존 필드 + `patent_run`·`market_run`·`readiness`·`analyzed_on`) |

- **색인 점검**은 컬렉션을 새로 만들지 않는다. 로컬은 `chroma.sqlite3` 존재, 공용 Chroma는 5초 제한 heartbeat로 확인한다. 시장 색인이 비었거나 `OPENAI_API_KEY`가 없으면 시장 조사를 호출하지 않고 `PartRun.state="skipped"`로 둔다.
- 특허는 로컬 색인(선택 분야 건수)과 `KIPRIS_API_KEY` 유무로 `patent_mode`(`local+kipris`·`kipris_only`·`local_only`·`none`)를 정한다. 로컬 색인이 없으면 빈 컬렉션을 넘겨 KIPRIS 보충 검색만 쓴다.
- **병렬 실행**: 시장·특허를 동시에 실행하고, 영역별 제한 시간(기본 시장 120초·특허 180초, `IDEALENS_MARKET_TIMEOUT`·`IDEALENS_PATENT_TIMEOUT`)을 넘기면 `timeout`으로 기록한다. 제한 시간 뒤에는 새 외부 호출을 막지만 이미 보낸 호출은 끝날 때까지 남는다. `IDEALENS_SERIAL=1`이면 순차 실행한다.
- 한 영역의 예외는 그 영역의 `error`로만 남고 다른 영역 결과는 유지한다. `PipelineReport.status`는 두 영역이 모두 `completed`이고 경고가 없을 때만 `completed`다.
- **입력 검사**: 핵심 구성·검토 질문·조건은 `input_guard.screen_text(..., min_chars=1)`로 검사하며 거절되면 `ValueError`(사용자 안내 문구)다. 빈 질문은 뺀다.
- **질문 연결**: 검증에 실패하면 오류를 덧붙여 1회 다시 생성한다. 그래도 실패하면 6개 기준을 갖춘 질문만 허용된 인용 ID로 남기고 나머지 질문만 보류한다. 연결 호출 자체가 실패하면 모든 질문을 보류한다. 경고는 `errors`와 보고서 '분석 경고'에 남는다.
- **키 마스킹**: 오류 문구·`unknowns`는 `redact`로 `.env` 키 값, `accessKey=`·`ServiceKey=` 인자, `sk-…`, `Bearer …`를 가린 뒤 보고서·화면·CLI에 내보낸다.
- **보고서**: 머리말에 분석일·시장 자료 수집 기준일(색인의 최대 `collected_at`)·근거 발행 범위를 따로 적고, 다음 행동 권고와 이유·기회·위험·미확인·검증 행동, 확정 브리프와 출처, 분석 실행 상태, 특허별 구성 비교·청구항 인용·예비 신호, 시장 절(`market_report_to_markdown`)을 싣는다. 외부·사용자 텍스트는 이스케이프하고 http(s)가 아닌 링크는 뺀다.
- CLI: `python -m src.pipeline status --json`(표준 출력은 JSON만), `python -m src.pipeline run --idea-id SF-02 [--questions 파일] [--out 결과.json]`(API 비용 발생).


## 4. 평가 실행·재현 정보

- 시장 검색 최신 비교: `python -m evaluation.evaluate market --idea-ids SF-01,SF-02,SF-03,SF-04 --mode {dense,bm25,hybrid} --label refreshed`. 이 20문항 집합은 새 SF-05 분야와 다른 기존 음성 어시스턴트 라벨을 제외한다.
- 특허 후보 라벨링: `python -m evaluation.patent_labeling export` → `evaluation/labels/patent_candidates.csv`에서 사람 판단 `relevant=0/1` → `python -m evaluation.patent_labeling import` → `python -m evaluation.evaluate patent --mode {dense,bm25,hybrid} --label <name>`. 다섯 문항에는 아직 사람 정답이 없으므로 라벨 전에는 성능 수치를 만들지 않는다.
- 답변 평가: `python -m evaluation.answer_eval --limit 5`는 같은 질문에서 LLM 단독과 검색 근거가 있는 답변을 만들고 LLM 평가자에게 인용 정확성·근거 충실성·사실 정확성(각 1~5)과 오류 유형을 기록한다. 사람 판정 점수가 아닌 탐색적 LLM 평가다.
- 검색 결과 CSV는 mode, 모델, prompt 적용 여부, 현재 커밋 ID를 포함한다. 답변 결과는 두 prompt의 SHA-256, 생성/평가 모델, 지연, 토큰 사용량을 보존한다. API 키와 비용이 필요하다.
