"""기존 시장 분석을 짧은 읽기 순서로 정리하며 새 결론은 생성하지 않는다."""

import streamlit as st


def grounded_review_result(result):
    """원문이 모두 연결된 판단만 요약에 사용하며 원본 분석은 보존한다."""
    review = result.executive_review
    if review is None:
        return result, 0
    available = {
        f"{prefix}:{item.citation_id}"
        for prefix, evidence in (
            ("P", result.patent.evidence),
            ("M", result.market.evidence),
        )
        for item in evidence
        if item.quote.strip()
    }
    supported = [
        finding
        for finding in review.integrated_findings
        if finding.kind == "unknown"
        or (finding.evidence_ids and set(finding.evidence_ids) <= available)
    ]
    hidden = len(review.integrated_findings) - len(supported)
    safe_review = review.model_copy(update={"integrated_findings": supported})
    return result.model_copy(update={"executive_review": safe_review}), hidden


def market_brief(market):
    labels = {
        "validated_demand": "고객 검증 자료가 있습니다. 표본과 실제 구매 조건을 확인하세요.",
        "buyer_signals": "구매자 관련 신호가 있지만, 이 아이디어의 구매 의사는 아직 확인되지 않았습니다.",
        "indirect_signals": "관련 산업의 움직임은 보이지만, 실제 고객 수요가 확인된 단계는 아닙니다.",
        "insufficient_evidence": "지금 자료만으로 이 아이디어의 시장성을 판단하기 어렵습니다.",
    }
    review = getattr(market, "opportunity_review", None)
    summary = (
        labels.get(review.status, "시장 판단 결과가 제공되지 않았습니다.")
        if review
        else "시장 판단 결과가 제공되지 않았습니다."
    )
    if market.status in {"error", "no_results"}:
        summary = "조사 결과가 충분하지 않습니다. 수요가 없다는 뜻은 아닙니다."
    evidence_ids = {item.citation_id for item in market.evidence if item.quote.strip()}
    facts, checks = [], []
    for dimension in market.dimensions:
        for claim in dimension.claims:
            refs = [cid for cid in claim.citation_ids if cid in evidence_ids]
            if (
                claim.claim_type == "fact"
                and refs
                and set(claim.citation_ids) <= evidence_ids
            ):
                facts.append(
                    {
                        "text": claim.statement,
                        "refs": refs,
                        "dimension": dimension.dimension,
                    }
                )
        if dimension.next_check:
            checks.append(dimension.next_check)
    return {
        "summary": summary,
        "facts": facts[:3],
        "checks": list(dict.fromkeys(checks))[:3],
        "unknowns": list(market.unknowns)[:3],
    }


def render_market_brief(market):
    brief = market_brief(market)
    st.subheader("그래서, 이 아이디어에 어떤 의미인가요?")
    st.info(brief["summary"])
    left, right = st.columns(2)
    with left.container(border=True):
        st.markdown("**자료에서 확인한 핵심**")
        for fact in brief["facts"]:
            st.write(fact["text"])
            st.caption("근거: " + ", ".join(f"M:{cid}" for cid in fact["refs"]))
        if not brief["facts"]:
            st.write("원문 인용으로 확인된 핵심 문장이 없습니다.")
    with right.container(border=True):
        st.markdown("**다음에 확인할 것**")
        for check in brief["checks"]:
            st.write("• " + check)
        if not brief["checks"]:
            st.write("다음 검증 과제가 제공되지 않았습니다.")
        if brief["unknowns"]:
            st.caption("아직 모르는 점: " + " · ".join(brief["unknowns"]))
    st.caption(
        "기존 분석의 자료 사실만 추려 표시했습니다. 주가·검색량·산업 뉴스는 우리 제품의 판매량이나 구매 의사와 다릅니다. 상세 문장과 그래프는 아래에서 확인하세요."
    )
