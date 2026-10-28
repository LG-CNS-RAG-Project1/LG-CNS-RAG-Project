"""특허와 시장의 상호작용을 사업 의사결정으로 바꾸는 최종 검토 보고서."""

from typing import Literal

from pydantic import BaseModel, Field

from src.generation.business_review import BusinessReview
from src.generation.report_builder import escape_md
from src.schemas import IdeaDraft, MarketReport, PatentReport


class IntegratedFinding(BaseModel):
    label: str
    judgment: str
    business_implication: str
    evidence_ids: list[str] = Field(default_factory=list)
    kind: Literal["fact", "interpretation", "hypothesis", "unknown"]


class ApprovalGate(BaseModel):
    question: str
    owner: str
    proof_needed: str
    consequence: str
    evidence_ids: list[str] = Field(default_factory=list)


class ExecutiveReview(BaseModel):
    recommendation: str
    scope: str
    confidence: str
    decision_summary: str
    integrated_findings: list[IntegratedFinding] = Field(default_factory=list)
    approval_gates: list[ApprovalGate] = Field(default_factory=list, max_length=3)
    next_actions: list[str] = Field(default_factory=list, max_length=3)
    limitations: list[str] = Field(default_factory=list)


RECOMMENDATION_LABELS = {
    "validate_demand": "조건부 진행",
    "limited_pilot": "제한 파일럿 검토",
    "research_more": "추가 확인 후 결정",
    "hold_redesign": "보류·재설계",
}
SCOPE_LABELS = {
    "validate_demand": "고객 조사와 구매 조건 확인까지만 진행합니다. 대규모 개발·투자는 보류합니다.",
    "limited_pilot": "특허·운영 조건을 확인한 뒤 단일 고객·공정 범위의 파일럿을 준비합니다.",
    "research_more": "미확인 항목을 먼저 확인하고, 그 전까지 제품화 투자는 보류합니다.",
    "hold_redesign": "현재 구성의 제품화는 보류하고, 특허 대응 구성과 대체 설계를 먼저 검토합니다.",
}


def _refs(values: list[str | int]) -> list[str]:
    return list(dict.fromkeys(str(value) for value in values))


