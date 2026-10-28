"""특허·시장 보고서의 증거 상태를 다음 사업 검증 행동으로 요약한다."""

from typing import Literal

from pydantic import BaseModel, Field

from src.schemas import IdeaDraft, MarketReport, PatentReport


class BusinessReviewReason(BaseModel):
    topic: str
    finding: str
    citation_ids: list[str] = Field(default_factory=list)


class BusinessReviewAction(BaseModel):
    horizon: str
    target: str
    action: str
    success_signal: str
    citation_ids: list[str] = Field(default_factory=list)


class BusinessReview(BaseModel):
    recommendation: Literal[
        "validate_demand", "limited_pilot", "research_more", "hold_redesign"
    ]
    confidence: Literal["low", "medium", "high"]
    summary: str
    reasons: list[BusinessReviewReason] = Field(default_factory=list, max_length=3)
    opportunities: list[BusinessReviewReason] = Field(default_factory=list)
    risks: list[BusinessReviewReason] = Field(default_factory=list)
    next_steps: list[BusinessReviewAction] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    scope_note: str = (
        "다음 검증 행동에 대한 예비 권고이며 사업 성공·투자·법률 판단이 아닙니다."
    )


RECOMMENDATION_LABELS = {
    "validate_demand": "고객 수요 검증",
    "limited_pilot": "제한된 파일럿 검토",
    "research_more": "추가 조사 후 판단",
    "hold_redesign": "보류·재설계 검토",
}


