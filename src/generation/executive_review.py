"""특허와 시장의 상호작용을 사업 의사결정으로 바꾸는 최종 검토 보고서."""

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field, model_validator

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


class DomainEvidenceSummary(BaseModel):
    """영역별 원본 보고서를 공통 형식으로 보여주는 읽기 전용 요약."""

    domain: Literal["patent", "market"]
    status: Literal["completed", "partial", "no_results", "error", "skipped", "timeout"]
    finding: str
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_scope: str
    evidence_count: int = Field(default=0, ge=0)
    data_as_of: str | None = None
    limitations: list[str] = Field(default_factory=list)
    next_check: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence_ids(self):
        prefix = "P:" if self.domain == "patent" else "M:"
        if any(not value.startswith(prefix) for value in self.evidence_ids):
            raise ValueError(f"{self.domain} summary has a foreign evidence ID")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Domain evidence IDs must be unique")
        return self


class ExecutiveReview(BaseModel):
    recommendation: str
    scope: str
    confidence: str
    decision_summary: str
    domain_summaries: list[DomainEvidenceSummary] = Field(
        default_factory=list, max_length=2
    )
    integrated_findings: list[IntegratedFinding] = Field(default_factory=list)
    approval_gates: list[ApprovalGate] = Field(default_factory=list, max_length=3)
    next_actions: list[str] = Field(default_factory=list, max_length=3)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_domain_summaries(self):
        domains = [summary.domain for summary in self.domain_summaries]
        if len(domains) != len(set(domains)):
            raise ValueError("Executive review has duplicate domain summaries")
        return self


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


def _unique_text(values: list[str], limit: int = 3) -> list[str]:
    return list(dict.fromkeys(" ".join(value.split()) for value in values if value))[
        :limit
    ]


def _patent_domain_summary(
    patent: PatentReport, run_state: str | None = None
) -> DomainEvidenceSummary:
    precheck = patent.patentability_precheck
    references = _refs([f"P:{item.citation_id}" for item in patent.evidence])
    document_count = len({item.patent_id for item in patent.evidence})
    status = run_state or patent.status
    if status == "skipped":
        finding = "특허 조사를 실행하지 않았습니다."
    elif status == "timeout":
        finding = "특허 조사 제한 시간이 지나 완료되지 않았습니다."
    elif status == "error":
        finding = "특허 조사가 완료되지 않아 비교 결론을 제시할 수 없습니다."
    elif patent.status == "no_results":
        finding = "현재 검색 범위에서 비교 근거를 확보하지 못했습니다. 특허 위험이 없다는 뜻은 아닙니다."
    elif patent.status == "partial":
        finding = "특허 원문 일부는 확보했지만 비교 분석이 완료되지 않았습니다."
    elif precheck and precheck.citation_ids:
        finding = precheck.summary
    elif patent.evidence:
        finding = (
            "특허 근거는 확보했으나 인용으로 뒷받침되는 종합 예비 판단은 없습니다."
        )
    else:
        finding = "인용 가능한 특허 비교 결과가 없습니다."

    limitations = _unique_text(patent.unknowns)
    limitations = _unique_text(
        limitations + ["검색 결과는 특허성·침해·실시 자유에 대한 법률 판단이 아닙니다."]
    )
    expert_questions = precheck.expert_questions if precheck else []
    next_checks = expert_questions or patent.unknowns
    if not next_checks and patent.status == "no_results":
        next_checks = [
            "검색어와 특허 수집 범위를 확인하고 추가 검색 필요성을 검토합니다."
        ]
    return DomainEvidenceSummary(
        domain="patent",
        status=status,
        finding=finding,
        evidence_ids=references,
        evidence_scope=(
            f"{patent.search_scope} · 비교 문헌 {document_count}건 · 인용 근거 {len(patent.evidence)}건"
        ),
        evidence_count=len(patent.evidence),
        limitations=limitations,
        next_check=_unique_text(next_checks),
    )


