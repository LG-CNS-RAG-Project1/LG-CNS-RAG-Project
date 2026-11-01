"""Render market investigation results and supporting evidence in Streamlit."""

import streamlit as st


def _render_market_details(market, draft=None, widget_suffix=""):
    """실제 시장 근거·시각화와 조사 범위를 중심으로 보고서를 표시한다."""
    from src.generation.market_markdown import NATURE_LABELS
    from src.retrieval.market_relevance import DIMENSION_LABELS

    if market.status == "error":
        st.error(
            "시장 조사를 완료하지 못했습니다. 조사 범위와 오류 상태를 확인해 주세요."
        )
    elif market.status == "no_results":
        st.warning(
            "현재 검색 범위에서 시장 근거를 찾지 못했습니다. 수요가 없다는 뜻은 아닙니다."
        )
    else:
        st.caption(
            f"조사 범위: {market.search_scope} · 기준일 {market.data_as_of or '미제공'}"
        )

    trend = getattr(market, "search_trend", None)
    from frontend.market_trend_view import render_search_trend

    if trend is None:
        st.info("이번 분석 결과에 검색 관심도 데이터가 포함되지 않았습니다.")
    else:
        render_search_trend(trend, widget_suffix)
        st.caption(
            "검색 관심도는 기준 검색어 대비 상대 지수이며 시장 규모나 고객 수요의 근거가 아닙니다."
        )

    network = getattr(market, "keyword_network", None)
    from frontend.market_network_view import render_keyword_network

    if network is None:
        st.info("이번 분석 결과에 뉴스 키워드 네트워크 데이터가 포함되지 않았습니다.")
    else:
        render_keyword_network(network, widget_suffix)
        st.caption(
            "뉴스 제목·요약에서 함께 나온 단어의 관계이며 수요·인과·고객 유형을 뜻하지 않습니다."
        )

    financials = getattr(market, "company_financials", None)
    if financials is not None:
        from frontend.market_financials_view import render_company_financials

        render_company_financials(financials)
    procurement = getattr(market, "procurement", None)
    if procurement is not None:
        from frontend.market_procurement_view import render_procurement

        render_procurement(procurement)

    observed_dimensions = [
        dimension
        for dimension in market.dimensions
        if dimension.verdict in {"confirmed", "signal_only"} and dimension.claims
    ]
    if observed_dimensions:
        st.subheader("시장 자료에서 확인된 관찰")
        st.caption("각 문장은 시장 보고서의 기존 분석과 인용을 그대로 표시합니다.")
        for dimension in observed_dimensions:
            with st.container(border=True):
                state = (
                    "근거 확인" if dimension.verdict == "confirmed" else "신호만 확인"
                )
                st.markdown(f"#### {DIMENSION_LABELS[dimension.dimension]} · {state}")
                for claim in dimension.claims[:2]:
                    claim_type = {
                        "fact": "자료 사실",
                        "user_claim": "사용자 입력",
                        "ai_hypothesis": "검증 전 가설",
                    }[claim.claim_type]
                    refs = (
                        ", ".join(f"M:{cid}" for cid in claim.citation_ids)
                        or "인용 근거 없음"
                    )
                    st.markdown(f"- **{claim_type}:** {claim.statement}")
                    st.caption(f"근거: {refs}")
                if dimension.relevant_count is not None:
                    st.caption(
                        f"관련 판정 자료 {dimension.relevant_count}건 · 인용 수와는 별도 집계"
                    )
                if dimension.limitation:
                    st.caption("해석 한계: " + dimension.limitation)
    elif market.status == "completed":
        st.info("이번 조사에서 인용으로 확인된 시장 관찰 문장은 없습니다.")

    pending_checks = [
        (dimension, dimension.next_check)
        for dimension in market.dimensions
        if dimension.next_check and dimension.verdict == "unverified"
    ]
    if pending_checks:
        st.markdown("#### 근거를 더 확인할 항목")
        for dimension, next_check in pending_checks:
            label = DIMENSION_LABELS[dimension.dimension]
            limitation = f" · {dimension.limitation}" if dimension.limitation else ""
            st.markdown(f"- **{label}:** {next_check}{limitation}")

    dart_evidence = [item for item in market.evidence if item.source_type == "dart"]
    if dart_evidence:
        st.subheader("관련 기업의 DART 공시 발췌")
        st.caption(
            "아이디어 관련 검색에서 연결된 기업의 자체 사업보고서입니다. 검색된 기업이 실제 경쟁사라는 확인이나 특허 보유 관계를 뜻하지 않습니다."
        )
        companies = {}
        for item in dart_evidence:
            company = (
                item.publisher.removesuffix(" (DART 사업보고서)").strip()
                or "공시 기업 미제공"
            )
            companies.setdefault(company, []).append(item)
        company_columns = st.columns(min(len(companies), 2))
        for index, (company, items) in enumerate(companies.items()):
            with company_columns[index % len(company_columns)]:
                with st.container(border=True):
                    st.markdown(f"#### {company}")
                    for item in items[:3]:
                        period = item.period or "사업연도 미제공"
                        section = item.section or "원문 위치 미제공"
                        st.caption(f"M:{item.citation_id} · {period} · {section}")
                        st.markdown(f"**{item.title}**")
                        st.write(item.quote)
                        if item.url and item.url.startswith(("https://", "http://")):
                            st.link_button("공시 원문 열기 ↗", item.url)
        st.caption(
            "공시 발췌 수는 기업 규모·경쟁력·시장 점유율의 비교 지표가 아닙니다."
        )

    if market.evidence:
        from src.generation.market_markdown import market_report_to_markdown
        from src.generation.report_builder import escape_md, safe_url

        with st.expander(f"시장 근거 전체와 분석 원문 ({len(market.evidence)}건)"):
            st.markdown(market_report_to_markdown(market, heading_level=3))
            for item in market.evidence:
                st.markdown(f"**M:{item.citation_id} · {escape_md(item.title)}**")
                details = [
                    item.publisher,
                    item.period or "기간 미제공",
                    item.section or "원문 위치 미제공",
                ]
                st.caption(
                    " · ".join(details)
                    + f" · {NATURE_LABELS.get(item.evidence_nature, item.evidence_nature)}"
                )
                st.write(item.quote)
                url = safe_url(item.url)
                if url:
                    st.link_button("시장 원문 열기", url)

    if market.unknowns:
        with st.expander(f"시장 조사 한계와 미확인 항목 ({len(market.unknowns)}건)"):
            for item in market.unknowns:
                st.write(f"- {item}")


def render_market_report(market, draft=None, widget_suffix=""):
    """요약을 먼저 보여주고 팀 공용 상세 렌더러는 접어 제공한다."""
    from frontend.report_reading import render_market_brief

    if market.status == "error":
        st.error("시장 조사를 완료하지 못했습니다. 상세에서 처리 상태를 확인해 주세요.")
    render_market_brief(market)
    with st.expander("상세 근거·시각화 펼쳐보기"):
        _render_market_details(market, draft, widget_suffix)
