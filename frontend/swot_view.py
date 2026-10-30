"""종합 보고서 요약 화면의 예비 SWOT(PipelineReport.swot) 2×2 표시."""

import streamlit as st

from src.generation.swot import BASIS_LABELS, QUADRANT_LABELS, SwotAnalysis

# 화면 배치 순서: 위 줄 내부 요인(강점·약점), 아래 줄 외부 요인(기회·위협)
LAYOUT = (("strengths", "weaknesses"), ("opportunities", "threats"))


def swot_item_caption(item) -> str:
    """항목 아래에 붙일 근거 구분·근거 ID 문구."""
    refs = " · " + ", ".join(item.citation_ids) if item.citation_ids else ""
    return BASIS_LABELS[item.basis] + refs


def render_swot(raw) -> None:
    """SWOT을 사분면 2×2와 해석 주의 문구로 보여 준다. 만들지 못했으면 사유만 보여 준다."""
    swot = SwotAnalysis.model_validate(raw)
    st.subheader("SWOT 분석 (예비)")
    if swot.status != "completed":
        st.info(
            "SWOT을 만들지 못했습니다. "
            + (swot.error_message or "검증을 통과한 항목이 없습니다.")
        )
        return
    for row in LAYOUT:
        columns = st.columns(2)
        for column, name in zip(columns, row):
            with column.container(border=True):
                st.markdown(f"**{QUADRANT_LABELS[name]}**")
                items = getattr(swot, name)
                if not items:
                    st.caption("확인된 항목이 없습니다.")
                for item in items:
                    st.markdown(f"- {item.text}")
                    st.caption(swot_item_caption(item))
    st.caption(swot.note)
