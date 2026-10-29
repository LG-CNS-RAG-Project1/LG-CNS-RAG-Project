from src.generation.business_review import build_business_review
from src.generation.executive_review import (
    DomainEvidenceSummary,
    build_executive_review,
    executive_report_markdown,
)
from src.schemas import (
    IdeaDraft,
    MarketDimensionResult,
    MarketEvidence,
    MarketOpportunityReview,
    MarketReport,
    PatentComponentComparison,
    PatentDocumentReview,
    PatentEvidence,
    PatentReport,
    PatentabilityPrecheck,
)


def sample_reports():
    draft = IdeaDraft(
        original_text="센서 분석 아이디어",
        title="설비 이상 예측",
        problem="예기치 않은 설비 중단",
        technology="센서 기반 이상 예측",
        customers="공장 정비 담당자",
        revenue="구독",
        current_alternative="정기 점검",
        target_segment="중소 제조 공장",
        technical_components=["진동 센서", "이상 예측 모델"],
        status="complete",
    )
    patent = PatentReport(
        status="completed",
        search_scope="KIPRIS",
        evidence=[
            PatentEvidence(
                citation_id=1,
                patent_id="P-1",
                title="진동 분석 장치",
                section="claims",
                quote="진동 신호를 분석하여 설비 이상을 판별하는 장치",
                claim_number=1,
            )
        ],
        patent_reviews=[
            PatentDocumentReview(
                patent_id="P-1",
                title="진동 분석 장치",
                citation_ids=[1],
                relevance="high",
                component_comparisons=[
                    PatentComponentComparison(
                        component_id="C1",
                        idea_component="진동 센서",
                        status="partial",
                        citation_ids=[1],
                        matched_text="진동 신호를 분석",
                    ),
                    PatentComponentComparison(
                        component_id="C2",
                        idea_component="이상 예측 모델",
                        status="uncertain",
                        citation_ids=[1],
                    ),
                ],
                overall_summary="신호 처리 구성이 일부 대응합니다.",
            )
        ],
        patentability_precheck=PatentabilityPrecheck(
            status="overlap_concern",
            summary="청구항에 진동 신호 처리 구성이 있어 전문가 검토가 필요합니다.",
            citation_ids=[1],
        ),
    )
    market = MarketReport(
        status="completed",
        search_scope="시장 뉴스",
        evidence=[
            MarketEvidence(
                citation_id=1,
                source_id="N1",
                source_type="news",
                title="예지보전 도입 동향",
                publisher="산업일보",
                quote="한 제조사가 예지보전 시스템을 도입했다.",
                published_at=20261001,
                reliability="medium",
                recency="high",
                directness="low",
                evidence_nature="business_signal",
            )
        ],
        dimensions=[
            MarketDimensionResult(
                dimension="buyer",
                verdict="signal_only",
                claims=[
                    {
                        "statement": "해당 제조사가 예지보전 시스템을 도입했다.",
                        "claim_type": "fact",
                        "citation_ids": [1],
                    }
                ],
            )
        ],
        opportunity_review=MarketOpportunityReview(
            status="indirect_signals",
            target_segment="중소 제조 공장",
            reasons=[
                {
                    "topic": "구매자",
                    "statement": "공개된 도입 사례가 있으나 직접 구매 검증은 아니다.",
                    "citation_ids": [1],
                }
            ],
            unknowns=["예산 주체"],
            validation_actions=[
                {
                    "title": "구매 조건 확인",
                    "target": "정비 담당자",
                    "method": "예산 주체와 견적을 확인합니다.",
                    "success_signal": "구매 절차와 예산이 확인됩니다.",
                    "citation_ids": [1],
                }
            ],
        ),
    )
    return draft, patent, market


def test_executive_report_shows_only_concise_cross_domain_conclusions():
    draft, patent, market = sample_reports()
    patent.patentability_precheck.expert_questions = [
        "우선 독립 청구항을 변리사와 대조합니다."
    ]
    business = build_business_review(draft, patent, market)
    review = build_executive_review(draft, patent, market, business)
    markdown = executive_report_markdown("설비 이상 예측", review, analyzed_on=20261028)

    assert review.recommendation == "hold_redesign"
    assert "현재 구성의 제품화는 보류" in review.scope
    assert any("P:1" in item.evidence_ids for item in review.integrated_findings)
    assert any("M:1" in item.evidence_ids for item in review.integrated_findings)
    market_finding = next(
        item for item in review.integrated_findings if item.label == "시장 진입 근거"
    )
    assert {"P:1", "M:1"}.issubset(set(market_finding.evidence_ids))
    assert "유사 청구항 우려를 낮추지는 않습니다" in market_finding.business_implication
    assert "## 종합 결론" in markdown
    assert "## 결론 근거" in markdown
    assert "## 판단 한계" in markdown
    assert "## 다음 확인" in markdown
    assert "M:1" in markdown and "P:1" in markdown
    assert "예산 주체와 견적을 확인합니다." in markdown
    assert "우선 독립 청구항을 변리사와 대조합니다." in markdown
    assert "영역별 근거 요약" not in markdown
    assert "승인 전에 통과할 확인사항" not in markdown
    assert "진동 분석 장치" not in markdown  # 상세 보고서의 문헌 반복을 피한다
    assert len(markdown.splitlines()) < 55


def test_executive_report_holds_if_either_domain_is_not_completed():
    from src.generation.executive_review import cross_domain_findings

    draft, patent, market = sample_reports()
    review = build_executive_review(
        draft,
        patent,
        market,
        build_business_review(draft, patent, market),
        market_run_state="skipped",
    )
    markdown = executive_report_markdown("설비 이상 예측", review, analyzed_on=20261028)

    assert cross_domain_findings(review) == []
    assert "추가 확인 후 결정" in markdown
    assert "통합 결론을 보류합니다" in markdown
    assert "P:1" not in markdown and "M:1" not in markdown


def test_market_industry_signal_is_not_recast_as_direct_purchase():
    draft, patent, market = sample_reports()
    review = build_executive_review(
        draft, patent, market, build_business_review(draft, patent, market)
    )
    market_finding = next(
        item for item in review.integrated_findings if item.label == "시장 진입 근거"
    )
    assert "구매 의사는 미검증입니다" in market_finding.judgment
    assert "매출 전망" in market_finding.business_implication


def test_domain_summary_preserves_source_status_and_scope_without_inference():
    draft, patent, market = sample_reports()
    review = build_executive_review(
        draft,
        patent,
        market,
        build_business_review(draft, patent, market),
        patent_run_state="partial",
        market_run_state="skipped",
    )

    patent_summary, market_summary = review.domain_summaries
    assert patent_summary.status == "partial"
    assert patent_summary.evidence_ids == ["P:1"]
    assert "비교 문헌 1건" in patent_summary.evidence_scope
    assert market_summary.status == "skipped"
    assert market_summary.finding == "시장 조사를 실행하지 않았습니다."
    assert market_summary.evidence_ids == ["M:1"]
    assert "구매 의사는" not in market_summary.finding


def test_domain_summary_rejects_evidence_from_another_domain():
    import pytest

    with pytest.raises(ValueError, match="foreign evidence ID"):
        DomainEvidenceSummary(
            domain="patent",
            status="completed",
            finding="확인",
            evidence_ids=["M:1"],
            evidence_scope="검색 후보",
        )
