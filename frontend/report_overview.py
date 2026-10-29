"""파이프라인의 구조화된 판단·인용을 추가 모델 호출 없이 시각화한다."""

from collections import Counter

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
    from src.generation.executive_review import RECOMMENDATION_LABELS
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
        data.conclusion = RECOMMENDATION_LABELS.get(
            executive.recommendation, executive.recommendation
        )
        data.summary = executive.decision_summary
        data.scope = executive.scope
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
            for x in executive.integrated_findings[:30]
        ]
        data.domain_summaries = [
            Finding(
                label="특허" if x.domain == "patent" else "시장",
                judgment=x.finding,
                implication=(
                    f"범위: {x.evidence_scope} · 자료 {x.evidence_count}건"
                    + (f" · 기준일 {x.data_as_of}" if x.data_as_of else "")
                    + (
                        f" · 다음 확인: {'; '.join(x.next_check[:2])}"
                        if x.next_check
                        else ""
                    )
                ),
                kind={
                    "completed": "완료",
                    "partial": "부분 완료",
                    "no_results": "근거 없음",
                    "error": "실패",
                    "skipped": "미실행",
                    "timeout": "시간 초과",
                }[x.status],
                citations=", ".join(x.evidence_ids),
                limitation="; ".join(x.limitations[:2]),
            )
            for x in executive.domain_summaries
        ]
        data.actions = [
            Finding(
                label=x.question,
                judgment=x.proof_needed,
                implication=x.consequence,
                kind=x.owner,
                citations=", ".join(x.evidence_ids),
            )
            for x in executive.approval_gates
        ]
        data.unknowns = list(executive.limitations)
    elif business:
        data.conclusion = RECOMMENDATION_LABELS.get(
            business.recommendation, business.recommendation
        )
        data.summary = business.summary
    if business:
        data.actions += [
            Finding(
                label=x.horizon,
                judgment=x.action,
                implication=f"대상: {x.target} · 확인 기준: {x.success_signal}",
                citations=", ".join(x.citation_ids),
            )
            for x in business.next_steps[:10]
        ]
        data.unknowns += business.unknowns
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
    data.unknowns = list(
        dict.fromkeys(data.unknowns + result.market.unknowns + result.patent.unknowns)
    )[:100]
    return data.model_dump()


def render_dashboard(raw):
    data = Dashboard.model_validate(raw)
    if data.conclusion:
        st.subheader(data.conclusion)
        st.write(data.summary)
        if data.scope:
            st.info(data.scope)
        if data.confidence:
            st.caption(
                f"분석의 확신 수준: {data.confidence} · 생성된 검토 결과의 판단이며 성공 확률이 아닙니다."
            )
    if data.domain_summaries:
        st.subheader("특허·시장 영역별 근거")
        for column, summary in zip(
            st.columns(len(data.domain_summaries)), data.domain_summaries
        ):
            with column.container(border=True):
                st.caption(summary.kind)
                st.markdown(f"**{summary.label}**")
                st.write(summary.judgment)
                st.caption(summary.implication)
                if summary.limitation:
                    st.caption(f"한계: {summary.limitation}")
                st.caption(f"근거: {summary.citations or '인용 근거 없음'}")
    if data.findings:
        st.subheader("특허 × 시장 · 연결된 판단")
        for column, finding in zip(
            st.columns(min(3, len(data.findings))), data.findings[:3]
        ):
            with column.container(border=True):
                st.caption(finding.kind)
                st.markdown(f"**{finding.label}**")
                st.write(finding.judgment)
                st.caption(finding.implication)
                st.caption(f"근거: {finding.citations or '미확인'}")
        with st.expander("연결 판단과 인용 전체 보기"):
            st.dataframe(
                [
                    {
                        "항목": x.label,
                        "구분": x.kind,
                        "판단": x.judgment,
                        "사업 검토 의미": x.implication,
                        "인용": x.citations or "없음",
                    }
                    for x in data.findings
                ],
                hide_index=True,
                width="stretch",
            )
    if data.dimensions:
        st.subheader("시장 검토 · 어디까지 확인됐나요?")
        chart, table = st.columns([1, 2])
        counts = Counter(x.judgment for x in data.dimensions)
        with chart:
            st.bar_chart(
                [
                    {"판단 상태": state, "항목 수": counts[state]}
                    for state in ["근거 확인", "신호만 확인", "미확인"]
                ],
                x="판단 상태",
                y="항목 수",
                horizontal=True,
                height=220,
                color="#19796f",
            )
            st.caption(
                "분석 항목의 상태 분포입니다. 시장 규모·수요량·사업성 점수가 아닙니다. 미제공 항목은 집계하지 않습니다."
            )
        with table:
            st.dataframe(
                [
                    {
                        "검토 항목": x.label,
                        "판단": x.judgment,
                        "근거": x.citations or "없음",
                        "확인되지 않은 이유": x.limitation or "미제공",
                        "자료 상태": EVIDENCE_STATUS_LABELS.get(
                            x.evidence_status, "미제공"
                        ),
                        "관련 검색 자료 수": x.relevant_count,
                        "다음 확인": x.implication,
                    }
                    for x in data.dimensions
                ],
                hide_index=True,
                width="stretch",
                height=220,
            )
            st.caption(
                "관련 검색 자료 수는 인용 건수와 다릅니다. 미제공 값은 0으로 채우지 않습니다."
            )
    if data.actions:
        st.subheader("다음 행동 · 결정 전에 확인할 것")
        selected = st.selectbox(
            "검증 과제",
            range(len(data.actions)),
            format_func=lambda i: f"{i+1}. {data.actions[i].label}",
        )
        action = data.actions[selected]
        with st.container(border=True):
            st.write(action.judgment)
            st.caption(action.implication)
            st.caption(f"근거: {action.citations or '추가 확보 필요'}")
    if data.unknowns:
        with st.expander(f"미확인 사항·한계 {len(data.unknowns)}개"):
            for value in data.unknowns:
                st.write(f"- {value}")
    if not any((data.conclusion, data.findings, data.dimensions, data.actions)):
        st.info(
            "구조화된 최종 판단이 아직 제공되지 않았습니다. 원문과 근거를 확인해 주세요."
        )
