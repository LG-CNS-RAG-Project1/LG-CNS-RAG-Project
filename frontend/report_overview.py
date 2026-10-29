"""파이프라인의 구조화된 판단·인용을 추가 모델 호출 없이 시각화한다."""

import streamlit as st
from pydantic import BaseModel, Field
from src.schemas import MarketKeywordNetwork, MarketSearchTrend

EVIDENCE_STATUS_LABELS = {
    "sufficient": "관련 자료 충분",
    "limited": "관련 자료 제한적",
    "insufficient": "관련 자료 부족",
    "no_results": "검색 결과 없음",
    "error": "판정 오류",
    "": "미제공",
}


def market_verification_markdown(market):
    """차원별 확인 한계를 문서에도 보존한다. 판정과 수치는 생성하지 않는다."""
    from src.generation.market_markdown import cell, VERDICT_LABELS, NATURE_LABELS
    from src.retrieval.market_relevance import DIMENSION_LABELS

    if not market.dimensions:
        return ""
    lines = [
        "\n\n## 시장 판단의 확인 범위",
        "",
        "| 항목 | 판단 | 자료 상태 | 관련 검색 자료 수 | 확인되지 않은 이유 | 다음 확인 |",
        "|---|---|---|---|---|---|",
    ]
    for d in market.dimensions:
        lines.append(
            "| "
            + " | ".join(
                cell(str(x))
                for x in [
                    DIMENSION_LABELS[d.dimension],
                    VERDICT_LABELS[d.verdict],
                    EVIDENCE_STATUS_LABELS.get(d.evidence_status or "", "미제공"),
                    d.relevant_count if d.relevant_count is not None else "미제공",
                    d.limitation or "미제공",
                    d.next_check or "미제공",
                ]
            )
            + " |"
        )
    lines += [
        "",
        "관련 검색 자료 수는 인용 건수와 다르며 미제공 값은 0이 아닙니다. 뉴스의 구매 신호는 고객의 직접 구매 의사 확인과 구분합니다.",
    ]
    if market.evidence:
        lines += ["", "### 인용 근거 성격"]
        lines += [
            f"- M:{e.citation_id} · {NATURE_LABELS.get(e.evidence_nature, e.evidence_nature)} · {cell(e.title)}"
            for e in market.evidence
        ]
    return "\n".join(lines)


class Finding(BaseModel):
    label: str
    judgment: str
    implication: str = ""
    kind: str = "미확인"
    citations: str = ""
    limitation: str = ""
    evidence_status: str = ""
    relevant_count: int | None = Field(default=None, ge=0)


class DartContextEvidence(BaseModel):
    evidence_id: str
    company: str
    period: str = ""
    section: str = ""
    title: str
    quote: str
    url: str = ""


class MarketContext(BaseModel):
    dart_evidence: list[DartContextEvidence] = Field(default_factory=list, max_length=3)
    search_trend: MarketSearchTrend | None = None
    keyword_network: MarketKeywordNetwork | None = None
    market_dimensions: list[Finding] = Field(default_factory=list, max_length=5)


class Dashboard(BaseModel):
    conclusion: str = ""
    summary: str = ""
    scope: str = ""
    confidence: str = ""
    findings: list[Finding] = Field(default_factory=list, max_length=30)
    domain_summaries: list[Finding] = Field(default_factory=list, max_length=2)
    dimensions: list[Finding] = Field(default_factory=list, max_length=10)
    actions: list[Finding] = Field(default_factory=list, max_length=20)
    unknowns: list[str] = Field(default_factory=list, max_length=100)
    market_context: MarketContext | None = None


