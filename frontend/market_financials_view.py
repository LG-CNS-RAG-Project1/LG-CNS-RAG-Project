"""시장성 화면의 인접 기업 재무 현황(MarketReport.company_financials) 표시."""

import streamlit as st

from frontend.market_network_view import _theme
from src.generation.market_markdown import (
    company_financial_rows,
    company_financials_summary,
)

PROFIT, LOSS, UNKNOWN = "영업이익 흑자", "영업이익 적자", "영업이익 미제공"
BAR_COLORS = {
    "light": {PROFIT: "#2a78d6", LOSS: "#d03b3b", UNKNOWN: "#8a8984"},
    "dark": {PROFIT: "#3987e5", LOSS: "#d03b3b", UNKNOWN: "#8a8984"},
}
# 막대 위 숫자, 패널 제목·연도·범례 글자, 기준선 색
LABEL_COLOR = {"light": "#55534e", "dark": "#c3c2b7"}
TEXT_COLOR = {"light": "#203d3b", "dark": "#e6e5df"}
AXIS_COLOR = {"light": "#c3c2b7", "dark": "#383835"}
SCALE_NOTE = (
    "기업마다 세로축 범위가 달라 막대 높이로 기업끼리 비교하지 않습니다. "
    "막대 위 숫자(억원)로 비교하세요."
)


def financial_chart_rows(financials) -> list[dict]:
    """기업별 매출액 막대 그래프용 행 목록. 매출액이 없는 연도는 뺀다.

    패널 제목은 '기업 · 영업이익률(최근 연도)'이고, 막대 색은 그 연도 영업이익의 흑자·적자다.
    """
    margins = {r["기업"]: r["영업이익률"] for r in company_financial_rows(financials)}
    rows = []
    for company in financials.companies:
        panel = f"{company.company} · 영업이익률 {margins[company.company]}"
        for year in company.years:
            if year.revenue is None:
                continue
            income = year.operating_income
            rows.append(
                {
                    "패널": panel,
                    "연도": str(year.year),
                    "매출액(억원)": round(year.revenue / 1e8),
                    "영업이익(억원)": None if income is None else round(income / 1e8),
                    "영업이익": (
                        UNKNOWN if income is None else PROFIT if income >= 0 else LOSS
                    ),
                }
            )
    return rows


def financial_chart(financials, theme: str = "light"):
    """기업별 3개 연도 매출액 막대를 기업마다 다른 세로축으로 나란히 그린다(altair). 행이 없으면 None.

    범례에는 실제로 쓰인 흑자·적자·미제공만 고정 순서와 고정 색으로 둔다.
    """
    rows = financial_chart_rows(financials)
    if not rows:
        return None
    import altair as alt
    import pandas as pd

    used = {r["영업이익"] for r in rows}
    colors = {k: v for k, v in BAR_COLORS[theme].items() if k in used}
    base = alt.Chart(pd.DataFrame(rows)).encode(
        x=alt.X("연도:N", title=None, axis=alt.Axis(labelAngle=0)),
        y=alt.Y("매출액(억원):Q", title=None, axis=None),
    )
    bars = base.mark_bar(
        cornerRadiusTopLeft=4, cornerRadiusTopRight=4, width={"band": 0.7}
    ).encode(
        color=alt.Color(
            "영업이익:N",
            scale=alt.Scale(domain=list(colors), range=list(colors.values())),
            legend=alt.Legend(title=None, orient="bottom"),
        ),
        tooltip=["연도", "매출액(억원)", "영업이익(억원)", "영업이익"],
    )
    labels = base.mark_text(dy=-6, baseline="bottom", fontSize=11).encode(
        text=alt.Text("매출액(억원):Q", format=","),
        color=alt.value(LABEL_COLOR[theme]),
    )
    return (
        alt.layer(bars, labels)
        .properties(width=150, height=150)
        .facet(column=alt.Column("패널:N", title=None, sort=None))
        .resolve_scale(y="independent")
        .configure_view(stroke=None)
        .configure_axis(
            labelColor=TEXT_COLOR[theme],
            domainColor=AXIS_COLOR[theme],
            tickColor=AXIS_COLOR[theme],
        )
        .configure_header(
            labelColor=TEXT_COLOR[theme],
            labelFontSize=12,
            labelExpr="split(datum.label, ' · ')",  # 기업명과 영업이익률을 두 줄로
        )
        .configure_legend(labelColor=TEXT_COLOR[theme])
    )


def render_company_financials(financials) -> None:
    """검색한 DART 기업의 재무 현황을 요약·기업별 매출액 그래프·표·해석 주의 문구로 보여 준다.

    financials가 없으면 표시하지 않는다.
    """
    if financials is None:
        return
    st.markdown("**인접 기업 재무 현황**")
    st.caption(company_financials_summary(financials))
    chart = financial_chart(financials, _theme())
    if chart is not None:
        st.altair_chart(
            chart,
            alt="기업별 최근 3개 사업연도 매출액 막대 그래프(억원, 영업이익 흑자·적자 색 구분)",
        )
        st.caption(SCALE_NOTE)
    rows = company_financial_rows(financials)
    if rows:
        st.dataframe(rows, hide_index=True, width="stretch")
    for item in financials.missing:
        st.caption(f"재무 계정 없음: {item}")
    bases = [f"{c.company}: {c.rnd_basis}" for c in financials.companies if c.rnd_basis]
    if bases:
        st.caption("연구개발비 근거 · " + " / ".join(bases))
    if financials.note:
        st.caption(financials.note)