def build_executive_review(
    draft: IdeaDraft,
    patent: PatentReport,
    market: MarketReport,
    business: BusinessReview,
) -> ExecutiveReview:
    """두 분석의 결합 결과, 승인 전 게이트와 순서가 있는 다음 결정을 만든다."""
    precheck = patent.patentability_precheck
    market_review = market.opportunity_review
    direct_demand = any(
        item.source_type == "customer_validation"
        and item.evidence_nature == "direct_demand"
        for item in market.evidence
    )
    buyer_ids = []
    barrier_ids = []
    buyer_dimension = next((item for item in market.dimensions if item.dimension == "buyer"), None)
    barrier_dimension = next(
        (item for item in market.dimensions if item.dimension == "adoption_barrier"), None
    )
    if buyer_dimension:
        buyer_ids = [cid for claim in buyer_dimension.claims for cid in claim.citation_ids]
    if barrier_dimension:
        barrier_ids = [cid for claim in barrier_dimension.claims for cid in claim.citation_ids]

    findings: list[IntegratedFinding] = []
    if precheck:
        patent_refs = [f"P:{cid}" for cid in precheck.citation_ids]
        findings.append(
            IntegratedFinding(
                label="기술 권리 범위",
                judgment=precheck.summary,
                business_implication=(
                    "제품 기능 범위와 차별 구성을 먼저 좁혀 전문가 검토를 받습니다."
                    if precheck.status == "overlap_concern"
                    else "예비 신호만으로 독점성이나 등록 가능성을 가정하지 않고 청구항 단위로 확인합니다."
                ),
                evidence_ids=_refs(patent_refs),
                kind="interpretation",
            )
        )
    else:
        findings.append(
            IntegratedFinding(
                label="기술 권리 범위",
                judgment="구성요소별 특허 예비 검토 결과가 없어 권리 위험과 차별점을 판단할 수 없습니다.",
                business_implication="제품화 투자 전에 관련 청구항과 추가 검색 범위를 확인합니다.",
                kind="unknown",
            )
        )

    if market_review:
        market_refs = [f"M:{cid}" for reason in market_review.reasons for cid in reason.citation_ids]
        cited_patent_refs = (
            [f"P:{cid}" for cid in precheck.citation_ids]
            if precheck and precheck.citation_ids
            else []
        )
        market_label = {
            "validated_demand": "직접 고객 검증 자료가 제출되었습니다.",
            "buyer_signals": "구매자 관련 공개 신호가 확인되었으나 직접 구매 검증은 아닙니다.",
            "indirect_signals": "산업·기업 신호만 확인되어 구매 의사는 미검증입니다.",
            "insufficient_evidence": "아이디어별 시장 판단에 충분한 자료가 없습니다.",
        }[market_review.status]
        if precheck and precheck.status == "overlap_concern" and cited_patent_refs:
            market_implication = (
                "시장 신호가 있어도 유사 청구항 우려를 낮추지는 않습니다. "
                "해당 청구항을 전문가와 대조하기 전까지 제품 기능 투자를 보류하고, "
                "구매자·예산 확인 전에는 시장 신호를 매출 전망으로 바꾸지 않습니다."
            )
        elif precheck and precheck.status == "potentially_distinct" and cited_patent_refs:
            market_implication = (
                "예비 차별 신호는 구매 증거가 아닙니다. 구매자·예산·도입 조건을 확인한 뒤 "
                "제한 파일럿을 판단합니다."
            )
        elif not direct_demand:
            market_implication = (
                "구매자·예산 주체·도입 조건을 확인하기 전에는 수요 신호를 매출 전망으로 바꾸지 않습니다."
            )
        else:
            market_implication = (
                "제출된 고객 검증의 표본·구매 권한·실제 지불 조건을 확인한 뒤 제한 파일럿 여부를 결정합니다."
            )
        findings.append(
            IntegratedFinding(
                label="시장 진입 근거",
                judgment=market_label,
                business_implication=market_implication,
                evidence_ids=_refs(market_refs + cited_patent_refs),
                kind="fact" if direct_demand else "interpretation",
            )
        )
    else:
        findings.append(
            IntegratedFinding(
                label="시장 진입 근거",
                judgment="시장 검토 결과가 없어 목표 고객의 수요와 구매 조건을 판단할 수 없습니다.",
                business_implication="시장 근거를 보완하기 전까지 매출·도입 가능성을 승인 근거로 쓰지 않습니다.",
                kind="unknown",
            )
        )

    if barrier_dimension and barrier_dimension.claims:
        claim = barrier_dimension.claims[0]
        findings.append(
            IntegratedFinding(
                label="도입 실행성",
                judgment=claim.statement,
                business_implication="파일럿 범위·일정·비용 산정에 이 장벽의 해소 조건을 반영합니다.",
                evidence_ids=_refs([f"M:{cid}" for cid in claim.citation_ids]),
                kind="fact" if claim.claim_type == "fact" else "hypothesis",
            )
        )
    elif draft.current_alternative:
        findings.append(
            IntegratedFinding(
                label="전환 과제",
                judgment=f"현재 대안은 아이디어 입력 기준 ‘{draft.current_alternative}’입니다. 대안 대비 전환 이유와 전환 비용은 검증되지 않았습니다.",
                business_implication="현재 대안을 유지할 때와 제안 제품을 도입할 때의 비용·작업 차이를 고객과 비교합니다.",
                kind="unknown",
            )
        )

    gates: list[ApprovalGate] = []
    if patent.status != "completed" or not precheck or precheck.status != "potentially_distinct":
        gates.append(
            ApprovalGate(
                question="주요 기능이 선행 특허 청구항과 어떻게 구분되는가?",
                owner="변리사 또는 특허 전문가",
                proof_needed="우선 확인할 독립 청구항, 구성 대응표, 추가 검색 범위에 대한 서면 검토",
                consequence="미확인 상태에서는 해당 기능의 제품화·권리 확보 일정을 확정하지 않습니다.",
                evidence_ids=_refs([f"P:{cid}" for cid in (precheck.citation_ids if precheck else [])]),
            )
        )
    if not direct_demand:
        gates.append(
            ApprovalGate(
                question="목표 고객이 이 문제를 해결하기 위해 실제 예산과 구매 절차를 제공하는가?",
                owner="사업기획·고객개발 담당자",
                proof_needed="사용자·구매결정자·예산 주체 인터뷰와 현재 대안·구매조건 기록",
                consequence="직접 수요 확인 전에는 시장 신호를 매출 예측이나 투자 승인 근거로 사용하지 않습니다.",
                evidence_ids=_refs([f"M:{cid}" for cid in buyer_ids]),
            )
        )
    if (not draft.revenue or not draft.current_alternative or barrier_dimension is None) and len(gates) < 3:
        gates.append(
            ApprovalGate(
                question="현재 대안보다 도입 가치가 크고 운영·예산 장벽을 감당할 수 있는가?",
                owner="제품기획·현장 운영 담당자",
                proof_needed="현행 비용 기준선, 설치·보안·운영 조건, 가격 또는 과금 가설 확인",
                consequence="ROI와 도입 범위가 확인되지 않으면 파일럿 비용·성공 기준을 승인하지 않습니다.",
                evidence_ids=_refs([f"M:{cid}" for cid in barrier_ids]),
            )
        )

    actions = []
    if not direct_demand:
        actions.append("1. 고객개발 담당자: 초기 세그먼트 후보와 인터뷰해 문제 빈도·현재 대안·구매결정자·예산 경로를 확인하고, 확인된 사례와 미확인을 분리 기록합니다.")
    if patent.status != "completed" or not precheck or precheck.status == "overlap_concern":
        actions.append("2. 특허 담당자: 우선순위가 높은 문헌의 독립 청구항과 실제 제품 기능을 변리사와 대조하고, 회피 설계·추가 조사 필요성을 문서화합니다.")
    if len(actions) < 3:
        actions.append("3. 제품·사업 담당자: 고객이 현재 대안과 제안 방식의 기준선·도입 조건을 합의한 뒤, 단일 고객·업무 범위의 파일럿 통과 기준과 중단 조건을 정합니다.")

    if business.recommendation == "limited_pilot" and not direct_demand:
        recommendation = "validate_demand"
    else:
        recommendation = business.recommendation
    confidence = (
        "낮음"
        if market.status in {"error", "no_results"} or patent.status in {"error", "no_results"}
        else {"low": "낮음", "medium": "보통", "high": "높음"}[business.confidence]
    )
    limitations = []
    if not direct_demand:
        limitations.append("직접 고객 구매·지불 검증 자료가 없어 지불 의사는 미확인입니다.")
    if patent.status != "completed":
        limitations.append("특허 조사가 완료되지 않아 검색 범위 밖 문헌을 포함한 권리 판단은 불가능합니다.")
    limitations.append("이 문서는 사업 검토용 예비 권고이며 법률 의견·시장 규모 산정·성공 예측이 아닙니다.")

    return ExecutiveReview(
        recommendation=recommendation,
        scope=SCOPE_LABELS[recommendation],
        confidence=confidence,
        decision_summary=(
            "현재는 시장 진입 투자 승인보다 구매자·예산 검증과 특허 범위 확인을 우선할 단계입니다."
            if recommendation in {"validate_demand", "research_more"}
            else business.summary
        ),
        integrated_findings=findings[:3],
        approval_gates=gates[:3],
        next_actions=actions[:3],
        limitations=limitations[:3],
    )


