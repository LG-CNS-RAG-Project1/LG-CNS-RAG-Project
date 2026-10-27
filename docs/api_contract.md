# 서비스 연결 계약

파이프라인(`src/pipeline.py`)과 Streamlit UI가 각 파트의 진입점을 부를 때의 입력·출력·오류 처리 약속이다.
데이터 형식은 모두 `src/schemas.py`의 Pydantic 모델이며, JSON으로 주고받을 때는 `model_dump_json()`·`model_validate_json()`을 쓴다.
특허 파트와 통합 흐름의 계약은 각 담당이 이 문서에 추가한다.

## 1. 아이디어 입력

| 함수 | 입력 | 출력 |
|---|---|---|
| `src.generation.idea_parser.parse_idea(text)` | 아이디어 문장 (str) | `IdeaDraft` |
| `src.generation.idea_parser.apply_answers(draft, answers)` | `IdeaDraft`, `{항목: 답변}` (항목: `problem`·`technology`·`customers`·`difference`·`revenue`) | `IdeaDraft` |
| `src.generation.idea_parser.build_requests(draft)` | `status="complete"`인 `IdeaDraft` | `(PatentSearchRequest, MarketSearchRequest)` |

`IdeaDraft.status`로 다음 단계를 정한다.

| status | 의미 | 다음 단계 |
|---|---|---|
| `rejected` | 주제 이탈(`input_status="off_topic"`) 또는 프롬프트 조작·유해 목적(`"unsafe"`) | `rejection_reason`을 사용자에게 보여 주고 종료. 특허·시장 검색을 부르지 않는다 |
| `needs_input` | 빈 항목이 있음 (재질문 최대 2회) | `questions`(`{항목: 질문}`)를 보여 주고 답변으로 `apply_answers` |
| `complete` | 5개 항목 확정 (끝까지 비어 있으면 `field_sources`가 `unknown`) | `build_requests`로 특허·시장 검색 요청 생성 |

- LLM 호출은 `parse_idea`의 1회뿐이다. `apply_answers`는 LLM을 부르지 않는다.
- 예외: 빈 문장은 `parse_idea`가 `ValueError`, `OPENAI_API_KEY`가 없으면 `RuntimeError`, OpenAI API 오류는 그대로 올라온다. `rejected` 초안에 `apply_answers`를 부르거나 미완성 초안에 `build_requests`를 부르면 `ValueError`다.
- JSON Schema: `IdeaDraft.model_json_schema()`

## 2. 시장 조사

| 함수 | 입력 | 출력 |
|---|---|---|
| `src.services.market_service.run_market_research(request, idea_id=None)` | `MarketSearchRequest` (`build_requests`의 두 번째 값) | `MarketReport` |
| `src.generation.market_markdown.market_report_to_markdown(report, heading_level=2)` | `MarketReport` | 종합 보고서용 마크다운 섹션 (str) |

- `idea_id`는 평가·시연용 샘플 아이디어(`data/samples/ideas.json`)의 수집 범위로 검색을 좁힐 때만 준다. 사용자가 새로 입력한 아이디어는 `None`.
- 소요 시간: 아이디어 1건당 약 13~20초 (관련성 판정 gpt-4o 25회 + 분석 gpt-4o 1~3회). 특허 조사와 입력·저장소가 독립적이라 병렬로 부를 수 있다(스레드 병렬 실행은 아직 검증하지 않음).
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
| `evidence` | 인용 근거. `citation_id`·제목·출처·`quote`(기사 요약)·`url`·`published_at`(YYYYMMDD)·`evidence_nature`·신뢰도·최신성·직접성 |
| `unknowns` | 미확인 사항 (비어 있는 아이디어 항목, 미확인 차원) |
| `search_scope` · `data_as_of` | 검색 범위 설명, 분석 기준일(YYYYMMDD) |

- 오류는 예외 대신 `status="error"` 보고서로 돌려준다(검색·판정·분석 생성 실패 모두).
- 인용 표기: UI와 마크다운 모두 시장 근거를 `M:{citation_id}`로 쓴다(특허는 `P:`). 같은 기사는 여러 차원에서 같은 `citation_id`를 쓴다.
- 해석 규칙: 수집 뉴스는 모두 `business_signal`(사업 신호)이므로 수요 `confirmed`는 고객 검증 자료(`direct_demand`)가 있을 때만 나온다. 종합 보고서에서도 '신호만 확인'을 수요 확인으로 바꿔 쓰지 않는다.
- JSON Schema: `MarketReport.model_json_schema()`
