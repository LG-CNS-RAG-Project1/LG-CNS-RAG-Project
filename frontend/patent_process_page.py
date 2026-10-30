"""IdeaLens 특허 검색 파이프라인과 평가 범위를 안내한다."""

import streamlit as st

_STEPS = (
    (
        "01 · 아이디어를 기술 질의로 구조화",
        "아이디어 전체를 그대로 검색하지 않고, 실제 발명 구성과 작동 기능을 검색 가능한 단위로 나눈다.",
        (
            (
                "기술 요소 추출",
                "LLM · Pydantic 구조화 결과",
                "고객·가격·산업 맥락이 기술 구성으로 섞이는 것을 줄인다.",
            ),
            (
                "질의 확장",
                "요소별 한국어·영어 질의",
                "표현이 달라도 같은 기능·구성을 다루는 문헌을 찾는다.",
            ),
            (
                "검색 계획",
                "2~5개 핵심 구성요소",
                "넓은 단일 질의 대신 기술 요소별 후보와 근거를 추적한다.",
            ),
        ),
        "`src/retrieval/patent_search.py` · `src/schemas.py` · `docs/patent_rag.md`",
    ),
    (
        "02 · KIPRIS 문헌과 청구항 수집",
        "분야와 기술 질의에 맞는 특허 후보를 수집한다. 서지·초록 검색과 청구항 상세 조회의 성공 여부를 구분한다.",
        (
            (
                "기본 문헌 정보",
                "KIPRIS 검색 API",
                "출원번호·발명의 명칭·초록 등 후보 확인에 필요한 정보를 모은다.",
            ),
            (
                "청구항 상세",
                "별도 상세 API 권한·응답",
                "가져오지 못한 청구항을 추정해 채우지 않고 초록 기반으로 한계를 표시한다.",
            ),
            (
                "호출 상한",
                "최대 5개 한국어 질의 보충",
                "검색 결과가 부족할 때만 외부 후보를 보충해 호출 경로를 제한한다.",
            ),
        ),
        "`src/ingestion/kipris_client.py` · `src/services/patent_service.py` · `docs/patent_rag.md`",
    ),
    (
        "03 · 문헌 정규화와 청킹·색인",
        "검색 단위는 문헌 전체가 아니라 초록과 개별 청구항이다. 청크를 문헌과 청구항 계보로 다시 연결할 메타데이터를 유지한다.",
        (
            (
                "청크 구성",
                "초록 1개 + 청구항별 청크",
                "긴 문헌 안의 기술 근거 위치를 더 세밀하게 찾는다.",
            ),
            (
                "청구항 관계",
                "번호·독립/종속 유형·상위항",
                "종속항을 읽을 때 인용하는 부모 청구항을 함께 확인할 수 있다.",
            ),
            (
                "문헌 추적성",
                "출원 식별자·버전·수집 시점",
                "검색 청크를 원문 문헌과 수집 버전까지 거슬러 확인한다.",
            ),
        ),
        "`src/ingestion/patent_processor.py` · ChromaDB · `docs/patent_rag.md`",
    ),
    (
        "04 · 검색 방식별 후보 생성",
        "동일 질의에서 의미 유사도와 용어 일치의 차이를 비교한다. 기본 경로는 Dense이며 BM25·Hybrid는 설정해 비교할 수 있다.",
        (
            (
                "Dense",
                "임베딩 의미 검색",
                "표현이 다르지만 기술적으로 가까운 후보를 찾는다. 현재 질의 임베딩 경로는 OpenAI 키를 사용한다.",
            ),
            (
                "BM25",
                "용어 기반 검색",
                "희귀한 기술명·구성 용어가 문헌에 직접 나타나는 경우를 보완한다.",
            ),
            (
                "Hybrid",
                "Dense + BM25 · RRF 결합",
                "점수 단위가 다른 두 검색기의 순위를 결합해 후보를 만든다.",
            ),
        ),
        "`src/retrieval/patent_search.py` · `src/retrieval/engine.py` · `README.md`",
    ),
    (
        "05 · 청크를 문헌 단위로 집계·재정렬",
        "한 문헌의 청크가 후보 목록을 차지하지 않도록 출원 문헌 단위로 합친다. 후보 생성과 순위 개선은 별도 단계로 기록한다.",
        (
            (
                "후보 집계",
                "출원/문헌 ID 기준 중복 제거",
                "초록과 여러 청구항이 검색돼도 한 문헌이 후보 슬롯을 독점하지 않게 한다.",
            ),
            (
                "근거 보존",
                "매칭 질의·섹션·청크 순위",
                "최고 점수 하나로 덮지 않고 어떤 기술 요소와 초록/청구항이 매치됐는지 남긴다.",
            ),
            (
                "선택적 재정렬",
                "Bi-Encoder 또는 BGE Cross-Encoder",
                "후보를 더 모으는 기능과 상위 순위를 정교화하는 기능을 나눠 검증한다. 재정렬은 추가 지연·의존성이 든다.",
            ),
        ),
        "`src/retrieval/patent_search.py` · `src/services/patent_service.py` · 특허 청킹·재정렬 평가 도구",
    ),
    (
        "06 · 분야 검색과 fallback 경로 표시",
        "선택 기술 분야에서 먼저 찾고 관련 후보가 부족하면 전체 색인에서 보충한다. 분야 분류 적합성과 기술 관련도는 다른 축으로 다룬다.",
        (
            (
                "분야 필터 검색",
                "`technology_area_id` 조건",
                "선택한 분야에 속한 색인 문헌을 우선 찾는다.",
            ),
            (
                "전체 색인 fallback",
                "분야 검색 결과 부족 시 실행",
                "분야 분류 누락으로 놓칠 수 있는 기술 후보를 보충하고 검색 경로를 추적한다.",
            ),
            (
                "관련성 판정",
                "LLM 판정은 필터 보조",
                "LLM의 관련 판단은 평가 정답 라벨로 재사용하지 않는다.",
            ),
        ),
        "`src/services/patent_service.py` · `src/retrieval/patent_relevance.py`",
    ),
    (
        "07 · 청구항 비교와 인용 보고서",
        "검색 후보 중 비교에 쓸 문헌을 선택해 기술 구성·유사점·차이와 확인되지 않은 내용을 정리한다.",
        (
            (
                "비교 문헌 선택",
                "최대 8건 · 근거 부족 시 축소",
                "목표 문헌 수를 채우려고 관련성이 낮은 후보를 억지로 포함하지 않는다.",
            ),
            (
                "청구항 맥락 구성",
                "관련 청구항 최대 5개/특허",
                "종속항은 부모항을 함께 포함하고 토큰 예산 안에서 근거를 구성한다.",
            ),
            (
                "결과와 한계",
                "인용 근거·미확인 상태·설계 검토",
                "최대 3개 설계 대안은 검토용이며 특허성·침해·FTO 법률 판단이 아니다.",
            ),
        ),
        "`src/generation/patent_analysis.py` · `src/generation/patent_design.py` · `docs/patent_rag.md`",
    ),
    (
        "08 · 사람 라벨로 검색 품질 평가",
        "같은 질의·색인·사람 검토 문헌 풀에서 후보를 찾는 성능과 상위 순위 품질을 따로 측정한다. 현재 저장소 추적 평가에는 사람 라벨이 없다.",
        (
            (
                "평가 문항",
                "5개 고정 케이스 · SF-02 3개, SF-05 2개",
                "넓은 분야 대표성보다 적은 고정 질의의 초기 평가 범위로 해석한다.",
            ),
            (
                "현재 라벨 상태",
                "후보 CSV 70행 · 사람 라벨 0행",
                "관련/비관련 판정이 아직 없어 품질 지표를 계산하거나 개선을 주장할 수 없다.",
            ),
            (
                "비교 지표",
                "후보 Recall · Hit@5 · Precision@5 · MRR@5 · nDCG@5",
                "후보 생성과 상위 순위를 분리한다. 후보 풀 밖 미발견 문헌은 측정되지 않는다.",
            ),
        ),
        "`evaluation/patent_cases.json` · `evaluation/labels/patent_candidates.csv` · `evaluation/patent_labeling.md`",
    ),
)


