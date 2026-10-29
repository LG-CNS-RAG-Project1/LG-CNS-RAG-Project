"""직접 입력 → AI 구조화·재질문 → 실제 조사 → 보고서 경로를 가짜 분석 함수로 검증한다."""

import json
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
                application_number="1020200000001",
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
    from src.generation import cost_estimation

    monkeypatch.setattr(
        cost_estimation,
        "call_cost_llm",
        lambda *args, **kwargs: {
            "status": "insufficient_data",
            "unknowns": ["테스트에서 비용 추정 미실행"],
        },
    )
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


def analysis_app():
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.button(key="lens_start").click().run()
    assert not app.exception, app.exception
    return app


def structured_app():
    app = analysis_app()
    app.text_area(key="raw_input").input(IDEA).run()
    click(app, "AI 초안 만들기")
    return app


def confirm_draft(app):
    assert app.session_state.stage == 1
    assert not app.session_state.get("analysis_workflow_id")
    assert app.session_state.idea_draft.status == "needs_input"
    assert app.text_area(key=f"draft_revenue_{app.session_state.version}").value == ""
    click(app, "수정 내용으로 전체 분석 시작")
    assert app.session_state.stage == 1 and not app.session_state.get(
        "analysis_workflow_id"
    )
    assert "수익모델" in " ".join(item.value for item in app.error)
    app.text_area(key=f"draft_problem_{app.session_state.version}").set_value(
        "갑작스러운 고장으로 생산이 중단되는 문제"
    )
    app.text_area(key=f"draft_revenue_{app.session_state.version}").set_value(
        "월 구독료"
    )
    click(app, "수정 내용으로 전체 분석 시작")
    return app


def test_direct_input_runs_followup_and_reaches_report(live):
    app = structured_app()
    assert app.session_state.stage == 1 and live["parse"] == 1
    assert live["analyze"] == 0
    confirm_draft(app)
    draft = app.session_state.idea_draft
    assert (
        draft.status == "complete" and draft.field_sources["revenue"] == "user_answer"
    )
    assert draft.problem == "갑작스러운 고장으로 생산이 중단되는 문제"
    assert app.session_state.real_mode and app.session_state.stage in (2, 4)

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
    assert any("특허 비교 신호" in item.value for item in app.subheader)
    assert any("특허 비교 궤도" in item.value for item in app.subheader)
    assert {item.label for item in app.get("expander")} >= {
        "1. 특허 비교 궤도",
        "2. 주의점",
        "3. 개선 제안 · 설계 대안",
    }
    charts = app.get("vega_lite_chart")
    assert len(charts) == 1
    assert json.loads(charts[0].proto.spec)["padding"] == {
        "top": 12,
        "right": 12,
        "bottom": 12,
        "left": 12,
    }
    assert not any(
        "궤도 차트를 표시하지 못했습니다" in item.value for item in app.warning
    )
    serialized = json.dumps(json.loads(charts[0].proto.spec), ensure_ascii=False)
    assert "핵심 요약" in serialized and "우선 확인 이유" in serialized
    assert not any("문헌 요약 선택" in item.label for item in app.selectbox)
    assert '"name": "patent_click"' in serialized

    app.session_state.selected_patent_detail_id = "1020200000001"
    app.run()
    detail = app.get("dialog")[0]
    assert any("진동 기반 고장 예측 장치" in item.value for item in detail.subheader)
    assert any("아이디어 구성요소별 비교" in item.value for item in detail.markdown)
    assert any(
        "<mark><u>진동 센서 분석</u></mark>" in item.value for item in detail.markdown
    )
    assert any("KIPRIS에서 출원번호 검색" in item.label for item in detail.link_button)
    assert any("P:1" in item.value for item in detail.caption)

    click(app, "시장성 보고서 →")
    assert app.session_state.stage == 3
    click(app, "최종 실행 검토 →")
    assert app.session_state.stage == 4
    text = "\n".join(m.value for m in app.markdown)
    assert "추가 확인 후 결정" in text
    assert "통합 결론을 보류합니다" in text
    assert "시연용 가상 자료" not in text
    previous = app.session_state.pipeline_result
    previous_calls = dict(live)
    for stage in (2, 3, 4):
        app.button(key=f"rail_{stage}").click().run()
        assert not app.exception
        assert app.session_state.stage == stage
        assert app.session_state.pipeline_result == previous
    assert live == previous_calls
    for page in ("history", "about", "difference", "home"):
        app.button(key=f"rail_{page}").click().run()
        assert not app.exception
        assert app.session_state.pipeline_result == previous
    app.button(key="rail_resume").click().run()
    assert not app.exception
    assert app.session_state.stage == 4
    assert app.session_state.pipeline_result == previous
    assert live == previous_calls


