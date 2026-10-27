# 시장 조사 설계

아이디어 한 문장을 5개 항목으로 구조화한 뒤, 수요·경쟁/대체재·가격·구매자·도입장벽 5개 차원별로
시장 근거를 검색하고, 출처가 확인된 문장만으로 시장 분석 결과를 만든다.

## 처리 흐름

```mermaid
flowchart TD
  start(["사용자 아이디어 입력"])
  parse["아이디어 구조화<br/>문장에 있는 내용만 5개 항목으로 추출"]
  filled{"5개 항목 모두 입력됨?"}
  ask["빈 항목 재질문<br/>사용자 답변 병합 · 모름 허용"]
  structure["아이디어 5개 항목 (공통 입력)<br/>문제·기술·고객·차별점·수익모델"]
  patent["특허 검색 요청<br/>(특허 파트)"]

  subgraph data["시장 데이터 기반"]
    direction TB
    news["네이버 뉴스 수집<br/>키워드 26개 · 제목·요약·링크만"]
    dart["DART 공시 수집<br/>사업의 내용·매출 (선택)"]
    clean["정제·메타데이터 부여<br/>MarketDocument"]
    dedup["중복 제거<br/>같은 URL · 제목 유사도 0.8 · 3일 이내"]
    index["Chroma 색인<br/>news 컬렉션 · cosine<br/>1기사 = 1청크"]
    news --> clean
    dart -.-> clean
    clean --> dedup --> index
  end

  query["차원별 질의 생성<br/>수요·경쟁·가격·구매자·도입장벽"]
  filter["메타데이터 필터<br/>아이디어 · 출처 유형 · 발행일"]
  vector["벡터 검색<br/>text-embedding-3-small · 후보 Top-20"]
  group["중복 그룹 정리<br/>dup_group당 1건"]
  top["차원별 근거 Top-5 선정"]
  enough{"충분성 확인<br/>임계 거리 이내 3건 이상?"}
  live["네이버 API 실시간 보충<br/>색인 추가 후 재검색 (선택)"]
  lack["자료 부족 표시"]
  nature["근거 성격 분류<br/>사업 신호 / 직접 수요"]
  verdict["차원별 판정<br/>확인됨 · 신호만 확인 · 미확인"]
  task["미확인 차원의<br/>검증 과제 1개 제안"]

  gen["시장 분석 생성<br/>gpt-4o-mini · 차원별 최대 3문장"]
  cite["사실 문장마다 [source_id] 인용<br/>출처에 없는 수치 생성 금지"]
  check["인용 존재·원문 일치·<br/>수치 출처·기준연도 검증"]
  pass{"검증 통과?"}
  drop["실패 문장 제거<br/>해당 차원 미확인 표시"]
  contract["시장 파트 결과 계약<br/>MarketReport"]
  handoff["UI·특허·종합 보고서 통합은<br/>담당 팀에 인계"]
  done(["전체 서비스 통합"])

  subgraph eval["검색·답변 품질 평가와 개선"]
    direction TB
    cases["평가셋 25문항<br/>아이디어 5개 × 차원 5개<br/>정답 source_id 라벨"]
    metrics["Hit@5 · Recall@5 · MRR"]
    answer["Citation Accuracy ·<br/>오류 로그 E01–E10"]
    cost["Latency · 비용 측정<br/>응답 시간 · 토큰 · API 호출"]
    compare["LLM 단독 vs RAG 비교<br/>같은 25문항"]
    improved{"개선 효과 확인?"}
    tune["키워드·질의 템플릿·<br/>임계값 조정"]
    fix["설정·데이터 버전 고정<br/>및 회귀 평가"]
    cases --> metrics --> answer --> cost --> compare --> improved
    improved -- 아니오 --> tune --> metrics
    improved -- 예 --> fix
  end

  start --> parse --> filled
  filled -- 아니오 · 최대 2회 --> ask --> filled
  filled -- 예 · 2회 후 남은 항목은 모름 --> structure
  structure --> query
  structure -.-> patent
  index --> vector
  query --> filter --> vector --> group --> top --> enough
  enough -- 예 --> nature
  enough -- 아니오 · 보충 사용 --> live
  enough -- 아니오 · 보충 미사용 --> lack
  live -. 재검색 1회 .-> vector
  live -- 재검색 후에도 부족 --> lack
  lack --> verdict
  nature --> verdict
  verdict -- 미확인 차원 있음 --> task --> gen
  verdict -- 모두 확인됨·신호만 확인 --> gen
  gen --> cite --> check --> pass
  pass -- 아니오 · 최대 2회 재생성 --> gen
  pass -- 2회 실패 --> drop --> contract
  pass -- 예 --> contract
  contract --> handoff --> done
  top -. 검색 결과 평가 대상 .-> metrics
  check -. 인용 검증 결과 .-> answer

  classDef io fill:#eaf1fb,stroke:#6d8fbf,color:#1d2b3a
  classDef term fill:#17263c,stroke:#17263c,color:#ffffff
  classDef search fill:#e8f5ec,stroke:#5f9e74,color:#1d3326
  classDef genstep fill:#efeafa,stroke:#8f7cc4,color:#2b2340
  classDef evalnode fill:#fff3d9,stroke:#cf9f45,color:#3d2f12
  classDef decide fill:#fbe9e1,stroke:#d0825f,color:#3d2318
  classDef todo stroke-dasharray:5 4

  class start,done term
  class parse,ask,structure,patent,news,dart,clean,dedup,index io
  class query,filter,vector,group,top,live,lack,nature search
  class verdict,task,gen,cite,check,drop,contract,handoff genstep
  class cases,metrics,answer,cost,compare,tune,fix evalnode
  class filled,enough,pass,improved decide
  class dart,enough,live,lack,nature,verdict,task,gen,cite,check,pass,drop,contract,answer,cost,compare,improved,tune,fix todo

  style data fill:#9aa3ad1f,stroke:#9aa3ad
  style eval fill:#9aa3ad1f,stroke:#9aa3ad
```

