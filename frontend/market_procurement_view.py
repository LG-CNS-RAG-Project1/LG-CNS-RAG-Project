"""시장성 화면의 공공 조달 입찰공고(MarketReport.procurement) 표시."""

import streamlit as st

from src.generation.market_markdown import (
    format_won,
    procurement_rows,
    procurement_stats,
    procurement_summary,
)

MAX_LISTED = 10


def render_procurement(procurement) -> None:
    """공공 조달 공고를 요약·예산 지표·구매 주체 유형·공고 목록·해석 주의 문구로 보여 준다.

    procurement가 없으면 표시하지 않는다.
    """
    if procurement is None:
        return
    st.markdown("**공공 조달 공고**")
    st.caption(procurement_summary(procurement))
    stats = procurement_stats(procurement)
    if stats["count"]:
        count, median, spread = st.columns(3)
        count.metric("관련 공고", f"{stats['count']}건")
        median.metric("예산 중앙값", format_won(stats["median"]))
        spread.metric(
            "예산 범위", f"{format_won(stats['min'])} ~ {format_won(stats['max'])}"
        )
        st.caption(
            "구매 주체: "
            + " · ".join(f"{name} {n}건" for name, n in stats["buyer_types"].items())
        )
        rows = procurement_rows(procurement, MAX_LISTED)
        st.dataframe(
            rows,
            hide_index=True,
            width="stretch",
            column_config={
                "공고": st.column_config.LinkColumn("공고", display_text="열기"),
            },
        )
        if stats["count"] > MAX_LISTED:
            st.caption(f"최근 {MAX_LISTED}건만 표시합니다.")
    if procurement.note:
        st.caption(procurement.note)
