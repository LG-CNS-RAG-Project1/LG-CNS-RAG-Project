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
    assert data["findings"][0]["citations"] == "M:1"
    assert data["dimensions"] == [
        {
            "label": "가격",
            "judgment": "미확인",
            "implication": "고객 견적 확인",
            "kind": "미확인",
            "citations": "",
        }
    ]
    assert "직접 고객 자료 없음" in data["unknowns"]


def test_final_dashboard_renders_existing_data_and_chart_without_api():
    data = dashboard_data(result())
    app = AppTest.from_string("""
from frontend.report_overview import render_dashboard
import streamlit as st
render_dashboard(st.session_state.data)
""")
    app.session_state.data = data
    app.run()
    assert not app.exception
    assert app.get("vega_lite_chart")
    assert any("사업성 점수가 아닙니다" in item.value for item in app.caption)
    assert any("구매 담당자 인터뷰" in item.value for item in app.markdown)
