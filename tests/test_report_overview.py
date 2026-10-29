"""실제 반환 계약의 판단·근거가 화면과 기록에서 유지되는지 확인한다."""

from pathlib import Path
from streamlit.testing.v1 import AppTest

from frontend.report_overview import dashboard_data
from src.pipeline import PipelineReport
from src.schemas import (
    MarketDimensionResult,
    MarketEvidence,
    MarketKeywordEdge,
    MarketKeywordNetwork,
    MarketKeywordNode,
    MarketReport,
    MarketSearchTrend,
    MarketTrendPoint,
    PatentReport,
    PatentStatisticItem,
    PatentTrendStatistics,
)
from src.generation.executive_review import (
    ExecutiveReview,
    IntegratedFinding,
    ApprovalGate,
    DomainEvidenceSummary,
)


def result():
    return PipelineReport(
        status="partial",
        title="검토 예시",
        patent=PatentReport(status="no_results", search_scope="test"),
        market=MarketReport(
            status="completed",
            search_scope="test",
            dimensions=[
                MarketDimensionResult(
                    dimension="price", verdict="unverified", next_check="고객 견적 확인"
                )
            ],
        ),
        executive_review=ExecutiveReview(
            recommendation="research_more",
            scope="견적과 특허 원문 추가 확인",
            confidence="low",
            decision_summary="확보한 근거만으로 제품화를 판단하지 않습니다.",
            integrated_findings=[
                IntegratedFinding(
                    label="도입 조건",
                    judgment="추가 확인",
                    business_implication="설치 조건 확인",
                    evidence_ids=["M:1"],
                    kind="unknown",
                )
            ],
            approval_gates=[
                ApprovalGate(
                    question="누가 구매하나요?",
                    owner="기획",
                    proof_needed="구매 담당자 인터뷰",
                    consequence="확인 전 투자 보류",
                )
            ],
            limitations=["직접 고객 자료 없음"],
        ),
    )


def test_dashboard_preserves_verdict_and_citations_without_filling_missing_dimensions():
    data = dashboard_data(result())
    assert data["conclusion"] == "추가 확인 후 결정"
    assert data["findings"] == []
    assert data["dimensions"] == [
        {
            "label": "가격",
            "judgment": "미확인",
            "implication": "고객 견적 확인",
            "kind": "미확인",
            "citations": "",
            "limitation": "",
            "evidence_status": "",
            "relevant_count": None,
        }
    ]
    assert "직접 고객 자료 없음" in data["unknowns"]


def test_market_limitations_are_preserved_in_dashboard_and_export():
    from frontend.report_overview import market_verification_markdown

    r = result()
    dimension = r.market.dimensions[0]
    dimension.limitation = "기업 주장 | 견적 미확보"
    dimension.evidence_status = "error"
    dimension.relevant_count = 0
    data = dashboard_data(r)
    assert data["dimensions"][0]["limitation"] == dimension.limitation
    assert data["dimensions"][0]["relevant_count"] == 0
    text = market_verification_markdown(r.market)
    assert "판정 오류" in text and "견적 미확보" in text
    dimension.relevant_count = None
    assert "미제공" in market_verification_markdown(r.market)


def test_dashboard_uses_market_and_patent_specific_next_checks():
    r = result()
    r.executive_review.domain_summaries = [
        DomainEvidenceSummary(
            domain="patent",
            status="completed",
            finding="청구항 추가 확인 필요",
            evidence_ids=["P:1"],
            evidence_scope="최종 비교 문헌",
            next_check=["독립 청구항을 전문가와 확인합니다."],
        ),
        DomainEvidenceSummary(
            domain="market",
            status="completed",
            finding="가격 근거 부족",
            evidence_ids=["M:1"],
            evidence_scope="시장 검색 근거",
            next_check=["고객 견적과 예산 주체를 확인합니다."],
        ),
    ]
    data = dashboard_data(r)
    assert [item["judgment"] for item in data["actions"]] == [
        "고객 견적과 예산 주체를 확인합니다.",
        "독립 청구항을 전문가와 확인합니다.",
    ]
    assert [item["label"] for item in data["domain_summaries"]] == [
        "특허 근거",
        "시장 근거",
    ]
    assert data["domain_summaries"][0]["citations"] == "P:1"


