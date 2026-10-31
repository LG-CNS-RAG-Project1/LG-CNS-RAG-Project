"""구버전 결과 복구와 시장 요약의 근거 한계를 검증한다."""

from types import SimpleNamespace
from pathlib import Path
from streamlit.testing.v1 import AppTest
from frontend.report_reading import market_brief, grounded_review_result
from frontend.workspace_view import report_payload
from src.pipeline import PipelineReport
from src.schemas import PatentReport, MarketReport, MarketDimensionResult, MarketClaim
from src.generation.executive_review import ExecutiveReview, IntegratedFinding


def test_missing_original_cannot_support_final_summary_and_original_is_preserved():
    report = PipelineReport(
        status="partial",
        title="검토",
        patent=PatentReport(status="no_results", search_scope="test"),
        market=MarketReport(status="no_results", search_scope="test"),
        executive_review=ExecutiveReview(
            recommendation="limited_pilot",
            scope="파일럿",
            confidence="high",
            decision_summary="확정 불가",
            integrated_findings=[
                IntegratedFinding(
                    label="연결 판단",
                    judgment="검증되지 않은 결론",
                    business_implication="검증되지 않은 행동",
                    evidence_ids=["P:1", "M:1"],
                    kind="interpretation",
                ),
                IntegratedFinding(
                    label="미확인",
                    judgment="구매 의사 미확인",
                    business_implication="고객 인터뷰 필요",
                    kind="unknown",
                ),
            ],
        ),
    )
    safe, hidden = grounded_review_result(report)
    assert hidden == 1
    assert [x.kind for x in safe.executive_review.integrated_findings] == ["unknown"]
    assert len(report.executive_review.integrated_findings) == 2
    state = SimpleNamespace(
        real_mode=True, pipeline_result=report, research_title="검토", raw="입력"
    )
    payload = report_payload(state)
    assert payload["unsupported_count"] == 1
    assert payload["dashboard"]["conclusion"] == "추가 확인 후 결정"
    assert "검증되지 않은 결론" not in str(payload["dashboard"])


def test_saved_record_pdf_is_available_without_running_analysis():
    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "frontend/app.py")
    ).run()
    app.session_state.records = [
        dict(
            title="보관 보고서",
            raw="가상 입력",
            markdown="# 저장 결과\n원문 근거",
            appendix="\n검토 메모",
            saved_at="test",
            id="saved",
            demo=True,
            rows=[],
            patent_count=0,
            market_count=0,
        )
    ]
    app.button(key="header_history").click().run()
    app.radio[0].set_value(0)
    app.button(key="history_prepare_pdf").click().run()
    assert not app.exception
    assert app.session_state.history_pdf["data"].startswith(b"%PDF-")
    assert any(
        x.label == "선택한 기록 PDF 다운로드 ↓" for x in app.get("download_button")
    )


def test_old_session_optional_field_is_rehydrated_without_new_analysis():
    report = PipelineReport(
        status="partial",
        title="검토",
        patent=PatentReport(status="no_results", search_scope="test"),
        market=MarketReport(status="no_results", search_scope="test"),
        executive_review=ExecutiveReview(
            recommendation="research_more",
            scope="추가 확인",
            confidence="low",
            decision_summary="자료 부족",
        ),
    )
    report.executive_review.__dict__.pop("domain_summaries")
    state = SimpleNamespace(
        real_mode=True, pipeline_result=report, research_title="검토", raw="입력"
    )
    payload = report_payload(state)
    assert payload is not None
    assert state.pipeline_result.executive_review.domain_summaries == []
    assert payload["dashboard"]["conclusion"] == "추가 확인 후 결정"


def test_missing_required_result_returns_reanalysis_notice_instead_of_crash():
    report = SimpleNamespace(model_dump=lambda: {"status": "partial"})
    assert (
        report_payload(SimpleNamespace(real_mode=True, pipeline_result=report)) is None
    )


def test_market_brief_does_not_promote_hypothesis_or_missing_citation_to_fact():
    market = MarketReport.model_construct(
        status="completed",
        search_scope="test",
        dimensions=[
            MarketDimensionResult(
                dimension="demand",
                verdict="unverified",
                next_check="고객 인터뷰",
                claims=[
                    MarketClaim(
                        statement="구매할 가능성이 높다",
                        claim_type="ai_hypothesis",
                        citation_ids=[],
                    ),
                    MarketClaim(
                        statement="사실이라 주장하나 원문 없음",
                        claim_type="fact",
                        citation_ids=[9],
                    ),
                ],
            )
        ],
    )
    brief = market_brief(market)
    assert brief["facts"] == []
    assert brief["checks"] == ["고객 인터뷰"]