def dashboard_data(result):
    """생성된 분석 값을 화면용 계약으로 투영하며 새 결론·수치를 만들지 않는다."""
    from src.generation.executive_review import (
        RECOMMENDATION_LABELS,
        cross_domain_findings,
        executive_next_checks,
        executive_limitations,
    )
    from src.retrieval.market_relevance import DIMENSION_LABELS

    executive = result.executive_review
    business = result.business_review
    verdicts = {
        "confirmed": "근거 확인",
        "signal_only": "신호만 확인",
        "unverified": "미확인",
    }
    kinds = {
        "fact": "사실",
        "interpretation": "해석",
        "hypothesis": "가설",
        "unknown": "미확인",
    }
    data = Dashboard()
    if executive:
        conclusions = cross_domain_findings(executive)
        data.conclusion = (
            RECOMMENDATION_LABELS.get(
                executive.recommendation, executive.recommendation
            )
            if conclusions
            else "추가 확인 후 결정"
        )
        data.summary = (
            executive.decision_summary
            if conclusions
            else "특허와 시장 양쪽 근거가 함께 확인될 때까지 통합 결론을 보류합니다."
        )
        data.confidence = {"low": "낮음", "medium": "보통", "high": "높음"}.get(
            executive.confidence, executive.confidence
        )
        data.findings = [
            Finding(
                label=x.label,
                judgment=x.judgment,
                implication=x.business_implication,
                kind=kinds[x.kind],
                citations=", ".join(x.evidence_ids),
            )
            for x in conclusions
        ]
        data.actions = [
            Finding(
                label=f"확인 {index}",
                judgment=action,
            )
            for index, action in enumerate(executive_next_checks(executive), 1)
        ]
        data.unknowns = executive_limitations(executive, limit=3)
    elif business:
        data.conclusion = RECOMMENDATION_LABELS.get(
            business.recommendation, business.recommendation
        )
        data.summary = business.summary
    if business and not executive:
        data.actions += [
            Finding(
                label=x.horizon,
                judgment=x.action,
                implication=f"대상: {x.target} · 확인 기준: {x.success_signal}",
                citations=", ".join(x.citation_ids),
            )
            for x in business.next_steps[:2]
        ]
        data.unknowns += business.unknowns[:2]
    for dimension in result.market.dimensions:
        data.dimensions.append(
            Finding(
                label=DIMENSION_LABELS[dimension.dimension],
                judgment=verdicts[dimension.verdict],
                implication=dimension.next_check or "",
                limitation=dimension.limitation or "",
                evidence_status=dimension.evidence_status or "",
                relevant_count=dimension.relevant_count,
                citations=", ".join(
                    f"M:{cid}"
                    for cid in sorted(
                        {
                            cid
                            for claim in dimension.claims
                            for cid in claim.citation_ids
                        }
                    )
                ),
            )
        )
    market = result.market
    dart_evidence = []
    seen_companies = set()
    for evidence in market.evidence:
        if evidence.source_type != "dart":
            continue
        company = evidence.publisher or "공시 기업 미제공"
        if company in seen_companies:
            continue
        seen_companies.add(company)
        dart_evidence.append(
            DartContextEvidence(
                evidence_id=f"M:{evidence.citation_id}",
                company=company,
                period=evidence.period or "사업연도 미제공",
                section=evidence.section or "원문 위치 미제공",
                title=evidence.title,
                quote=evidence.quote,
                url=evidence.url or "",
            )
        )
        if len(dart_evidence) >= 3:
            break
    if (
        dart_evidence
        or market.search_trend
        or market.keyword_network
        or market.dimensions
    ):
        data.market_context = MarketContext(
            dart_evidence=dart_evidence,
            search_trend=market.search_trend,
            keyword_network=market.keyword_network,
            market_dimensions=data.dimensions,
        )
    data.unknowns = list(dict.fromkeys(data.unknowns))[:3]
    return data.model_dump()


