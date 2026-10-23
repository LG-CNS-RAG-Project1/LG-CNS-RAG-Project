# IdeaLens PR 분석 안내서

> PR 자동 분석(scripts/review)이 목표·역할·규칙을 판단할 때 쓰는 기준 문서. 항목 상태는 [확정] [초안] [비어 있음]으로 표기하고, 리더가 확정한다.
> 모든 항목이 [초안]이므로 판단 근거로 쓸 때는 "초안 기준"임을 밝힌다. [비어 있음] 항목은 근거로 쓰지 않고 판단을 보류한다.

## 목표
- B-GOAL-0 [초안] 개발 기반: CI(black·pytest), Docker 개발 환경, PR 협업 자동화(리뷰어 지정·Notion 문서화)를 안정적으로 유지한다.
- B-GOAL-1 [초안] 특허 근거: KIPRIS Plus 수집 → 정제·청킹 → 정확·의미 검색(Chroma, text-embedding-3-small 초기 검토) → 인용 검증.
- B-GOAL-2 [초안] 시장 근거: DART·공공·연구기관·기업 공식 자료 수집과 판정. 뉴스는 이용조건 확인 후 활용.
- B-GOAL-3 [초안] 보고서·화면: 경영진 요약, R&D 상세 보고서 초안, 미확인 사항과 다음 검증 과제를 제공한다. 사실·해석·가설·미확인을 구분하고 근거가 부족하면 판단을 보류하며, 최종 판단은 사용자가 한다.
- B-GOAL-4 [초안] 평가: 검색 품질(Hit Rate@K, Recall@K, MRR), 답변 품질(정확성·근거 충실성·인용 정확성), 일반 LLM 대비 RAG 비교.

## 이번 시기 우선순위
- B-PRIO [비어 있음] 리더가 작성 예정.

## 범위
- B-SCOPE-1 [초안] 범위 안: KIPRIS Plus, DART, 공공기관·연구기관·기업의 공식 자료.
- B-SCOPE-2 [초안] 뉴스는 이용조건 확인 후 활용. 사내자료 연계는 향후 확장 범위.
- B-SCOPE-3 [초안] 처리 흐름: 아이디어 구조화 → 자료 수집·전처리 → 검색 → 근거 검증 → 보고서 생성.

## 역할
- B-ROLE [비어 있음] GitHub ID ↔ 역할 ↔ 담당 영역은 리더가 기입 예정. 역할 경계 판단은 보류한다.

## 담당 영역과 약속
- B-MOD-1 [초안] 공통 데이터 계약은 `src/schemas.py`(StructuredIdea, PatentReport, Market* 모델)다. 계약 변경은 사용하는 영역 전체에 영향을 준다.
- B-MOD-2 [초안] 서비스 구조: 사용자 → `frontend/`(Streamlit UI) → `src/main.py`(FastAPI) → `src/services/` → `src/pipeline.py` → `src/ingestion/`·`src/retrieval/`·`src/generation/`. API 계약 문서(`docs/api_contract.md`)는 비어 있다.
- B-MOD-3 [초안] 비밀값(API 키)은 `.env`에만 두고 `.env.example`에는 이름만 둔다.

## 팀 규칙
- B-RULE-1 [초안] 한 기능 브랜치(`feature/영문소문자-하이픈`)에는 그 기능과 직접 관련된 작업만 한다(AGENTS §2).
- B-RULE-2 [초안] 기능·구조·파일이 바뀌면 README.md를 함께 갱신한다(AGENTS §4).
- B-RULE-3 [초안] README·주석·테스트·로그·커밋에 실제 비밀값을 넣지 않는다(AGENTS §5).
- B-RULE-4 [초안] 주석에는 현재 동작만 쓰고 날짜·작성자·버전·이력 메타데이터를 쓰지 않는다(AGENTS §6).
- B-RULE-5 [초안] 커밋 제목은 명사형 또는 음슴체, 본문은 `-` 목록(AGENTS §8).
