"""서비스의 사용 흐름과 특허·시장 연결 관점을 짧은 설명·도식으로 소개한다."""

import streamlit as st


def render_introduction(page):
    with st.container(key="introduction"):
        if page == "about":
            st.html('<span class="intro-eyebrow">MEET IDEALENS</span>')
            st.title("생각 한 줄이, 검토 노트가 되기까지.")
            st.write("아이디어를 구체화하고, 특허와 시장에서 근거를 찾습니다.")
            st.html(
                """<section class="intro-journey" aria-label="아이디어에서 조사와 보고서로 이어지는 흐름">
                <article class="journey-card"><span class="journey-icon idea-icon" aria-hidden="true">✦</span><span class="intro-number">01 / IDEA</span><h2>아이디어를 적고</h2><p>무엇을 · 누구를 위해 · 어떻게</p><div class="note-lines"><i></i><i></i><i></i></div></article>
                <span class="journey-arrow" aria-hidden="true">→</span>
                <article class="journey-card dual-card"><span class="intro-number">02 / EVIDENCE</span><h2>두 근거를 찾고</h2><div class="mini-lanes"><div><b>특허 · 기술</b><span>관련 구성 · 청구항</span></div><div><b>시장 · 기업</b><span>고객 · 도입 맥락</span></div></div></article>
                <span class="journey-arrow" aria-hidden="true">→</span>
                <article class="journey-card"><span class="journey-icon report-icon" aria-hidden="true">▤</span><span class="intro-number">03 / RESEARCH NOTE</span><h2>판단을 정리합니다</h2><p>연결한 이유 · 아직 모르는 것</p><div class="note-tags"><span>근거</span><span>조건</span><span>다음 검증</span></div></article>
                </section>"""
            )
            a, b, c = st.columns(3)
            for col, title, body in [
                (
                    a,
                    "막연해도 시작할 수 있어요",
                    "빠진 내용은 AI가 다시 묻고, 핵심 구성은 직접 확인합니다.",
                ),
                (
                    b,
                    "출처를 열어볼 수 있어요",
                    "특허·시장 자료를 나란히 보고 인용한 원문을 확인합니다.",
                ),
                (
                    c,
                    "결과를 보관할 수 있어요",
                    "검토 노트를 PDF·Markdown으로 받고 내 기록에 남깁니다.",
                ),
            ]:
                with col:
                    st.subheader(title)
                    st.write(body)
            st.caption(
                "실제 조사는 외부 API 사용료가 발생합니다. 결과는 검토 초안이며 최종 사업성·권리범위 판단을 대신하지 않습니다."
            )
        else:
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
            st.html(
                """<section class="connection-board" aria-label="특허 근거와 시장 맥락을 하나의 질문으로 연결">
                <article class="evidence-node patent-node"><span class="intro-number">PATENT</span><span class="node-symbol" aria-hidden="true">▧</span><h2>기술의 근거</h2><p>관련 특허는?<br>구성과 차이는?</p></article>
                <div class="connection-center"><span class="connection-line" aria-hidden="true"></span><strong>하나의<br>검토 질문</strong><span class="connection-line" aria-hidden="true"></span><p>아이디어를 구체화한 뒤<br>두 근거의 연결 이유를 확인</p></div>
                <article class="evidence-node market-node"><span class="intro-number">MARKET</span><div class="mini-chart" aria-hidden="true"><i></i><i></i><i></i><i></i></div><h2>시장의 맥락</h2><p>어떤 고객에게?<br>어떤 도입 조건에서?</p></article>
                </section>"""
            )
            st.subheader("특허와 시장, 따로 찾고 함께 연결합니다.")
            st.html(
                """<div class="intro-takeaway"><b>근거가 부족하면, 부족한 상태 그대로.</b><span>관련 특허가 있다는 이유만으로 수요가 있다고 판단하지 않습니다.<br>연결이 확인되지 않은 부분과 다음에 확인할 조건도 노트에 남깁니다.</span></div>"""
            )
            st.caption(
                "특정 경쟁 제품의 기능·성능 비교가 아닌 IdeaLens의 검토 관점입니다. 시장 자료는 현재 수집된 뉴스 범위이며 수요 검증·특허성·사업성을 확정하지 않습니다."
            )
