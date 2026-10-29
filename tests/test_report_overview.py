"""실제 반환 계약의 판단·근거가 화면과 기록에서 유지되는지 확인한다."""

from pathlib import Path
from streamlit.testing.v1 import AppTest

from frontend.report_overview import dashboard_data
from src.pipeline import PipelineReport
from src.schemas import MarketReport, MarketDimensionResult, PatentReport
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
    assert not any("특허·시장 영역별 근거" in item.value for item in app.subheader)
