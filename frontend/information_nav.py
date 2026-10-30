"""세션을 유지하는 소개 메뉴와 마우스·키보드 하위 탐색."""

import streamlit as st

from frontend.process_guide import process_styles


def _navigate(open_page, page, view):
    if page == "about":
        st.session_state.introduction_view = view
    elif page == "difference":
        st.session_state.difference_view = view
    open_page(page)


def render_information_header(open_page):
    st.html(process_styles())
    with st.container(key="brandbar"):
        brand, intro, difference, records = st.columns([2.6, 1, 1.2, 0.8])
        brand.button("IdeaLens", key="home", on_click=open_page, args=("home",))
        for column, page, key, label, entries in (
            (
                intro,
                "about",
                "about",
                "서비스 소개",
                (
                    ("overview", "서비스 개요", "intro_tab_overview"),
                    ("patent", "특허 조사 흐름", "intro_tab_patent"),
                    ("market", "시장 조사 흐름", "intro_tab_market"),
                ),
            ),
            (
                difference,
                "difference",
                "difference",
                "왜 IdeaLens인가",
                (
                    ("perspective", "차별점과 검토 관점", "difference_tab_perspective"),
                    ("examples", "화면 예시·검증", "difference_tab_examples"),
                ),
            ),
        ):
            with column.container(key=f"nav_{key}"):
                st.button(
                    label + " ⌄",
                    key=f"header_{key}",
                    on_click=_navigate,
                    args=(open_page, page, entries[0][0]),
                    width="stretch",
                )
                with st.container(key=f"nav_{key}_dropdown"):
                    st.caption(label)
                    for view, text, button_key in entries:
                        st.button(
                            text,
                            key=button_key,
                            on_click=_navigate,
                            args=(open_page, page, view),
                            width="stretch",
                        )
        records.button(
            "내 기록", key="header_history", on_click=open_page, args=("history",)
        )
