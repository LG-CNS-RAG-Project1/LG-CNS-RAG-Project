from src.generation.business_review import build_business_review
from src.schemas import (
    IdeaDraft,
    MarketEvidence,
    MarketOpportunityFinding,
    MarketOpportunityReview,
    MarketReport,
    PatentEvidence,
    PatentReport,
)


def draft(**updates):
    values = dict(
        original_text="공장 설비 고장 예측",
        title="고장 예측",
        problem="설비 고장을 미리 발견",
        technology="진동 센서 분석",
        customers="중소 제조사",
        difference="기존 점검보다 빠른 감지",
        revenue="월 구독료",
        current_alternative="정기 수동 점검",
        target_segment="중소 제조사",
        technical_components=["진동 센서", "고장 예측 모델"],
        status="complete",
    )
    values.update(updates)
    return IdeaDraft(**values)


def patent_report(status="completed", precheck=None):
    evidence = [
        PatentEvidence(
            citation_id=1,
            patent_id="P-1",
            title="진동 분석 특허",
            section="claims",
            quote="센서 데이터를 분석하는 장치",
        )
    ]
    return PatentReport(
        status=status,
        evidence=evidence if status == "completed" else [],
        search_scope="test",
        patentability_precheck=precheck,
    )


def test_business_review_requires_direct_customer_evidence_for_pilot():
    from src.schemas import PatentabilityPrecheck

    patent = patent_report(
        precheck=PatentabilityPrecheck(
            status="potentially_distinct",
            summary="검색 결과의 구성 차이 일부 확인",
            citation_ids=[1],
        )
    )
    indirect = MarketEvidence(
        citation_id=1,
        source_id="N1",
        source_type="news",
        title="예지보전 산업 동향",
        publisher="신문",
        quote="공장 예지보전 도입 사례",
        published_at=20261001,
        reliability="medium",
        recency="high",
        directness="low",
        evidence_nature="business_signal",
    )
    market = MarketReport(
        status="completed",
        evidence=[indirect],
        search_scope="test",
        opportunity_review=MarketOpportunityReview(
            status="indirect_signals",
            reasons=[
                MarketOpportunityFinding(
                    topic="수요", statement="산업 신호만 확인", citation_ids=[1]
                )
            ],
        ),
    )
    result = build_business_review(draft(), patent, market)
    assert result.recommendation == "validate_demand"
    assert any(item.citation_ids == ["M:1"] for item in result.reasons)
    assert result.confidence == "low"
    assert any("지불 의사" in item.finding for item in result.risks)
    assert result.next_steps


def test_patent_overlap_blocks_pilot_recommendation():
    from src.schemas import PatentabilityPrecheck

    patent = patent_report(
        precheck=PatentabilityPrecheck(
            status="overlap_concern",
            summary="청구항에 유사 구성이 포함됨",
            citation_ids=[1],
            expert_questions=["청구항 범위 검토"],
        )
    )
    market = MarketReport(status="no_results", search_scope="test")
    result = build_business_review(draft(), patent, market)
    assert result.recommendation == "research_more"
    assert any(item.topic == "특허 유사성" for item in result.risks)
    assert "청구항 범위 검토" in result.unknowns


def test_unmitigated_patent_overlap_recommends_hold_and_redesign():
    from src.schemas import PatentabilityPrecheck

    patent = patent_report(
        precheck=PatentabilityPrecheck(
            status="overlap_concern",
            summary="핵심 구성이 기존 독립항과 겹칠 가능성이 있습니다.",
            citation_ids=[1],
        )
    )
    market = MarketReport(
        status="completed",
        search_scope="test",
    )
    result = build_business_review(draft(), patent, market)
    assert result.recommendation == "hold_redesign"
    assert "보류" in result.summary


def test_direct_customer_validation_allows_only_limited_pilot():
    from src.schemas import PatentabilityPrecheck

    direct = MarketEvidence(
        citation_id=1,
        source_id="CV1",
        source_type="customer_validation",
        title="익명 파일럿 요약",
        publisher="사용자 제공",
        quote="구매 담당자가 제한된 파일럿 제안서를 요청함",
        published_at=20261001,
        reliability="medium",
        recency="high",
        directness="high",
        evidence_nature="direct_demand",
    )
    patent = patent_report(
        precheck=PatentabilityPrecheck(
            status="potentially_distinct",
            summary="검색된 문헌에서 차별 구성이 일부 보임",
            citation_ids=[1],
            distinction_hypotheses=["센서 조합 방식 검토"],
        )
    )
    market = MarketReport(status="completed", evidence=[direct], search_scope="test")
    result = build_business_review(draft(), patent, market)
    assert result.recommendation == "limited_pilot"
    assert result.confidence == "medium"
    assert any(step.horizon == "2~4주" for step in result.next_steps)
