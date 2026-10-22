"""Streamlit 기반 아이디어 입력·결과 확인 시연 화면."""

import sys
from pathlib import Path

import streamlit as st

# Streamlit의 직접 실행에서도 저장소의 공통 모델을 찾는다.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frontend.demo import build_demo, report_markdown
from src.schemas import PatentReport, StructuredIdea

st.set_page_config(page_title="IdeaLens · 아이디어 검토", page_icon="🔎", layout="wide")

with st.sidebar:
    st.title("IdeaLens")
    st.caption("사업과 기술을 근거로 살펴보는 작업 공간")
    st.info("시연 모드 · API 키 없이 사용")
    st.markdown(
        "**사용 순서**\n\n1. 아이디어 입력\n2. 예시 결과 확인\n3. 근거와 미확인 사항 검토"
    )
    st.divider()
    st.caption("입력은 이 브라우저 세션에서만 사용하며 외부 API로 전송하지 않습니다.")
    if st.button("결과 초기화"):
        st.session_state.pop("result", None)

st.caption("IDEA → EVIDENCE → NEXT STEP")
st.title("아이디어를 근거와 함께 검토하세요")
st.write(
    "해결할 문제와 기술을 정리하고, 경영진과 R&D 관점에서 필요한 근거를 확인합니다."
)
st.warning(
    "현재는 화면 시연용입니다. 실제 특허·시장 검색 및 AI 분석은 수행하지 않습니다."
)

left, right = st.columns([1, 1.6], gap="large")
with left:
    st.subheader("01 · 아이디어 입력")
    example = st.selectbox("입력 시작 방법", ["직접 입력", "설비 이상 탐지 예시"])
    use_example = example != "직접 입력"
    with st.form("idea_input"):
        title = st.text_input(
            "아이디어 제목 *", value="설비 이상 탐지" if use_example else ""
        )
        problem = st.text_area(
            "해결할 문제 *",
            value=(
                "공장 설비의 이상 징후를 조기에 파악하기 어렵습니다."
                if use_example
                else ""
            ),
        )
        technology = st.text_area(
            "기술·해결 방식 *",
            value=(
                "진동 센서 데이터를 분석해 기준 상태에서 벗어나는 징후를 알립니다."
                if use_example
                else ""
            ),
        )
        customers = st.text_input(
            "대상 고객", value="제조업 설비 관리자" if use_example else ""
        )
        submitted = st.form_submit_button("시연 결과 보기", type="primary")
    if submitted:
        if not all(value.strip() for value in [title, problem, technology]):
            st.session_state.pop("result", None)
            st.error("제목, 해결할 문제, 기술·해결 방식을 입력해 주세요.")
        else:
            idea = StructuredIdea(
                title=title.strip(),
                problem=problem.strip(),
                technology=technology.strip(),
                customers=customers.strip(),
            )
            st.session_state.result = build_demo(idea)

with right:
    st.subheader("02 · 결과와 근거")
    result = st.session_state.get("result")
    if result is None:
        st.info("왼쪽에서 입력하거나 예시를 선택한 후 ‘시연 결과 보기’를 눌러 주세요.")
        st.markdown(
            "**경영진 요약** · 판단에 필요한 핵심과 다음 조사\n\n**R&D 상세** · 기술 근거와 검증 한계"
        )
    else:
        st.caption(
            f"표시 중인 제출 결과: {result['idea']['title']} · 입력 변경 후에는 다시 제출하세요."
        )
        executive, research, next_steps = st.tabs(
            ["경영진 요약", "R&D 상세", "다음 검증"]
        )
        with executive:
            st.markdown("### 검토 과제")
            st.write(result["idea"]["title"])
            st.caption("아래 설명은 사용자가 입력한 내용이며 확인된 사실이 아닙니다.")
            st.write(result["idea"]["problem"])
            st.write(result["idea"]["technology"])
            st.info(
                "판단 보류 · 실제 특허 근거와 시장 자료를 연결한 뒤 검토해야 합니다."
            )
            st.markdown(
                "**시장 근거:** 미연결\n\n**실제 특허 조사:** 미수행\n\n**가상 예시:** 1건"
            )
        with research:
            patent = PatentReport.model_validate(result["patent"])
            st.caption(patent.search_scope)
            for evidence in patent.evidence:
                with st.expander(
                    f"[가상 근거 {evidence.citation_id}] {evidence.title}",
                    expanded=True,
                ):
                    st.write(evidence.quote)
                    st.caption(
                        f"문헌 ID: {evidence.patent_id} · 구획: {evidence.section}"
                    )
                    st.warning(
                        "실재 문헌이 아니므로 출처 링크와 유사도 점수를 제공하지 않습니다."
                    )
            st.markdown(
                "**실제 특허 비교:** 미수행 · API 연결 후 공통 PatentReport로 교체 예정"
            )
        with next_steps:
            st.markdown(
                "- 특허 담당: 실제 문헌·청구항·출처 확인\n"
                "- 시장 담당: 고객 수요·도입 장벽과 출처 확인\n"
                "- 통합 담당: 입력·응답 API 명세 합의\n"
                "- UI 담당: 실제 응답의 빈 결과·오류·부분 성공 화면 검증"
            )
            st.caption(
                "특허 유사성만으로 등록 가능성·침해 여부·사업성을 판단하지 않습니다."
            )
        st.download_button(
            "시연 보고서 다운로드 (.md)",
            data=report_markdown(result),
            file_name="idealens-demo-report.md",
            mime="text/markdown",
        )
