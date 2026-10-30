"""서비스의 사용 흐름과 특허·시장 연결 관점을 짧은 설명·도식으로 소개한다."""

import streamlit as st


def _select_intro(view):
    st.session_state.introduction_view = view
    st.session_state.scroll_to_top = True


def _render_journey():
    st.html("""<section class="info-journey" aria-label="IdeaLens의 사용 흐름">
    <article><small>01 / IDEA</small><h2>생각을 구체화합니다</h2><p>한 줄의 아이디어에서 문제·기술·고객을 정리합니다. 빠진 내용은 질문으로 확인합니다.</p></article>
    <article><small>02 / EVIDENCE</small><h2>두 근거를 찾습니다</h2><p>특허에서는 기술 구성의 차이를, 시장에서는 고객과 도입 조건을 살펴봅니다.</p></article>
    <article><small>03 / RESEARCH NOTE</small><h2>다음 판단을 남깁니다</h2><p>확인한 사실과 아직 모르는 것을 구분하고, 다음 검증 과제를 정리합니다.</p></article>
    </section>""")
    with st.container(key="intro_links"):
        left, right = st.columns(2)
        left.button(
            "특허 조사 흐름 →",
            key="intro_open_patent",
            on_click=_select_intro,
            args=("patent",),
            width="stretch",
        )
        right.button(
            "시장 조사 흐름 →",
            key="intro_open_market",
            on_click=_select_intro,
            args=("market",),
            width="stretch",
        )


def render_introduction(page):
    with st.container(key="introduction"):
        if page == "about":
            from frontend.process_guide import process_styles, render_process_guide

            st.html(process_styles())
            view = st.session_state.get("introduction_view", "overview")
            if view not in {"overview", "patent", "market"}:
                view = "overview"
            if view != "overview":
                render_process_guide(view)
                return
            st.html('<span class="intro-eyebrow">MEET IDEALENS</span>')
            st.title("생각 한 줄이, 검토 노트가 되기까지.")
            st.write("아이디어를 구체화하고, 특허와 시장에서 근거를 찾습니다.")
            _render_journey()
            st.divider()
            st.subheader("출처를 확인하고, 결과를 보관하세요")
            st.write(
                "보고서의 인용에서 원문으로 이동하고, PDF·Markdown으로 내려받거나 내 기록에 남길 수 있습니다."
            )
            st.caption(
                "실제 조사는 외부 API 사용료가 발생합니다. 결과는 검토 초안이며 최종 사업성·권리범위 판단을 대신하지 않습니다."
            )
        else:
            from frontend.process_guide import process_styles

            st.html(process_styles())
            view = st.session_state.get("difference_view", "perspective")
            if view == "examples":
                from frontend.showcase import render_showcase

                render_showcase()
                return
            st.html('<span class="intro-eyebrow">WHY IDEALENS</span>')
            st.title("특허 분석에, 시장 조사를 더하다.")
            st.write(
                "관련 기술을 찾는 데서 더 나아가, 어떤 고객에게 어떻게 쓰일 아이디어인지 구체화합니다."
            )
            st.html(
                """<section class="difference-comparison" aria-label="특허 중심 검토와 IdeaLens의 조사 범위 비교">
                <article class="comparison-base"><span class="intro-number">특허 중심의 검토 흐름</span><h2>어떤 기술이 있나요?</h2><div class="scope-chips"><span>특허 검색</span><span>문헌·청구항 분석</span></div><p>관련 기술과 구성의 차이를 살펴봅니다.</p></article>
                <div class="comparison-plus" aria-hidden="true">＋</div>
                <article class="comparison-expanded"><span class="intro-number">IDEALENS가 더하는 검토</span><h2>시장에서는 어떻게 쓰일까요?</h2><div class="scope-chips"><span>아이디어 구체화</span><span>시장·기업 조사</span><span>양쪽 근거 연결</span></div><p>기술의 관련성과 고객·도입 맥락을<br>같은 질문으로 연결해 검토 노트를 만듭니다.</p></article>
                </section>"""
            )
            st.subheader("특허와 시장, 따로 찾고 함께 연결합니다.")
            st.html(
                """<div class="intro-takeaway"><b>근거가 부족하면, 부족한 상태 그대로.</b><span>관련 특허가 있다는 이유만으로 수요가 있다고 판단하지 않습니다.<br>연결이 확인되지 않은 부분과 다음에 확인할 조건도 노트에 남깁니다.</span></div>"""
            )
            st.caption(
                "IdeaLens의 조사 범위를 설명합니다. 특정 경쟁 제품의 기능·성능을 비교한 결과는 아닙니다. 뉴스·공시 등에서 확인한 신호와 실제 구매 의사는 구분합니다."
            )