- 색: 파랑 = 입력·데이터 준비, 초록 = 검색, 보라 = 분석 생성·검증, 노랑 = 평가, 주황 = 판단 분기
- 점선 테두리: 아직 구현되지 않은 단계 / 점선 화살표: 선택 단계, 평가 연결, 다른 파트로의 인계
- 아이디어 5개 항목(`StructuredIdea`)은 특허 파트와 공통 입력이며, UI·보고서 통합(파트 1·4)은 시장 파트의 출력 경계다.
- 재시도 상한: 빈 항목 재질문 2회, 실시간 보충 후 재검색 1회, 인용 검증 실패 시 재생성 최대 2회.
- 재질문 후에도 비어 있는 항목은 모름으로 표시하고, 해당 항목에 기대는 차원은 미확인으로 판정한다(예: 수익모델 모름 → 가격 미확인).

## 아이디어 5개 항목

| 항목 | 필드 | 주로 쓰는 시장 차원 |
|---|---|---|
| 문제 | `problem` | 수요 |
| 기술 | `technology` | 전 차원 |
| 고객 | `customers` | 수요·구매자·도입장벽 |
| 차별점 | `difference` | 경쟁/대체재 |
| 수익모델 | `revenue` | 가격 |

## 단계별 코드 위치

| 단계 | 위치 |
|---|---|
| 아이디어 구조화·재질문 | `prompts/idea_parser.md`, `src/generation/idea_parser.py` |
| 수집 키워드·요청 설정 | `configs/market_keywords.yaml` |
| 네이버 뉴스 수집 | `src/ingestion/news_client.py` → `data/market/raw/` |
| DART 공시 수집 | `src/ingestion/dart_client.py` |
| 정제·중복 제거 | `src/ingestion/market_processor.py` → `data/market/processed/market_docs.jsonl` |
| 색인·차원별 검색 툴 | `src/retrieval/market_search.py` → `data/market/chroma/` |
| 시장 조사 진입점 | `src/services/market_service.py` |
| 시장 분석 생성 규칙 | `prompts/market_analysis.md`, `src/generation/market_analysis.py` |
| 데이터 형식·결과 계약 | `src/schemas.py` (`MarketDocument`, `MarketSearchRequest`, `MarketReport`) |
| 평가 문항·정답 라벨 | `evaluation/market_cases.json`, `evaluation/labels/`, `evaluation/market_labeling.py`, `evaluation/market_judge.py` |
| 검색 평가 실행·결과 | `evaluation/evaluate.py` → `evaluation/results/` |
