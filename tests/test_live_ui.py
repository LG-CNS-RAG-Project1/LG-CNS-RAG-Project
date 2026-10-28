"""직접 입력 → AI 구조화·재질문 → 실제 조사 → 보고서 경로를 가짜 분석 함수로 검증한다."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import src.generation.idea_parser as idea_parser
import src.generation.report_builder as report_builder
import src.pipeline as pipeline
from src.generation.report_builder import integrated_report_markdown
from frontend.live import cost_markdown, cost_rows_list
from src.generation.report_builder import CRITERIA
from src.pipeline import PartRun, SourceAnalysis
from frontend.workflow import WORKFLOW_JOBS, WORKFLOW_JOBS_LOCK
from src.schemas import (
    IdeaDraft,
    MarketReport,
    PatentComponentComparison,
    PatentDocumentReview,
    PatentEvidence,
    PatentReport,
    PatentabilityPrecheck,
)

APP = Path(__file__).resolve().parents[1] / "frontend" / "app.py"
IDEA = "공장 설비의 진동 데이터를 분석해 고장을 미리 알려주는 서비스"
FIELDS = dict(
    title="설비 고장 예측",
    problem="갑작스런 설비 고장",
    technology="진동 센서 분석",
    customers="중소 제조사",
    difference="저비용 설치",
)


def needs_input_draft(text):
    return IdeaDraft(
        original_text=text,
        **FIELDS,
        revenue="",
        field_sources={f: "extracted" for f in FIELDS if f != "title"},
        status="needs_input",
        missing_fields=["revenue"],
        questions={"revenue": "수익은 어떻게 내나요?"},
    )


def sources():
    patent = PatentReport(
        status="completed",
        search_scope="KIPRIS",
        evidence=[
            PatentEvidence(
                citation_id=1,
                patent_id="1020200000001",
                title="진동 기반 고장 예측 장치",
                section="claims",
                quote="진동 센서 분석으로 고장을 예측하는 장치",
                claim_number=1,
                claim_type="independent",
                source_url="https://example.com/p1",
            )
        ],
        patent_reviews=[
            PatentDocumentReview(
                patent_id="1020200000001",
                title="진동 기반 고장 예측 장치",
                citation_ids=[1],
                relevance="high",
                relevance_reason="청구항에 센서 기반 예측 구성이 포함됨",
                component_comparisons=[
                    PatentComponentComparison(
                        component_id="C1",
                        idea_component="진동 센서 분석",
                        status="partial",
                        citation_ids=[1],
                        matched_text="진동 센서 분석",
                        overlap="진동 센서 분석 구성이 포함됨",
                        difference="고장 예측 방식은 추가 확인 필요",
                        uncertainty="전체 청구항 범위 미검토",
                    )
                ],
                overall_summary="일부 기술 구성이 대응합니다.",
            )
        ],
        patentability_precheck=PatentabilityPrecheck(
            status="insufficient_evidence",
            summary="등록 관련 판단에는 추가 선행기술 조사가 필요합니다.",
            citation_ids=[1],
        ),
    )
    return SourceAnalysis(
        patent=patent,
        market=MarketReport(status="no_results", search_scope="뉴스 색인"),
        patent_run=PartRun(state="completed", seconds=3.0),
        market_run=PartRun(state="no_results", seconds=2.0),
        analyzed_on=20261028,
        total_seconds=3.0,
    )


@pytest.fixture
def live(monkeypatch):
    """OpenAI 키가 있는 상태를 흉내 내고 외부 호출 함수를 가짜로 바꾼다."""
    monkeypatch.setenv("OPENAI_API_KEY", "test-openai")
    calls = {"parse": 0, "analyze": 0, "link": 0}

    def fake_parse(text, *args, **kwargs):
        calls["parse"] += 1
        return needs_input_draft(text)

    def fake_analyze(draft, **kwargs):
        calls["analyze"] += 1
        return sources()

    def fake_link(system_prompt, user_text):
        calls["link"] += 1
        return {
            "links": [
                {
                    "question_id": "Q1",
                    "status": "connected",
                    "summary": "특허 근거 확인",
                    "criteria": [
                        {
                            "criterion": c,
                            "assessment": "확인",
                            "citation_ids": ["P:1"],
                            "next_check": "현장 확인",
                        }
                        for c in CRITERIA
                    ],
                }
            ]
        }

    monkeypatch.setattr(idea_parser, "parse_idea", fake_parse)
    monkeypatch.setattr(pipeline, "analyze_sources", fake_analyze)
    monkeypatch.setattr(report_builder, "call_report_llm", fake_link)
    return calls


def click(app, label):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception, app.exception
    return app


def structured_app():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.text_area(key="raw_input").input(IDEA).run()
    click(app, "아이디어 구조화·전체 보고서 시작 · API 비용 발생")
    return app


def confirm_draft(app):
    app.text_input(key="ai_answer_revenue_0").input("모름")
    click(app, "답변 반영")
    return app


def test_direct_input_runs_followup_and_reaches_report(live):
    app = structured_app()
    assert app.session_state.stage == 1 and live["parse"] == 1
    confirm_draft(app)
    draft = app.session_state.idea_draft
    assert draft.status == "complete" and draft.field_sources["revenue"] == "unknown"
    assert app.session_state.real_mode and app.session_state.stage == 2

    # 초안 확정 뒤 백그라운드 전체 분석이 자동 시작된다.
    assert live["analyze"] == 1
    app.session_state.analysis_workflow_id = None
    app.session_state.pipeline_result = pipeline.run_pipeline(
        app.session_state.idea_draft,
        [],
        sources=sources(),
    )
    app.session_state.stage = 2
    app.run()
    assert any("진동 센서 분석" in item.value for item in app.markdown)
    assert any("등록 가능성 예비 신호" in item.value for item in app.subheader)
    click(app, "P:1 근거 원문 확인")
    assert any(
        "<mark><u>진동 센서 분석</u></mark>" in item.value for item in app.markdown
    )

    click(app, "시장성 보고서 →")
    assert app.session_state.stage == 3
    click(app, "최종 실행 검토 →")
    assert app.session_state.stage == 4
    text = "\n".join(m.value for m in app.markdown)
    assert "검토일" in text and "P:1" in text
    assert "시연용 가상 자료" not in text


def test_four_report_stages_use_one_analysis_run(live):
    app = structured_app()
    confirm_draft(app)
    # 전체 분석은 초안 확정 콜백에서 한 번 시작된다.
    assert live["analyze"] == 1
    app.session_state.analysis_workflow_id = None
    app.session_state.pipeline_result = sources()
    app.session_state.stage = 2
    app.run()
    click(app, "시장성 보고서 →")
    assert app.session_state.stage == 3
    click(app, "← 특허 비교")
    assert app.session_state.stage == 2 and live["analyze"] == 1


def test_running_workflow_allows_previous_completed_stage_navigation(live):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    draft = IdeaDraft(
        original_text=IDEA,
        **FIELDS,
        revenue="구독",
        field_sources={f: "extracted" for f in FIELDS},
        status="complete",
    )
    patent = PatentReport(status="completed", search_scope="test")
    with WORKFLOW_JOBS_LOCK:
        WORKFLOW_JOBS["navigation-test"] = {
            "patent_report": patent,
            "patent_run": PartRun(state="completed", seconds=1),
            "market_report": None,
            "market_run": None,
            "phase": "market",
            "result": None,
            "sources": None,
            "error": None,
            "done": False,
            "started_at": 0,
            "updated_at": 0,
        }
    try:
        app.session_state.analysis_workflow_id = "navigation-test"
        app.session_state.idea_draft = draft
        app.session_state.real_mode = True
        app.session_state.confirmed_context = True
        app.session_state.stage = 3
        app.session_state.workflow_patent_displayed_at = 0
        app.session_state.workflow_auto_patent_advanced = True
        app.run()
        assert not app.button(key="nav_1").disabled
        assert not app.button(key="nav_2").disabled
        assert app.button(key="nav_3").disabled is False  # 현재 분석 중인 단계
        app.button(key="nav_1").click().run()
        assert app.session_state.stage == 1
        assert app.session_state.analysis_workflow_id == "navigation-test"
        app.button(key="nav_2").click().run()
        assert app.session_state.stage == 2
        assert app.session_state.analysis_workflow_id == "navigation-test"
        assert app.session_state.pipeline_result.patent.status == "completed"
    finally:
        with WORKFLOW_JOBS_LOCK:
            WORKFLOW_JOBS.pop("navigation-test", None)


def test_rejected_input_stays_on_first_step(live, monkeypatch):
    def rejected(text, *args, **kwargs):
        return IdeaDraft(
            original_text=text,
            status="rejected",
            input_status="unsafe",
            rejection_reason="검토할 사업 아이디어만 입력해 주세요.",
        )

    monkeypatch.setattr(idea_parser, "parse_idea", rejected)
    app = structured_app()
    assert app.session_state.stage == 1 and not app.session_state.real_mode
    assert any("사업 아이디어만" in w.value for w in app.warning)
    assert live["analyze"] == 0


def test_pipeline_error_message_hides_keys(live, monkeypatch):
    monkeypatch.setenv("KIPRIS_API_KEY", "FAKE_KIPRIS_KEY_9")

    def broken(draft, **kwargs):
        raise ValueError(
            "검색 실패 http://x?ServiceKey=FAKE_KIPRIS_KEY_9&q=1 sk-FAKEOPENAIKEY"
        )

    monkeypatch.setattr(pipeline, "analyze_sources", broken)
    app = structured_app()
    confirm_draft(app)
    errors = app.session_state.pipeline_error
    assert "검색 실패" in errors
    assert "FAKE_KIPRIS_KEY_9" not in errors and "FAKEOPENAIKEY" not in errors


def test_example_path_keeps_demo_flow_with_key(live):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    click(app, "예시 불러오기")
    assert app.session_state.raw_input
    assert "카메라와 조명" in app.session_state.raw_input
    assert app.session_state.stage == 1
    assert live["parse"] == 0 and live["analyze"] == 0
    assert not app.session_state.real_mode


def test_cost_rows_and_markdown_escape():
    rows = [{"항목": "센서|키트", "수량": 2, "단가(만원)": None, "납기": "<b>2주</b>"}]
    assert cost_rows_list(rows) == rows
    md = cost_markdown(rows)
    assert "센서\\|키트" in md and "&lt;b&gt;2주&lt;/b&gt;" in md
    assert "| 센서\\|키트 | 2 |  |  | &lt;b&gt;2주&lt;/b&gt; |" in md


def test_short_idea_can_start_ai_draft(live):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.text_area(key="raw_input").set_value("고장 예측")
    click(app, "아이디어 구조화·전체 보고서 시작 · API 비용 발생")
    assert live["parse"] == 1
    assert app.session_state.idea_draft.status == "needs_input"