def _market_domain_summary(
    market: MarketReport, run_state: str | None = None
) -> DomainEvidenceSummary:
    review = market.opportunity_review
    status_labels = {
        "validated_demand": "직접 고객 검증 자료가 제출되었습니다.",
        "buyer_signals": "구매자 관련 공개 신호가 있으나 직접 구매 검증은 아닙니다.",
        "indirect_signals": "간접 산업 신호가 있으며 구매 의사는 확인되지 않았습니다.",
        "insufficient_evidence": "아이디어별 판단에 충분한 시장 근거가 없습니다.",
    }
    verdict_labels = {
        "confirmed": "근거 확인",
        "signal_only": "신호만 확인",
        "unverified": "미확인",
    }
    status = run_state or market.status
    if status == "skipped":
        finding = "시장 조사를 실행하지 않았습니다."
    elif status == "timeout":
        finding = "시장 조사 제한 시간이 지나 완료되지 않았습니다."
    elif status == "error":
        finding = "시장 조사가 완료되지 않았습니다."
    elif market.status == "no_results":
        finding = "현재 검색 범위에서 시장 근거를 확보하지 못했습니다. 수요가 없다는 뜻은 아닙니다."
    elif review:
        finding = status_labels[review.status]
        if review.target_segment:
            finding += f" 목표 고객: {review.target_segment}."
    else:
        dimension_findings = [
            f"{item.dimension}: {verdict_labels[item.verdict]}"
            for item in market.dimensions
        ]
        finding = (
            "차원별 상태: " + " · ".join(dimension_findings[:4])
            if dimension_findings
            else "구조화된 시장 판단 결과가 없습니다."
        )

    references = [
        f"M:{citation_id}"
        for reason in (review.reasons if review else [])
        for citation_id in reason.citation_ids
    ]
    references.extend(
        f"M:{citation_id}"
        for dimension in market.dimensions
        for claim in dimension.claims
        for citation_id in claim.citation_ids
    )
    references.extend(
        f"M:{citation_id}"
        for action in (review.validation_actions if review else [])
        for citation_id in action.citation_ids
    )
    references.extend(
        f"M:{item.citation_id}"
        for item in market.evidence
        if item.evidence_nature == "direct_demand"
    )
    references = _refs(references)

    limitations = list(market.unknowns)
    if review:
        limitations.extend(review.unknowns)
    limitations.extend(
        dimension.limitation for dimension in market.dimensions if dimension.limitation
    )
    next_checks = [
        action.method for action in (review.validation_actions if review else [])
    ]
    next_checks.extend(
        dimension.next_check
        for dimension in market.dimensions
        if dimension.verdict == "unverified" and dimension.next_check
    )
    data_as_of = None
    if market.data_as_of:
        data_as_of = datetime.strptime(str(market.data_as_of), "%Y%m%d").strftime(
            "%Y-%m-%d"
        )
    return DomainEvidenceSummary(
        domain="market",
        status=status,
        finding=finding,
        evidence_ids=references,
        evidence_scope=(f"{market.search_scope} · 검색 근거 {len(market.evidence)}건"),
        evidence_count=len(market.evidence),
        data_as_of=data_as_of,
        limitations=_unique_text(limitations),
        next_check=_unique_text(next_checks),
    )