def _render_market_context(context: MarketContext) -> None:
    """실제 시장 계약에 있는 참고 맥락만 작은 카드로 표시한다."""
    status_labels = {
        "sufficient": "관련 근거 충분",
        "limited": "관련 근거 제한적",
        "insufficient": "관련 근거 부족",
        "no_results": "검색 결과 없음",
        "error": "판정 오류",
        "": "상태 미제공",
    }
    verdict_labels = {
        "confirmed": "확인됨",
        "signal_only": "신호만 확인",
        "unverified": "미확인",
    }
    if context.market_dimensions:
        st.markdown("#### 차원별 근거 상태")
        for dimension in context.market_dimensions:
            count = (
                f" · 관련 자료 {dimension.relevant_count}건"
                if dimension.relevant_count is not None
                else ""
            )
            st.markdown(
                f"- **{dimension.label}:** {dimension.judgment} · "
                f"{status_labels.get(dimension.evidence_status, '상태 미제공')}{count}"
            )
            if dimension.limitation or dimension.implication:
                parts = [
                    value
                    for value in (dimension.limitation, dimension.implication)
                    if value
                ]
                st.caption(" · ".join(parts))

    if context.dart_evidence:
        st.markdown("#### DART 기업 공시 맥락")
        st.caption(
            "기업 자체 사업 설명입니다. 시장 전체 수요나 특허 출원인과의 동일성을 입증하지 않습니다."
        )
        for evidence in context.dart_evidence:
            with st.container(border=True):
                st.markdown(f"**{evidence.evidence_id} · {evidence.company}**")
                st.caption(f"{evidence.period} · {evidence.section} · 기업 공시")
                st.write(evidence.title)
                excerpt = evidence.quote
                if len(excerpt) > 420:
                    excerpt = excerpt[:420].rstrip() + "…"
                st.write(excerpt)
                if evidence.url.startswith(("https://", "http://")):
                    st.link_button("공시 원문 열기 ↗", evidence.url)
        st.caption(
            "현재 특허 데이터에는 출원인 정보가 보존되지 않아 기업·특허 관계는 미확인입니다."
        )

    trend = context.search_trend
    if trend:
        st.markdown("#### 검색 관심도 흐름")
        keywords = ", ".join(trend.keywords) or "주제어 미제공"
        reference = ", ".join(trend.reference_keywords) or "기준어 미제공"
        if trend.status == "completed":
            if trend.recent_change_pct is not None:
                st.caption(
                    f"{keywords} · 기준: {reference} · 최근 6개월 변화 "
                    f"{trend.recent_change_pct:+.1f}%"
                )
            else:
                st.caption(f"{keywords} · 기준: {reference} · 변화율 미제공")
            points = [
                {"월": point.period, "기준 대비 지수": point.relative_index}
                for point in trend.points
                if point.relative_index is not None
            ]
            if points:
                import altair as alt
                import pandas as pd

                chart = (
                    alt.Chart(pd.DataFrame(points))
                    .mark_line(point=True)
                    .encode(
                        x=alt.X("월:N", title=None, sort=None),
                        y=alt.Y("기준 대비 지수:Q", title="기준 대비 지수"),
                        tooltip=["월", "기준 대비 지수"],
                    )
                    .properties(height=190)
                )
                st.altair_chart(
                    chart,
                    width="stretch",
                    alt="기준 검색어 대비 월별 상대 검색 관심도",
                )
            else:
                st.info("표시할 월별 상대 지수가 없습니다.")
        elif trend.status == "insufficient_volume":
            st.info("검색량이 적어 관심도 흐름을 판단하지 않습니다.")
        else:
            st.warning("검색 관심도 자료를 불러오지 못했습니다.")
        if trend.note:
            st.caption(trend.note)
        st.caption("상대 검색 관심도이며 시장 규모·고객 수요의 근거가 아닙니다.")

    network = context.keyword_network
    if network:
        st.markdown("#### 키워드 동시 출현 네트워크")
        if network.status == "completed" and network.nodes:
            import altair as alt
            import pandas as pd

            palette = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4"]
            node_rows = [
                {
                    "명사": node.term,
                    "기사 수": node.document_count,
                    "묶음": f"묶음 {node.cluster + 1}",
                    "색": (
                        palette[node.cluster]
                        if node.cluster < len(palette)
                        else "#8a8984"
                    ),
                    "x": node.x,
                    "y": node.y,
                }
                for node in network.nodes
            ]
            coords = {row["명사"]: (row["x"], row["y"]) for row in node_rows}
            edge_rows = [
                {
                    "x": coords[edge.source][0],
                    "y": coords[edge.source][1],
                    "x2": coords[edge.target][0],
                    "y2": coords[edge.target][1],
                    "연결": f"{edge.source} – {edge.target}",
                    "함께 나온 기사": edge.weight,
                }
                for edge in network.edges
                if edge.source in coords and edge.target in coords
            ]
            axis = alt.Axis(
                labels=False, ticks=False, domain=False, grid=False, title=None
            )
            scale = alt.Scale(domain=[-1.15, 1.15], nice=False)
            node_data = pd.DataFrame(node_rows)
            base = alt.Chart(node_data).encode(
                x=alt.X("x:Q", axis=axis, scale=scale),
                y=alt.Y("y:Q", axis=axis, scale=scale),
            )
            dots = base.mark_circle(stroke="white", strokeWidth=1.5).encode(
                size=alt.Size(
                    "기사 수:Q", scale=alt.Scale(range=[60, 400]), legend=None
                ),
                color=alt.Color("색:N", scale=None, legend=None),
                tooltip=["명사:N", "기사 수:Q", "묶음:N"],
            )
            texts = base.mark_text(dy=-13, fontSize=10).encode(text="명사:N")
            chart = dots + texts
            if edge_rows:
                edges = (
                    alt.Chart(pd.DataFrame(edge_rows))
                    .mark_rule(color="#8a8984", opacity=0.32)
                    .encode(
                        x=alt.X("x:Q", axis=axis, scale=scale),
                        y=alt.Y("y:Q", axis=axis, scale=scale),
                        x2="x2:Q",
                        y2="y2:Q",
                        strokeWidth=alt.StrokeWidth(
                            "함께 나온 기사:Q",
                            scale=alt.Scale(range=[0.5, 3]),
                            legend=None,
                        ),
                        tooltip=["연결:N", "함께 나온 기사:Q"],
                    )
                )
                chart = edges + chart
            st.altair_chart(
                chart.properties(height=280).configure_view(strokeWidth=0),
                width="stretch",
                alt="같은 뉴스에서 함께 언급된 키워드 네트워크",
            )
            for index, cluster in enumerate(network.clusters[:3], 1):
                st.caption(f"묶음 {index}: {' · '.join(cluster[:5])}")
        elif network.status == "insufficient":
            st.info(network.note or "연결망을 구성할 뉴스나 연결이 부족합니다.")
        else:
            st.warning("키워드 동시 출현 네트워크를 생성하지 못했습니다.")
        st.caption(
            f"뉴스 {network.document_count}건의 제목·요약에서 함께 등장한 주제입니다. "
            "수요·인과·소비자 세그먼트의 근거가 아닙니다."
        )
        if network.note:
            st.caption(network.note)


def render_dashboard(raw):
    data = Dashboard.model_validate(raw)
    if data.conclusion:
        st.subheader("종합 결론")
        st.markdown(f"**{data.conclusion}**")
        st.write(data.summary)
    if data.findings:
        st.subheader("양쪽 근거로 연결된 판단")
        for finding in data.findings[:2]:
            st.markdown(f"**{finding.label}**")
            st.write(finding.judgment)
            if finding.implication:
                st.caption(finding.implication)
            st.caption(f"특허·시장 근거: {finding.citations}")
    if data.actions:
        st.subheader("다음 확인")
        for action in data.actions[:2]:
            st.write(f"- {action.judgment}")
    if data.unknowns:
        with st.expander("판단 한계"):
            for value in data.unknowns:
                st.write(f"- {value}")
    if data.market_context:
        with st.expander("시장 맥락 · 참고 자료", expanded=False):
            _render_market_context(data.market_context)
    if not any((data.conclusion, data.findings, data.actions)):
        st.info(
            "구조화된 최종 판단이 아직 제공되지 않았습니다. 원문과 근거를 확인해 주세요."
        )
