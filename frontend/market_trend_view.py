"""시장성 화면의 검색 관심도 흐름(MarketReport.search_trend) 표시."""

import streamlit as st

from src.generation.market_markdown import search_trend_summary


def trend_rows(trend) -> list[dict]:
    """차트용 월별 지수 행 목록. 기준 검색량이 0인 달은 뺀다."""
    return [
        {"월": p.period, "관심도 지수": p.relative_index}
        for p in trend.points
        if p.relative_index is not None
    ]


def render_search_trend(trend, widget_suffix: str = "") -> None:
    """검색 관심도 흐름을 요약·월별 선 그래프·해석 주의 문구로 보여 준다. trend가 없으면 표시하지 않는다.

    같은 화면에 두 번 그릴 때(미리보기 대화상자 등) widget_suffix로 차트 key를 구분한다.
    """
    if trend is None:
        return
    st.markdown("**검색 관심도 흐름**")
    st.caption(search_trend_summary(trend))
    rows = trend_rows(trend)
    if trend.status == "completed" and rows:
        import altair as alt
        import pandas as pd

        chart = (
            alt.Chart(pd.DataFrame(rows))
            .mark_line(point=True)
            .encode(
                x=alt.X("월:N", title=None, sort=None),
                y=alt.Y("관심도 지수:Q", title="기준 대비 지수"),
                tooltip=["월", "관심도 지수"],
            )
            .properties(height=220)
        )
        st.altair_chart(
            chart,
            key=f"market_search_trend{widget_suffix}",
            width="stretch",
            alt="아이디어 주제어의 월별 네이버 검색 관심도 지수(기준 주제어 대비) 선 그래프",
        )
    if trend.note:
        st.caption(trend.note)