def build_executive_review(
    draft: IdeaDraft,
    patent: PatentReport,
    market: MarketReport,
    business: BusinessReview,
    *,
    patent_run_state: str | None = None,
    market_run_state: str | None = None,
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
    buyer_dimension = next(
        (item for item in market.dimensions if item.dimension == "buyer"), None
    )
    barrier_dimension = next(
        (item for item in market.dimensions if item.dimension == "adoption_barrier"),
        None,
    )
    if buyer_dimension:
        buyer_ids = [
            cid for claim in buyer_dimension.claims for cid in claim.citation_ids
        ]
    if barrier_dimension:
        barrier_ids = [
            cid for claim in barrier_dimension.claims for cid in claim.citation_ids
        ]

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
        market_refs = [
            f"M:{cid}"
            for reason in market_review.reasons
            for cid in reason.citation_ids
        ]
        market_refs.extend(
            f"M:{item.citation_id}"
            for item in market.evidence
            if item.source_type == "customer_validation"
            and item.evidence_nature == "direct_demand"
        )
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
        elif (
            precheck and precheck.status == "potentially_distinct" and cited_patent_refs
        ):
            market_implication = (
                "예비 차별 신호는 구매 증거가 아닙니다. 구매자·예산·도입 조건을 확인한 뒤 "
                "제한 파일럿을 판단합니다."
            )
        elif not direct_demand:
            market_implication = "구매자·예산 주체·도입 조건을 확인하기 전에는 수요 신호를 매출 전망으로 바꾸지 않습니다."
        else:
            market_implication = "제출된 고객 검증의 표본·구매 권한·실제 지불 조건을 확인한 뒤 제한 파일럿 여부를 결정합니다."
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
    if (
        patent.status != "completed"
        or not precheck
        or precheck.status != "potentially_distinct"
    ):
        gates.append(
            ApprovalGate(
                question="주요 기능이 선행 특허 청구항과 어떻게 구분되는가?",
                owner="변리사 또는 특허 전문가",
                proof_needed="우선 확인할 독립 청구항, 구성 대응표, 추가 검색 범위에 대한 서면 검토",
                consequence="미확인 상태에서는 해당 기능의 제품화·권리 확보 일정을 확정하지 않습니다.",
                evidence_ids=_refs(
                    [f"P:{cid}" for cid in (precheck.citation_ids if precheck else [])]
                ),
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
    if (
        not draft.revenue or not draft.current_alternative or barrier_dimension is None
    ) and len(gates) < 3:
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
        actions.append(
            "1. 고객개발 담당자: 초기 세그먼트 후보와 인터뷰해 문제 빈도·현재 대안·구매결정자·예산 경로를 확인하고, 확인된 사례와 미확인을 분리 기록합니다."
        )
    if (
        patent.status != "completed"
        or not precheck
        or precheck.status == "overlap_concern"
    ):
        actions.append(
            "2. 특허 담당자: 우선순위가 높은 문헌의 독립 청구항과 실제 제품 기능을 변리사와 대조하고, 회피 설계·추가 조사 필요성을 문서화합니다."
        )
    if len(actions) < 3:
        actions.append(
            "3. 제품·사업 담당자: 고객이 현재 대안과 제안 방식의 기준선·도입 조건을 합의한 뒤, 단일 고객·업무 범위의 파일럿 통과 기준과 중단 조건을 정합니다."
        )

    if business.recommendation == "limited_pilot" and not direct_demand:
        recommendation = "validate_demand"
    else:
        recommendation = business.recommendation
    confidence = (
        "낮음"
        if market.status in {"error", "no_results"}
        or patent.status in {"error", "partial", "no_results"}
        else {"low": "낮음", "medium": "보통", "high": "높음"}[business.confidence]
    )
    limitations = []
    if not direct_demand:
        limitations.append(
            "직접 고객 구매·지불 검증 자료가 없어 지불 의사는 미확인입니다."
        )
    if patent.status != "completed":
        limitations.append(
            "특허 조사가 완료되지 않아 검색 범위 밖 문헌을 포함한 권리 판단은 불가능합니다."
        )
    limitations.append(
        "이 문서는 사업 검토용 예비 권고이며 법률 의견·시장 규모 산정·성공 예측이 아닙니다."
    )

    return ExecutiveReview(
        recommendation=recommendation,
        scope=SCOPE_LABELS[recommendation],
        confidence=confidence,
        decision_summary=(
            "현재는 시장 진입 투자 승인보다 구매자·예산 검증과 특허 범위 확인을 우선할 단계입니다."
            if recommendation in {"validate_demand", "research_more"}
            else business.summary
        ),
        domain_summaries=[
            _patent_domain_summary(patent, patent_run_state),
            _market_domain_summary(market, market_run_state),
        ],
        integrated_findings=findings[:3],
        approval_gates=gates[:3],
        next_actions=actions[:3],
        limitations=limitations[:3],
    )


def cross_domain_findings(review: ExecutiveReview) -> list[IntegratedFinding]:
    """완료된 양쪽 영역의 근거 ID가 함께 연결된 판단만 반환한다."""
    if review.domain_summaries:
        summaries = {item.domain: item for item in review.domain_summaries}
        if any(
            domain not in summaries or summaries[domain].status != "completed"
            for domain in ("patent", "market")
        ):
            return []
        patent_ids = set(summaries["patent"].evidence_ids)
        market_ids = set(summaries["market"].evidence_ids)
    else:
        patent_ids = None
        market_ids = None

    findings = []
    for finding in review.integrated_findings:
        references = set(finding.evidence_ids)
        patent_references = {value for value in references if value.startswith("P:")}
        market_references = {value for value in references if value.startswith("M:")}
        if not patent_references or not market_references or finding.kind == "unknown":
            continue
        if patent_ids is not None and not patent_references <= patent_ids:
            continue
        if market_ids is not None and not market_references <= market_ids:
            continue
        findings.append(finding)
    return findings[:2]


def executive_report_markdown(
    title: str,
    review: ExecutiveReview,
    *,
    analyzed_on: int | None = None,
    cost_estimate=None,
    cost_totals=None,
) -> str:
    """특허·시장 교차 결론과 다음 확인만 담은 간결한 최종 검토 문서."""
    from datetime import datetime

    date_label = (
        datetime.strptime(str(analyzed_on), "%Y%m%d").strftime("%Y-%m-%d")
        if analyzed_on
        else datetime.now().strftime("%Y-%m-%d")
    )

    findings = cross_domain_findings(review)
    combined = bool(findings)
    recommendation = (
        RECOMMENDATION_LABELS.get(review.recommendation, review.recommendation)
        if combined
        else "추가 확인 후 결정"
    )
    decision = (
        review.decision_summary
        if combined
        else "특허와 시장 양쪽 근거가 함께 확인될 때까지 통합 결론을 보류합니다."
    )
    lines = [
        f"# 종합 검토 | {escape_md(title) or '아이디어'}",
        "",
        f"> 검토일 {date_label}",
        "",
        "## 종합 결론",
        "",
        f"- **판단:** {recommendation}",
        f"- {escape_md(decision)}",
        "",
        "## 결론 근거",
        "",
    ]
    if findings:
        for finding in findings:
            references = ", ".join(finding.evidence_ids)
            lines.append(
                f"- **{escape_md(finding.label)}:** {escape_md(finding.judgment)} "
                f"— {escape_md(finding.business_implication)} ({escape_md(references)})"
            )
    else:
        lines += ["- 특허와 시장 근거 ID가 함께 연결된 결론이 없어 판단을 보류합니다."]
    lines += ["", "## 판단 한계", ""]
    lines.extend(f"- {escape_md(item)}" for item in review.limitations[:2])
    if not review.limitations:
        lines.append("- 상세 특허·시장 보고서의 검색 범위와 근거 한계를 따릅니다.")
    lines += ["", "## 다음 확인", ""]
    lines.extend(f"- {escape_md(item)}" for item in review.next_actions[:2])
    lines += [
        "",
        "> 사업 검토용 예비 정리이며 법률 의견이나 사업 성공 보장이 아닙니다.",
        "",
    ]
    return "\n".join(lines)