def build_business_review(
    draft: IdeaDraft, patent: PatentReport, market: MarketReport
) -> BusinessReview:
    """명시된 증거 기준으로 권고를 정하고 과도한 사업성 단정을 막는다."""
    direct = [
        item
        for item in market.evidence
        if item.evidence_nature == "direct_demand"
        and item.source_type == "customer_validation"
    ]
    patent_precheck = patent.patentability_precheck
    patent_overlap = bool(
        patent_precheck
        and patent_precheck.citation_ids
        and patent_precheck.status == "overlap_concern"
    )
    patent_review_insufficient = bool(
        patent.status == "completed"
        and (
            not patent_precheck
            or not patent_precheck.citation_ids
            or patent_precheck.status == "insufficient_evidence"
        )
    )
    market_failed = market.status in {"error", "no_results"}
    patent_failed = patent.status in {"error", "no_results"}
    missing_business_fields = [
        label
        for field, label in (
            ("customers", "목표 고객"),
            ("revenue", "수익모델"),
        )
        if not getattr(draft, field)
    ]

    if market_failed or patent_failed or patent_review_insufficient:
        recommendation = "research_more"
    elif patent_overlap and not patent_precheck.distinction_hypotheses:
        recommendation = "hold_redesign"
    elif patent_overlap:
        recommendation = "research_more"
    elif direct and not missing_business_fields:
        recommendation = "limited_pilot"
    else:
        recommendation = "validate_demand"

    confidence = "low"
    if (
        direct
        and not missing_business_fields
        and not patent_failed
        and not patent_overlap
        and not patent_review_insufficient
        and market.status == "completed"
    ):
        confidence = "medium"
    # 소수의 검색 결과와 예비 분류만으로 사업 결론을 high로 표시하지 않는다.

    reasons: list[BusinessReviewReason] = []
    opportunities: list[BusinessReviewReason] = []
    risks: list[BusinessReviewReason] = []
    unknowns = list(dict.fromkeys(draft.unknowns + market.unknowns + patent.unknowns))

    if direct:
        ids = [f"M:{item.citation_id}" for item in direct]
        reasons.append(
            BusinessReviewReason(
                topic="고객 검증",
                finding=f"사용자 제공 고객 검증 자료 {len(direct)}건이 있습니다. 해당 자료의 표본과 범위를 확인해야 합니다.",
                citation_ids=ids,
            )
        )
        opportunities.append(reasons[-1])
    else:
        risks.append(
            BusinessReviewReason(
                topic="직접 수요",
                finding="인터뷰·구매 검토·파일럿 등 직접 고객 검증 자료가 없어 지불 의사는 미검증입니다.",
            )
        )
        unknowns.append("실제 목표 고객의 구매 의사와 지불 조건")

    if patent_overlap:
        risks.append(
            BusinessReviewReason(
                topic="특허 유사성",
                finding=patent_precheck.summary,
                citation_ids=[f"P:{item}" for item in patent_precheck.citation_ids],
            )
        )
    elif (
        patent_precheck
        and patent_precheck.citation_ids
        and patent_precheck.status == "potentially_distinct"
    ):
        opportunities.append(
            BusinessReviewReason(
                topic="기술 차별점 신호",
                finding=patent_precheck.summary,
                citation_ids=[f"P:{item}" for item in patent_precheck.citation_ids],
            )
        )
    else:
        unknowns.append("검색 범위 내 특허 청구항과의 구성요소별 대응")

    if market_failed:
        risks.append(
            BusinessReviewReason(
                topic="시장 근거 공백",
                finding=market.error_message or "시장 근거를 확보하지 못했습니다.",
            )
        )
    elif market.opportunity_review:
        for reason in market.opportunity_review.reasons:
            reasons.append(
                BusinessReviewReason(
                    topic="시장 근거",
                    finding=reason.statement,
                    citation_ids=[f"M:{item}" for item in reason.citation_ids],
                )
            )
        unknowns.extend(market.opportunity_review.unknowns)

    unknowns.extend(f"{label} 미정" for label in missing_business_fields)
    unknowns = list(dict.fromkeys(unknowns))

    next_steps = []
    if not direct:
        next_steps.append(
            BusinessReviewAction(
                horizon="2주 이내",
                target=draft.target_segment or draft.customers or "목표 고객 후보",
                action="목표 고객 후보와 문제·현재 대안·구매 절차를 인터뷰하고, 본인 식별정보나 비밀정보는 수집하지 않은 요약 결과만 기록합니다.",
                success_signal="고객이 같은 문제와 현재 대안, 도입 조건을 구체적 사례로 설명하고 후속 검증에 동의합니다.",
            )
        )
    if missing_business_fields or not draft.revenue:
        next_steps.append(
            BusinessReviewAction(
                horizon="2주 이내",
                target=draft.target_segment or draft.customers or "목표 고객 후보",
                action="사용자·구매결정자·예산 주체와 과금 가설을 구분해 정리합니다.",
                success_signal="구매 결정자, 예산 출처, 선호 과금 방식이 확인되거나 미확인으로 명시됩니다.",
            )
        )
    if patent_overlap or patent.status != "completed" or not patent_precheck:
        questions = (
            patent_precheck.expert_questions
            if patent_precheck
            else ["주요 청구항과 공개일을 특허 전문가와 검토"]
        )
        next_steps.append(
            BusinessReviewAction(
                horizon="파일럿 전",
                target="변리사 또는 특허 전문가",
                action="검색된 청구항의 대응 구성, 출원일 전 공개 여부와 추가 검색 범위를 검토합니다.",
                success_signal="검토 대상 청구항과 차별 구성, 추가 조사 범위가 서면으로 정리됩니다.",
                citation_ids=[
                    f"P:{item}"
                    for item in (
                        patent_precheck.citation_ids if patent_precheck else []
                    )
                ],
            )
        )
        unknowns.extend(questions)

    unknowns = list(dict.fromkeys(unknowns))

    if recommendation == "limited_pilot":
        summary = "직접 고객 검증과 핵심 입력이 확인되어 제한된 범위의 파일럿을 검토할 근거가 있습니다. 특허·운영 조건은 파일럿 전에 별도로 확인하세요."
        next_steps.append(
            BusinessReviewAction(
                horizon="2~4주",
                target=draft.target_segment or draft.customers,
                action="단일 고객·공정 범위로 제한된 파일럿을 설계하고 현재 기준선과 개선 목표를 사전에 합의합니다.",
                success_signal=(
                    draft.value_hypotheses[0]
                    if draft.value_hypotheses
                    else "고객과 합의한 운영 지표가 기준선 대비 개선되고 구매 절차가 확인됨"
                ),
            )
        )
    elif recommendation == "hold_redesign":
        summary = "검색된 청구항과의 겹침 우려가 크고 확인할 차별 구성도 부족합니다. 현재 설계의 진행은 보류하고 차별화 가능한 구성을 전문가와 검토하세요."
    elif recommendation == "research_more":
        summary = "현재 자료만으로 실행 결정을 내리기 어렵습니다. 시장 또는 특허의 핵심 공백을 먼저 확인하세요."
    else:
        summary = "산업 신호만으로 실제 구매 의사를 판단할 수 없습니다. 목표 고객의 문제·구매 조건을 먼저 검증하세요."

    return BusinessReview(
        recommendation=recommendation,
        confidence=confidence,
        summary=summary,
        reasons=reasons[:3],
        opportunities=opportunities,
        risks=risks,
        next_steps=next_steps,
        unknowns=unknowns,
    )
