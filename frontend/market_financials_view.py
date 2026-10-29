"""시장성 화면의 인접 기업 재무 현황(MarketReport.company_financials) 표시."""

import streamlit as st

from src.generation.market_markdown import (
    company_financial_rows,
    company_financials_summary,
)


def render_company_financials(financials) -> None:
    """검색한 DART 기업의 재무 현황을 요약·표·해석 주의 문구로 보여 준다. financials가 없으면 표시하지 않는다."""
    if financials is None:
        return
    st.markdown("**인접 기업 재무 현황**")
    st.caption(company_financials_summary(financials))
    rows = company_financial_rows(financials)
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    for item in financials.missing:
        st.caption(f"재무 계정 없음: {item}")
    if financials.note:
        st.caption(financials.note)
