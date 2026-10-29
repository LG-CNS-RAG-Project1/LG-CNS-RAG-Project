"""시장성 화면의 키워드 동시 출현 네트워크(MarketReport.keyword_network) 표시."""

import streamlit as st

from src.generation.market_markdown import keyword_network_summary

# 묶음 색은 순서대로 고정 배정한다 (dataviz 기준 팔레트 1~5번, 밝은·어두운 화면 각각 검증).
# 6번째 묶음부터는 '기타' 회색으로 접는다.
CLUSTER_COLORS = {
    "light": ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"],
    "dark": ["#3987e5", "#d95926", "#199e70", "#c98500", "#d55181"],
}
OTHER_COLOR = "#8a8984"
EDGE_COLOR = "#8a8984"
SURFACE = {"light": "#fcfcfb", "dark": "#1a1a19"}


def cluster_label(index: int, clusters: list[list[str]]) -> str:
    """묶음 범례 이름. 대표 명사 2개를 붙이고, 6번째 묶음부터는 '기타'."""
    if index >= len(CLUSTER_COLORS["light"]):
        return "기타"
    return f"묶음 {index + 1} · {'·'.join(clusters[index][:2])}"


def network_rows(network) -> tuple[list[dict], list[dict]]:
    """차트용 (명사 행, 연결 행). 연결 행은 양 끝 명사 좌표를 함께 담는다."""
    coords = {n.term: (n.x, n.y) for n in network.nodes}
    nodes = [
        {
            "명사": n.term,
            "기사 수": n.document_count,
            "묶음": cluster_label(n.cluster, network.clusters),
            "x": n.x,
            "y": n.y,
        }
        for n in network.nodes
    ]
    edges = [
        {
            "x": coords[e.source][0],
            "y": coords[e.source][1],
            "x2": coords[e.target][0],
            "y2": coords[e.target][1],
            "연결": f"{e.source} – {e.target}",
            "함께 나온 기사": e.weight,
        }
        for e in network.edges
        if e.source in coords and e.target in coords
    ]
    return nodes, edges


def _theme() -> str:
    try:
        return "dark" if st.context.theme.type == "dark" else "light"
    except Exception:  # 테마 정보를 읽을 수 없는 실행 환경
        return "light"


def network_chart(network, theme: str = "light"):
    """연결선(굵기 = 함께 나온 기사 수)·원(크기 = 기사 수, 색 = 묶음)·명사 이름을 겹친 Altair 차트."""
    import altair as alt
    import pandas as pd

    nodes, edges = network_rows(network)
    palette = CLUSTER_COLORS[theme]
    labels = [
        cluster_label(i, network.clusters)
        for i in range(min(len(network.clusters), len(palette) + 1))
    ]
    colors = [
        palette[i] if i < len(palette) else OTHER_COLOR for i in range(len(labels))
    ]
    axis = alt.Axis(labels=False, ticks=False, domain=False, grid=False, title=None)
    scale = alt.Scale(domain=[-1.15, 1.15], nice=False)
    lines = (
        alt.Chart(pd.DataFrame(edges))
        .mark_rule(color=EDGE_COLOR, opacity=0.35)
        .encode(
            x=alt.X("x:Q", axis=axis, scale=scale),
            y=alt.Y("y:Q", axis=axis, scale=scale),
            x2="x2:Q",
            y2="y2:Q",
            strokeWidth=alt.StrokeWidth(
                "함께 나온 기사:Q", scale=alt.Scale(range=[0.5, 4]), legend=None
            ),
            tooltip=["연결:N", "함께 나온 기사:Q"],
        )
    )
    base = alt.Chart(pd.DataFrame(nodes)).encode(
        x=alt.X("x:Q", axis=axis, scale=scale),
        y=alt.Y("y:Q", axis=axis, scale=scale),
    )
    dots = base.mark_circle(opacity=1, stroke=SURFACE[theme], strokeWidth=2).encode(
        size=alt.Size("기사 수:Q", scale=alt.Scale(range=[60, 500]), legend=None),
        color=alt.Color(
            "묶음:N",
            scale=alt.Scale(domain=labels, range=colors),
            legend=alt.Legend(orient="bottom", title=None, columns=2),
        ),
        tooltip=["명사:N", "기사 수:Q", "묶음:N"],
    )
    texts = base.mark_text(dy=-17, fontSize=12).encode(text="명사:N")
    return (lines + dots + texts).properties(height=440).configure_view(strokeWidth=0)


def render_keyword_network(network, widget_suffix: str = "") -> None:
    """키워드 동시 출현 네트워크를 요약·연결망 그림·묶음 목록·해석 주의 문구로 보여 준다.

    network가 없으면 표시하지 않는다. 같은 화면에 두 번 그릴 때 widget_suffix로 차트 key를 구분한다.
    """
    if network is None:
        return
    st.markdown("**키워드 동시 출현**")
    st.caption(keyword_network_summary(network))
    if network.status == "completed" and network.nodes:
        theme = _theme()
        st.altair_chart(
            network_chart(network, theme),
            key=f"market_keyword_network{widget_suffix}",
            width="stretch",
            alt="아이디어와 가까운 뉴스에서 함께 나온 명사의 연결망. 색은 키워드 묶음, 원 크기는 기사 수",
        )
        for i, group in enumerate(network.clusters[: len(CLUSTER_COLORS[theme])]):
            st.caption(f"묶음 {i + 1}: {' · '.join(group)}")
        if len(network.clusters) > len(CLUSTER_COLORS[theme]):
            rest = network.clusters[len(CLUSTER_COLORS[theme]) :]
            st.caption("기타: " + " · ".join(t for group in rest for t in group))
    if network.note:
        st.caption(network.note)
