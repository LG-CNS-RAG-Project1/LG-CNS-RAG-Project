"""파이프라인의 구조화된 판단·인용을 추가 모델 호출 없이 시각화한다."""

import streamlit as st
from pydantic import BaseModel, Field

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


def dashboard_data(result):
    """생성된 분석 값을 화면용 계약으로 투영하며 새 결론·수치를 만들지 않는다."""
    from src.generation.executive_review import (
        RECOMMENDATION_LABELS,
        cross_domain_findings,
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
            for index, action in enumerate(executive.next_actions[:2], 1)
        ]
        data.unknowns = list(executive.limitations[:2])
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
    data.unknowns = list(dict.fromkeys(data.unknowns))[:3]
    return data.model_dump()


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
    if not any((data.conclusion, data.findings, data.actions)):
        st.info(
            "구조화된 최종 판단이 아직 제공되지 않았습니다. 원문과 근거를 확인해 주세요."
        )
