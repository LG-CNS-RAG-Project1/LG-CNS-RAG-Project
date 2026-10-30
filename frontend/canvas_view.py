"""종합 보고서 요약 화면의 예비 비즈니스 모델 캔버스(PipelineReport.canvas) 표시."""

import streamlit as st

from src.generation.business_canvas import (
    BLOCK_LABELS,
    BusinessCanvas,
    item_suffix,
)
from src.generation.market_markdown import cell

# 표준 캔버스 배치: 위 줄 5칸(가운데 두 칸은 위아래로 두 블록), 아래 줄 비용·수익
TOP_ROW = (
    ("key_partners",),
    ("key_activities", "key_resources"),
    ("value_propositions",),
    ("customer_relationships", "channels"),
    ("customer_segments",),
)
BOTTOM_ROW = ("cost_structure", "revenue_streams")
LEGEND = "표시 없음: 아이디어 입력 · M:·P:·T·F: 조사 근거 ID · 가설: 검증 전 AI 제안"


def canvas_item_line(item) -> str:
    """블록 안 항목 제목 한 줄. 출처 표시는 회색 작은 글씨로 뒤에 붙인다."""
    suffix = item_suffix(item)
    return f"- **{cell(item.text)}**" + (f" :gray[{cell(suffix)}]" if suffix else "")


def _render_block(canvas: BusinessCanvas, name: str) -> None:
    with st.container(border=True):
        st.markdown(f"**{BLOCK_LABELS[name]}**")
        items = getattr(canvas, name)
        if not items:
            st.caption("내용 없음")
        for item in items:
            st.markdown(canvas_item_line(item))
            if item.detail:
                st.caption(item.detail)


def render_canvas(raw) -> None:
    """캔버스를 표준 9블록 배치와 해석 주의 문구로 보여 준다. 만들지 못했으면 사유만 보여 준다."""
    canvas = BusinessCanvas.model_validate(raw)
    st.subheader("비즈니스 모델 캔버스 (예비)")
    if canvas.status != "completed":
        st.info(
            "비즈니스 모델 캔버스를 만들지 못했습니다. "
            + (canvas.error_message or "검증을 통과한 항목이 없습니다.")
        )
        return
    st.caption(LEGEND)
    for column, names in zip(st.columns(len(TOP_ROW)), TOP_ROW):
        with column:
            for name in names:
                _render_block(canvas, name)
    for column, name in zip(st.columns(len(BOTTOM_ROW)), BOTTOM_ROW):
        with column:
            _render_block(canvas, name)
    st.caption(canvas.note)
