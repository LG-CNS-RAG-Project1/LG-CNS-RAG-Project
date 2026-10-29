"""긴 조사 화면에서도 결과와 기록에 접근할 수 있는 고정 이동 바."""

import streamlit as st


def render_quick_nav(render_stage, open_page):
    """기존 단계 이동의 잠금·분석 중 미리보기 규칙을 그대로 사용한다."""
    with st.container(key="research_rail"):
        st.html('<div class="rail-caption">바로가기</div>')
        for number, label, icon in (
            (1, "아이디어", ":material/edit_note:"),
            (2, "특허", ":material/find_in_page:"),
            (3, "시장", ":material/monitoring:"),
            (4, "보고서", ":material/summarize:"),
        ):
            render_stage(number, label, st, f"rail_{number}", icon=icon)
        st.html('<div class="rail-divider" aria-hidden="true"></div>')
        st.button(
            "내 기록",
            key="rail_history",
            icon=":material/history:",
            on_click=open_page,
            args=("history",),
            width="stretch",
        )
        st.html(
            '<a class="rail-top" href="#research-top" target="_self" '
            'aria-label="화면 맨 위로 이동"><span aria-hidden="true">↑</span>맨 위로</a>'
        )