def test_kipris_quota_failure_is_not_presented_as_patent_absence(live):
    draft = IdeaDraft(
        original_text=IDEA,
        **FIELDS,
        revenue="월 구독료",
        field_sources={field: "extracted" for field in FIELDS},
        status="complete",
    )
    source = sources().model_copy(
        update={
            "patent": PatentReport(
                status="error",
                search_scope="Dense + KIPRIS",
                error_message="KIPRIS API 오류: 22 - LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR",
            ),
            "patent_run": PartRun(state="error", seconds=1),
        }
    )
    app = analysis_app()
    app.session_state.idea_draft = draft
    app.session_state.real_mode = True
    app.session_state.confirmed_context = True
    app.session_state.stage = 2
    app.session_state.pipeline_result = pipeline.run_pipeline(draft, [], sources=source)
    app.run()

    assert any("검색 미완료" in item.value for item in app.warning)
    assert not any("표시할 특허 문헌이 없습니다" in item.value for item in app.info)


def test_partial_patent_comparison_keeps_eight_sources_visible(live):
    draft = IdeaDraft(
        original_text=IDEA,
        **FIELDS,
        revenue="월 구독료",
        field_sources={field: "extracted" for field in FIELDS},
        status="complete",
    )
    evidence = [
        PatentEvidence(
            citation_id=index,
            patent_id=f"P{index}",
            title=f"특허 {index}",
            section="abstract",
            quote=f"검색 근거 {index}",
        )
        for index in range(1, 9)
    ]
    source = sources().model_copy(
        update={
            "patent": PatentReport(
                status="partial",
                search_scope="검색과 원문 확보 완료, 비교 생성 실패",
                error_message="비교 응답 검증 실패",
                evidence=evidence,
            ),
            "patent_run": PartRun(
                state="partial", seconds=8.0, message="비교 응답 검증 실패"
            ),
        }
    )
    app = analysis_app()
    app.session_state.idea_draft = draft
    app.session_state.real_mode = True
    app.session_state.confirmed_context = True
    app.session_state.stage = 2
    app.session_state.pipeline_result = pipeline.run_pipeline(draft, [], sources=source)
    app.run()

    assert not app.exception
    assert any(
        "원문은 확보했지만 비교 분석을 완료하지 못했습니다" in item.value
        for item in app.warning
    )
    assert any("최종 비교 문헌 8건 · 목표 5~8건" in item.value for item in app.caption)


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


@pytest.mark.parametrize("navigation_key", ["nav_1", "rail_1"])
def test_running_workflow_top_step_opens_idea_preview_without_leaving_current_stage(
    live,
    navigation_key,
):
    app = analysis_app()
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
        app.button(key=navigation_key).click().run()
        assert app.session_state.stage == 3
        assert app.session_state.analysis_workflow_id == "navigation-test"
        dialog = app.get("dialog")[0]
        assert any("아이디어 구조화" in item.value for item in dialog.get("subheader"))
    finally:
        with WORKFLOW_JOBS_LOCK:
            WORKFLOW_JOBS.pop("navigation-test", None)