def executive_report_markdown(
    title: str, review: ExecutiveReview, *, analyzed_on: int | None = None
) -> str:
    """독립된 최종 실행 검토 문서. 근거 원문은 영역별 상세 화면에 둔다."""
    from datetime import datetime

    date_label = (
        datetime.strptime(str(analyzed_on), "%Y%m%d").strftime("%Y-%m-%d")
        if analyzed_on
        else datetime.now().strftime("%Y-%m-%d")
    )

    def refs(ids):
        return f" ({', '.join(ids)})" if ids else " (근거 없음·미확인)"

    lines = [
        f"# 최종 실행 검토 | {escape_md(title) or '아이디어'}",
        "",
        f"> 검토일 {date_label} · 신뢰도 {escape_md(review.confidence)} · 근거는 각 단계의 상세 화면에서 확인",
        "",
        "## 의사결정 요약",
        "",
        f"- **권고: {RECOMMENDATION_LABELS[review.recommendation]}**",
        f"- **진행 범위:** {escape_md(review.scope)}",
        f"- **판단:** {escape_md(review.decision_summary)}",
        "",
        "## 기회와 제약을 함께 본 판단",
        "",
    ]
    for finding in review.integrated_findings:
        lines += [
            f"- **{escape_md(finding.label)} · {finding.kind}:** {escape_md(finding.judgment)}{refs(finding.evidence_ids)} 사업상 의미: {escape_md(finding.business_implication)}",
            "",
        ]
    lines += ["## 승인 전에 통과할 확인사항", ""]
    for index, gate in enumerate(review.approval_gates, 1):
        lines += [
            f"{index}. **{escape_md(gate.question)}**{refs(gate.evidence_ids)}",
            f"   - 담당: {escape_md(gate.owner)} · 확인: {escape_md(gate.proof_needed)} · 미확인 시: {escape_md(gate.consequence)}",
        ]
    lines += ["", "## 다음 실행 순서", ""]
    lines.extend(f"- {escape_md(item)}" for item in review.next_actions)
    lines += ["", "## 판단 한계", ""]
    lines.extend(f"- {escape_md(item)}" for item in review.limitations)
    lines += ["", "> 권고는 다음 검증 단계의 선택을 돕기 위한 것이며 사업 성공·투자·특허 등록을 보장하지 않습니다.", ""]
    return "\n".join(lines)
