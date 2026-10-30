"""소개·기록·조사 화면의 맥락에 맞는 고정 이동 바."""

import streamlit as st


def _page_button(page, label, icon, current_page, open_page):
    st.button(
        label,
        key=f"rail_{page}",
        icon=icon,
        type="primary" if page == current_page else "secondary",
        on_click=open_page,
        args=(page,),
        width="stretch",
    )


def _top_link():
    st.html(
        '<a class="rail-top" href="#research-top" target="_self" '
        'aria-label="화면 맨 위로 이동"><span aria-hidden="true">↑</span>맨 위로</a>'
    )


def render_page_nav(page, open_page, resume_research, *, has_research=False):
    """공개 안내 화면에서는 단계 대신 페이지 이동과 진행 중 조사 복귀를 제공한다."""
    with st.container(key="research_rail"):
        st.html('<div class="rail-caption">바로가기</div>')
        for target, label, icon in (
            ("home", "홈", ":material/home:"),
            ("about", "서비스 소개", ":material/info:"),
            ("difference", "차별점", ":material/compare_arrows:"),
            ("patent-process", "특허 검색 흐름", ":material/schema:"),
            ("market-process", "시장 조사 흐름", ":material/monitoring:"),
            ("history", "내 기록", ":material/history:"),
        ):
            _page_button(target, label, icon, page, open_page)
        if page != "home" or has_research:
            st.html('<div class="rail-divider" aria-hidden="true"></div>')
            st.button(
                "조사 계속" if has_research else "조사 시작",
                key="rail_resume",
                icon=":material/travel_explore:",
                on_click=resume_research,
                width="stretch",
            )
        _top_link()


def render_quick_nav(render_stage, open_page):
    """기존 단계 이동의 잠금·분석 중 미리보기 규칙을 그대로 사용한다."""
    with st.container(key="research_rail"):
        st.html('<div class="rail-caption">바로가기</div>')
        _page_button("home", "홈", ":material/home:", "workspace", open_page)
        for number, label, icon in (
            (1, "아이디어", ":material/edit_note:"),
            (2, "특허", ":material/find_in_page:"),
            (3, "시장", ":material/monitoring:"),
            (4, "보고서", ":material/summarize:"),
        ):
            render_stage(number, label, st, f"rail_{number}", icon=icon)
        st.html('<div class="rail-divider" aria-hidden="true"></div>')
        _page_button("history", "내 기록", ":material/history:", "workspace", open_page)
        _top_link()
