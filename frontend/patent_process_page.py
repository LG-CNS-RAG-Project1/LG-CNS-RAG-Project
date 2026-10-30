"""IdeaLens 특허 검색부터 평가까지의 흐름을 안내한다."""

import streamlit as st


_STEPS = (
    (
        "01 · 아이디어를 기술 질의로 구조화",
        "기술 구성요소를 중심으로 한국어·영어 질의를 만든다. 고객·가격 같은 사업 조건과 기술 검색어를 분리한다.",
        "`src/retrieval/patent_search.py` · `src/schemas.py`",
    ),
    (
        "02 · KIPRIS에서 특허 문헌과 청구항 수집",
        "검색어별 문헌을 찾고 출원번호 기준으로 중복을 정리한다. 청구항 원문은 별도 API 권한과 응답이 있을 때만 사용한다.",
        "`src/ingestion/kipris_client.py` · `docs/patent_rag.md`",
    ),
    (
        "03 · 문헌을 정규화하고 청크 색인",
        "초록과 청구항을 검색 단위로 나누면서 청구항 번호, 독립·종속항 유형, 상위항 참조, 문헌 식별자를 보존한다.",
        "`src/ingestion/patent_processor.py` · ChromaDB",
    ),
    (
        "04 · Dense·BM25·Hybrid로 후보 생성",
        "Dense 검색은 의미가 가까운 표현을 찾고 BM25는 기술 용어의 일치를 찾는다. Hybrid는 두 순위를 RRF로 결합한다.",
        "`src/retrieval/patent_search.py` · `src/retrieval/engine.py`",
    ),
    (
        "05 · 청크를 특허 단위로 합치고 재정렬",
        "한 문헌의 여러 청크가 결과를 독점하지 않게 특허 단위로 모으고, 초록·독립항·종속항 근거와 검색 순위를 보존한다.",
        "검색 후보 집계 · 선택적 Cross-Encoder 재정렬",
    ),
    (
        "06 · 분야 필터와 전체 색인 fallback 추적",
        "선택 분야 검색과 전체 색인 fallback을 구분한다. 분야 적합성과 기술 관련성은 서로 다른 판단으로 기록한다.",
        "`src/services/patent_service.py`",
    ),
    (
        "07 · 청구항 비교와 인용 근거 작성",
        "문헌별 기술 구성, 유사점, 차이점과 미확인 항목을 정리하고 원문 근거를 연결한다. 청구항 미확보 시 초록 기반임을 드러낸다.",
        "`src/generation/patent_analysis.py` · `src/generation/patent_design.py`",
    ),
    (
        "08 · 같은 라벨 풀로 검색 품질 평가",
        "후보 생성 재현율과 상위 순위 품질을 나눠 Recall, Precision@5, Hit@5, MRR@5, nDCG@5 등을 비교한다.",
        "`evaluation/patent_cases.json` · `evaluation/patent_labeling.md`",
    ),
)


def render_patent_process_page():
    """검색 구성과 검증 한계를 사용자에게 설명한다."""
    with st.container(key="patent_process_page"):
        st.caption("IDEALENS · 특허 조사 흐름")
        st.title("특허 검색은 어떻게 근거가 되나요?")
        st.write(
            "아이디어의 기술 요소에서 출발해 특허 후보를 찾고, 청구항과 원문 근거를 확인하는 과정을 단계별로 살펴봅니다."
        )

        first, second, third = st.columns(3)
        first.metric("검색 입력", "기술 구성요소", "한국어 · 영어 질의")
        second.metric("후보 단위", "특허 문헌", "청크 중복 완화")
        third.metric("검증 기준", "사람 검토 라벨", "AI 판정은 보조")

        st.subheader("수집에서 평가까지")
        for title, description, source in _STEPS:
            with st.expander(title, expanded=title.startswith("01")):
                st.write(description)
                st.caption(f"구현 근거: {source}")

        st.divider()
        st.subheader("결과를 해석할 때 확인할 점")
        left, right = st.columns(2)
        with left:
            st.markdown(
                "**후보 수와 검색 품질은 다릅니다.** 후보를 많이 모아도 관련 문헌이 상위에 배치된다는 뜻은 아닙니다."
            )
            st.markdown(
                "**미판정 문헌은 정답이 아닙니다.** AI가 만든 관련도는 라벨링 보조 자료로 보고, 품질 지표에는 사람이 검토한 문헌만 사용합니다."
            )
        with right:
            st.markdown(
                "**Recall은 평가 풀 범위와 함께 봅니다.** 미발견 문헌이나 미판정 후보가 많으면 전체 검색 재현율을 확정할 수 없습니다."
            )
            st.markdown(
                "**분야 일치와 기술 관련성을 분리합니다.** 전체 색인 fallback 결과는 검색 경로를 구분해 해석해야 합니다."
            )

        st.info(
            "이 화면은 시스템 흐름 안내입니다. 특허 비교 결과는 기술 검토 자료이며, 특허성·침해 여부·실시 자유에 대한 법률 의견이 아닙니다."
        )
        st.caption(
            "페이지 주소에 `?page=patent-process`가 포함되므로 주소창 링크를 복사해 바로 공유할 수 있습니다."
        )