@pytest.mark.parametrize("navigation_key", ["nav_2", "rail_2"])
def test_completed_stage_status_button_opens_read_only_dialog(live, navigation_key):
    app = analysis_app()
    draft = IdeaDraft(
        original_text=IDEA,
        **FIELDS,
        revenue="구독",
        field_sources={f: "extracted" for f in FIELDS},
        status="complete",
    )
    patent = sources().patent
    with WORKFLOW_JOBS_LOCK:
        WORKFLOW_JOBS["preview-test"] = {
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
        app.session_state.analysis_workflow_id = "preview-test"
        app.session_state.idea_draft = draft
        app.session_state.real_mode = True
        app.session_state.confirmed_context = True
        app.session_state.stage = 3
        app.session_state.workflow_patent_displayed_at = 0
        app.session_state.workflow_auto_patent_advanced = True
        app.run()

        assert not any(
            (item.key or "").startswith("workflow_preview_") for item in app.button
        )
        assert "특허" in app.button(key="nav_2").label
        assert app.button(key="nav_3").disabled
        assert app.button(key="rail_3").disabled
        assert app.button(key="rail_4").disabled
        app.button(key=navigation_key).click().run()

        assert app.session_state.analysis_workflow_id == "preview-test"
        assert app.session_state.stage == 3
        dialog = app.get("dialog")[0]
        assert any("특허 비교 보고서" in item.value for item in dialog.get("subheader"))
        assert any("특허 비교 궤도" in item.value for item in dialog.get("subheader"))
        assert not any("선택한 문헌" in item.value for item in dialog.get("markdown"))
        assert not any(
            "문헌 요약 선택" in item.label for item in dialog.get("selectbox")
        )
        chart = dialog.get("vega_lite_chart")
        assert chart and '"reason"' in chart[0].proto.spec
        assert '"name": "patent_hover_preview"' in chart[0].proto.spec
        assert "patent_click_preview" not in chart[0].proto.spec
        assert app.session_state.stage == 3
    finally:
        with WORKFLOW_JOBS_LOCK:
            WORKFLOW_JOBS.pop("preview-test", None)


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
    assert any("사업 아이디어만" in item.value for item in app.error)
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


def test_example_generates_draft_without_starting_analysis(live):
    app = analysis_app()
    assert not any("시연" in button.label for button in app.button)
    click(app, "예시 아이디어")
    click(app, "공장 설비 고장 예측")
    assert not app.exception, app.exception
    assert "진동 데이터를 분석" in app.session_state.raw_input
    assert app.session_state.idea_page_view == "draft"
    assert app.session_state.stage == 1
    assert live["parse"] == 1 and live["analyze"] == 0


def test_cost_rows_and_markdown_escape():
    rows = [{"항목": "센서|키트", "수량": 2, "단가(만원)": None, "납기": "<b>2주</b>"}]
    assert cost_rows_list(rows) == rows
    md = cost_markdown(rows)
    assert "센서\\|키트" in md and "&lt;b&gt;2주&lt;/b&gt;" in md
    assert "| 센서\\|키트 | 2 |  |  | &lt;b&gt;2주&lt;/b&gt; |" in md


def test_short_idea_can_start_ai_draft(live):
    app = analysis_app()
    app.text_area(key="raw_input").set_value(IDEA)
    click(app, "AI 초안 만들기")
    assert live["parse"] == 1
    assert app.session_state.idea_draft.status == "needs_input"


def test_short_input_is_rejected_without_calling_parser(live):
    app = analysis_app()
    app.text_area(key="raw_input").set_value("고장")
    click(app, "AI 초안 만들기")
    assert live["parse"] == 0
    assert app.session_state.stage == 1
    assert any("자 이상" in item.value for item in app.error)


def test_complete_draft_waits_for_user_and_uses_edited_values(live, monkeypatch):
    complete = IdeaDraft(
        original_text=IDEA,
        **FIELDS,
        revenue="구독",
        current_alternative="정기 점검",
        target_segment="중소 제조공장",
        technical_components=["진동 센서", "예측 모델"],
        value_hypotheses=["고장 정지시간 감소"],
        field_sources={
            "problem": "extracted",
            "technology": "extracted",
            "customers": "extracted",
            "difference": "extracted",
            "revenue": "extracted",
        },
        status="complete",
    )
    monkeypatch.setattr(idea_parser, "parse_idea", lambda text, *a, **k: complete)
    app = analysis_app()
    app.text_area(key="raw_input").input(IDEA).run()
    click(app, "AI 초안 만들기")
    assert app.session_state.idea_draft.status == "complete"
    assert app.selectbox(key="technology_area_choice").value == "AUTO"
    assert (
        app.text_area(key=f"draft_revenue_{app.session_state.version}").value == "구독"
    )
    assert app.session_state.stage == 1
    assert not app.session_state.get("analysis_workflow_id")
    assert live["analyze"] == 0

    key = app.session_state.version
    app.text_area(key=f"draft_technology_{key}").set_value("수정한 진동 예측 기술")
    click(app, "수정 내용으로 전체 분석 시작")
    assert app.session_state.idea_draft.technology == "수정한 진동 예측 기술"
    assert app.session_state.idea_draft.field_sources["technology"] == "user_answer"
    assert app.session_state.stage in (2, 4)
    assert app.session_state.analysis_workflow_id or app.session_state.pipeline_result


def test_completed_patent_preview_uses_current_orbit_report_ui(live):
    from src.schemas import IdeaDraft

    draft = IdeaDraft(
        original_text=IDEA,
        title="진동 예측 서비스",
        problem="설비 고장 대응 부담",
        technology="진동 데이터 분석",
        customers="제조사",
        difference="상태기반 경보 가설",
        revenue="월 구독 가설",
        field_sources={
            "problem": "ai_hypothesis",
            "technology": "extracted",
            "customers": "extracted",
            "difference": "ai_hypothesis",
            "revenue": "ai_hypothesis",
        },
        status="complete",
    )
    app = analysis_app()
    app.session_state.raw = IDEA
    app.session_state.raw_input = IDEA
    app.session_state.idea_draft = draft
    app.session_state.confirmed_context = True
    app.session_state.real_mode = True
    app.session_state.stage = 3
    app.session_state.pipeline_result = pipeline.run_pipeline(
        draft, [], sources=sources()
    )
    app.session_state.workflow_preview_stage = 2
    app.run()

    assert any("특허 비교 궤도" in item.value for item in app.subheader)
    assert not any("선택한 문헌" in item.value for item in app.markdown)
    assert not any("문헌 요약 선택" in item.label for item in app.selectbox)
    assert app.get("vega_lite_chart")
    chart_spec = app.get("vega_lite_chart")[0].proto.spec
    assert '"name": "patent_hover_preview"' in chart_spec
    assert "patent_click_preview" not in chart_spec
    assert app.session_state.stage == 3


def test_completed_idea_preview_marks_ai_hypotheses(live):
    from src.schemas import IdeaDraft

    draft = IdeaDraft(
        original_text=IDEA,
        title="진동 예측 서비스",
        problem="설비 고장 대응 부담 가설",
        technology="진동 데이터 분석",
        customers="제조사 가설",
        difference="상태기반 경보 가설",
        revenue="월 구독 가설",
        field_sources={
            "problem": "ai_hypothesis",
            "technology": "extracted",
            "customers": "ai_hypothesis",
            "difference": "ai_hypothesis",
            "revenue": "ai_hypothesis",
        },
        status="complete",
    )
    app = analysis_app()
    app.session_state.raw = IDEA
    app.session_state.raw_input = IDEA
    app.session_state.idea_draft = draft
    app.session_state.confirmed_context = True
    app.session_state.real_mode = True
    app.session_state.stage = 3
    app.session_state.pipeline_result = pipeline.run_pipeline(
        draft, [], sources=sources()
    )
    app.session_state.workflow_preview_stage = 1
    app.run()

    assert any("검증 전 AI 가설" in item.value for item in app.markdown)
    assert any("수익모델" in item.value for item in app.markdown)
    assert app.session_state.stage == 3