def test_patent_trend_statistics_are_transferred_to_integrated_report():
    r = result()
    r.patent.related_statistics = PatentTrendStatistics(
        scope="아이디어 관련 검색 후보",
        total_patents=4,
        application_date_coverage=3,
        ipc_coverage=2,
        cpc_coverage=1,
        ipc_distribution=[PatentStatisticItem(label="G01N", count=2)],
        yearly_applications=[
            PatentStatisticItem(label="2022", count=1),
            PatentStatisticItem(label="2024", count=2),
        ],
    )
    r.patent.indexed_statistics = PatentTrendStatistics(
        scope="현재 특허 색인",
        total_patents=10,
        application_date_coverage=8,
        ipc_coverage=7,
        ipc_distribution=[PatentStatisticItem(label="G01N", count=4)],
    )

    data = dashboard_data(r)
    related = data["patent_statistics"]["related_candidates"]
    assert related["total_patents"] == 4
    assert related["yearly_applications"][1]["label"] == "2024"
    assert related["ipc_coverage"] == 2
    assert data["patent_statistics"]["indexed"]["scope"] == "현재 특허 색인"

    app = AppTest.from_string("""
from frontend.report_overview import render_dashboard
import streamlit as st
render_dashboard(st.session_state.data)
""")
    app.session_state.data = data
    app.run()
    assert not app.exception
    assert any("특허 동향 · 검색 데이터 분포" in item.value for item in app.subheader)
    assert any("아이디어 관련 검색 후보" in item.value for item in app.markdown)
    assert any("전체 특허 분야의 출원 추세" in item.value for item in app.caption)


def test_final_dashboard_renders_concise_result_without_market_detail_chart():
    data = dashboard_data(result())
    app = AppTest.from_string("""
from frontend.report_overview import render_dashboard
import streamlit as st
render_dashboard(st.session_state.data)
""")
    app.session_state.data = data
    app.run()
    assert not app.exception
    assert not app.get("vega_lite_chart")
    assert any("종합 결론" in item.value for item in app.subheader)
    assert not any("가격" in item.value for item in app.subheader)


def test_dashboard_holds_cross_conclusion_when_domain_is_incomplete():
    r = result()
    r.executive_review.domain_summaries = [
        DomainEvidenceSummary(
            domain="patent",
            status="no_results",
            finding="현재 검색 범위에서 비교 근거를 확보하지 못했습니다.",
            evidence_ids=[],
            evidence_scope="KIPRIS · 비교 문헌 0건",
            limitations=["검색 결과는 법률 판단이 아닙니다."],
            next_check=["검색 범위를 확인합니다."],
        ),
        DomainEvidenceSummary(
            domain="market",
            status="timeout",
            finding="시장 조사 제한 시간이 지나 완료되지 않았습니다.",
            evidence_ids=["M:1"],
            evidence_scope="뉴스 검색 · 검색 근거 1건",
        ),
    ]
    data = dashboard_data(r)
    assert data["conclusion"] == "추가 확인 후 결정"
    assert data["findings"] == []

    app = AppTest.from_string("""
from frontend.report_overview import render_dashboard
import streamlit as st
render_dashboard(st.session_state.data)
""")
    app.session_state.data = data
    app.run()
    assert not app.exception
    assert any("특허·시장 교차 확인" in item.value for item in app.subheader)
    assert any("검색 결과 없음" in item.value for item in app.caption)
    assert any("시간 초과" in item.value for item in app.caption)


def test_dashboard_renders_real_market_context_without_treating_it_as_demand():
    r = result()
    r.market.evidence = [
        MarketEvidence(
            citation_id=1,
            source_id="dart:corp1:2025",
            source_type="dart",
            title="사업의 내용",
            publisher="공시기업",
            quote="공시기업 사업보고서 발췌 내용",
            section="II. 사업의 내용",
            published_at=20260331,
            period="FY2025",
            reliability="medium",
            recency="medium",
            directness="low",
            evidence_nature="company_claim",
        )
    ]
    r.market.search_trend = MarketSearchTrend(
        status="completed",
        keywords=["예지보전"],
        reference_keywords=["스마트공장"],
        points=[
            MarketTrendPoint(
                period="2026-01",
                theme_ratio=20,
                reference_ratio=50,
                relative_index=40,
            )
        ],
        recent_change_pct=12,
        direction="rising",
    )
    r.market.keyword_network = MarketKeywordNetwork(
        status="completed",
        document_count=12,
        nodes=[
            MarketKeywordNode(term="설비", document_count=8, cluster=0, x=0, y=0),
            MarketKeywordNode(
                term="예지보전", document_count=6, cluster=0, x=0.5, y=0.5
            ),
        ],
        edges=[MarketKeywordEdge(source="설비", target="예지보전", weight=3)],
        clusters=[["설비", "예지보전"]],
    )
    data = dashboard_data(r)
    assert data["market_context"]["dart_evidence"][0]["evidence_id"] == "M:1"
    assert data["market_context"]["dart_evidence"][0]["period"] == "FY2025"
    assert data["market_context"]["search_trend"]["points"][0]["relative_index"] == 40
    assert data["market_context"]["keyword_network"]["document_count"] == 12

    app = AppTest.from_string("""
from frontend.report_overview import render_dashboard
import streamlit as st
render_dashboard(st.session_state.data)
""")
    app.session_state.data = data
    app.run()
    assert not app.exception
    assert len(app.get("vega_lite_chart")) == 2
    assert any("시장 맥락 · 참고 자료" in item.label for item in app.get("expander"))