def _render_step(title, description, details, source):
    with st.container(border=True):
        st.markdown(f"#### {title}")
        st.write(description)
        columns = st.columns(2)
        for index, (name, tool, reason) in enumerate(details):
            with columns[index % 2]:
                st.markdown(f"**{name}** · {tool}")
                st.caption(f"선택 이유: {reason}")
        st.caption(f"코드·자료: {source}")


def render_patent_process_page():
    """특허 검색 단계, 비교 기준과 현재 평가 한계를 보여준다."""
    with st.container(key="patent_process_page"):
        st.caption("IDEALENS · 스마트팩토리 · 특허 검색 흐름")
        st.title("특허 검색은 어떻게 근거가 되나요?")
        st.write(
            "기술 구성요소에서 검색 질의를 만들고, 문헌 단위 후보를 비교한 뒤 청구항과 원문 근거를 검토하는 과정을 살펴봅니다."
        )

        first, second, third = st.columns(3)
        first.metric("질의 계획", "2~5개 기술 요소")
        first.caption("요소별 한국어 · 영어 확장")
        second.metric("비교 문헌", "최대 8건")
        second.caption("관련 후보가 부족하면 축소")
        third.metric("현재 평가", "사람 라벨 0행")
        third.caption("5개 케이스 · 후보 CSV 70행")

        st.subheader("수집에서 평가까지")
        for title, description, details, source in _STEPS:
            _render_step(title, description, details, source)

        st.divider()
        st.subheader("검색 방식은 같은 조건에서 비교합니다")
        st.caption(
            "아래는 현재 평가 설계에 포함된 방식입니다. 라벨이 없어 특허 검색 점수는 아직 산출되지 않았습니다."
        )
        st.table(
            {
                "단계": ["후보 생성", "후보 생성", "후보 생성", "재정렬", "재정렬"],
                "방식": [
                    "Dense",
                    "BM25",
                    "Hybrid (RRF)",
                    "Bi-Encoder",
                    "Cross-Encoder",
                ],
                "현재 상태": [
                    "서비스 기본 경로",
                    "비교 가능",
                    "비교 가능",
                    "선택 실험 · 임베딩 API 추가",
                    "선택 실험 · 모델 의존성 추가",
                ],
                "평가 점수": ["미산출"] * 5,
            }
        )

        st.subheader("평가 지표와 분모")
        st.table(
            {
                "지표": [
                    "Candidate Recall@K",
                    "Hit@5",
                    "Precision@5",
                    "MRR@5",
                    "nDCG@5",
                ],
                "읽는 법": [
                    "사람이 관련이라고 판정한 문헌 중 후보 단계에서 찾은 비율",
                    "상위 5건에 관련 문헌이 하나 이상 있는 질의 비율",
                    "상위 5건의 관련 문헌 비율",
                    "첫 관련 문헌 순위의 역수 평균",
                    "관련 문헌이 상위에 올수록 높아지는 순위 점수",
                ],
                "주의점": [
                    "분모는 평가 후보 풀 안의 판정 관련 문헌이며 전체 색인 재현율이 아님",
                    "모든 비교 방식에서 같은 완전 판정 질의만 사용",
                    "미판정·보류 문헌을 비관련으로 간주하지 않음",
                    "질의별 결과와 표본 수를 함께 확인",
                    "사람 라벨이 충분하기 전에는 점수 미산출",
                ],
            }
        )

        st.subheader("재현 가능한 평가 흐름")
        st.code(
            "python -m evaluation.patent_labeling export\n"
            "# 후보 CSV에서 원문을 검토해 relevant=0/1, review_status=reviewed, label_source=human 입력\n"
            "python -m evaluation.patent_labeling import\n"
            "python -m evaluation.evaluate patent --mode dense --label human\n"
            "python -m evaluation.evaluate patent --mode bm25 --label human\n"
            "python -m evaluation.evaluate patent --mode hybrid --label human",
            language="bash",
        )
        st.caption(
            "비교 방식은 동일한 사람 라벨·색인·질의를 사용해야 합니다. 새 후보가 미판정이면 먼저 검토하고, 평가 결과에 색인·질의 설정과 검색 시간을 함께 남깁니다."
        )

        st.subheader("결과를 해석할 때 확인할 점")
        left, right = st.columns(2)
        with left:
            st.markdown(
                "**후보 수와 순위 품질은 다릅니다.** 더 많은 문헌을 수집하거나 후보로 가져와도 관련 문헌이 상위에 배치된다는 뜻은 아닙니다."
            )
            st.markdown(
                "**AI 판정은 정답 라벨이 아닙니다.** 제목·초록 기반 AI 초안은 사람 검토 전에는 지표 계산에서 제외합니다."
            )
            st.markdown(
                "**분야 적합성과 기술 관련성은 별도입니다.** 선택 분야 결과와 전체 색인 fallback 경로를 분리해 확인합니다."
            )
        with right:
            st.markdown(
                "**후보 풀 밖은 미확인입니다.** 평가 후보에 들어오지 않은 관련 특허를 알 수 없으면 전체 코퍼스 재현율을 결론 낼 수 없습니다."
            )
            st.markdown(
                "**재정렬에는 비용과 지연이 따릅니다.** 품질이 같은 사람 라벨에서 개선되는지와 추가 모델·API 사용량을 함께 봅니다."
            )
            st.markdown(
                "**청킹은 근거 단위입니다.** 청구항의 번호·독립/종속 관계를 잃으면 검색 결과의 기술 맥락도 약해질 수 있습니다."
            )

        st.warning(
            "현재 저장소에 추적된 5개 평가 케이스는 모두 미라벨이며, 후보 CSV 70행도 관련도 판정이 비어 있습니다. 따라서 이 페이지에는 검색 품질 점수를 싣지 않았습니다. 평가 문헌 풀이 작거나 불완전할 수 있어, 후보 수가 적다는 이유만으로 품질이 높다고 볼 수 없습니다."
        )
        st.info(
            "이 화면은 조사 흐름 안내입니다. 특허 비교 결과는 기술 검토 자료이며, 특허성·신규성·진보성·침해 여부·실시 자유에 대한 법률 의견이 아닙니다."
        )
        st.caption(
            "코드·평가 근거: `src/services/patent_service.py`, `src/retrieval/patent_search.py`, `docs/patent_rag.md`, `evaluation/patent_labeling.md`. 페이지 주소에 `?page=patent-process`가 포함되어 바로 공유할 수 있습니다."
        )
