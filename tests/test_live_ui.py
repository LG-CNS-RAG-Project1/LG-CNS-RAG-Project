"""직접 입력 → AI 구조화·재질문 → 실제 조사 → 보고서 경로를 가짜 분석 함수로 검증한다."""

from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

import src.generation.idea_parser as idea_parser
import src.generation.report_builder as report_builder
import src.pipeline as pipeline
from frontend.live import cost_markdown, cost_rows_list
from src.generation.report_builder import CRITERIA
from src.pipeline import PartRun, SourceAnalysis
from src.schemas import (
    IdeaDraft,
    MarketReport,
    PatentComparison,
    PatentEvidence,
    PatentReport,
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
                quote="진동 신호로 고장을 예측하는 장치",
                claim_number=1,
                claim_type="independent",
                source_url="https://example.com/p1",
            )
        ],
        comparisons=[
            PatentComparison(
                citation_id=1,
                similarity="유사",
                difference="차이",
                uncertainty="미확인",
            )
        ],
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
    click(app, "돋보기로 조사 시작")
    app.text_area(key="raw_input").input(IDEA).run()
    click(app, "핵심 구성 확인하기 →")
    return app


def test_direct_input_runs_followup_and_reaches_report(live):
    app = structured_app()
    assert app.session_state.stage == 1 and live["parse"] == 1
    app.text_input(key="ai_answer_revenue_0").input("모름")  # 폼 값은 제출 때 반영
    click(app, "답변 반영")
    draft = app.session_state.idea_draft
    assert draft.status == "complete" and draft.field_sources["revenue"] == "unknown"
    assert app.session_state.real_mode

    assert app.session_state.stage == 2
    click(app, "1개 구성으로 조사 시작하기 →")
    assert app.session_state.stage == 3
    click(app, "특허·시장 조사 실행")
    result = app.session_state.pipeline_result
    assert result is not None and live["analyze"] == 1
    assert result.links[0].status == "hold"  # 시장 근거가 없어 통합 판단 보류

    click(app, "종합 보고서 확인 →")
    assert app.session_state.stage == 4
    text = "\n".join(m.value for m in app.markdown)
    assert "실제 분석 결과" in text and "P:1" in text
    assert "시연용 가상 자료" not in text


def test_question_change_reuses_sources_without_new_analysis(live):
    app = structured_app()
    app.text_input(key="ai_answer_revenue_0").input("모름")  # 폼 값은 제출 때 반영
    click(app, "답변 반영")
    click(app, "1개 구성으로 조사 시작하기 →")
    click(app, "특허·시장 조사 실행")
    click(app, "← 아이디어·질문 수정")
    version = app.session_state.version
    app.text_area(key=f"question_{version}_Q1").input(
        "현장 설치 비용을 줄일 수 있는가?"
    ).run()
    click(app, "1개 구성으로 조사 시작하기 →")
    click(app, "질문 연결 다시 실행")
    assert live["analyze"] == 1 and live["link"] == 2
    assert (
        app.session_state.pipeline_result.links[0].question_id == "Q1"
        and "현장 설치 비용" in app.session_state.pipeline_result.markdown
    )


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
    app.text_input(key="ai_answer_revenue_0").input("모름")  # 폼 값은 제출 때 반영
    click(app, "답변 반영")
    click(app, "1개 구성으로 조사 시작하기 →")
    click(app, "특허·시장 조사 실행")
    errors = " ".join(e.value for e in app.error)
    assert "검색 실패" in errors
    assert "FAKE_KIPRIS_KEY_9" not in errors and "FAKEOPENAIKEY" not in errors


def test_example_path_keeps_demo_flow_with_key(live):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    click(app, "돋보기로 조사 시작")
    click(app, "예시 불러오기")
    click(app, "핵심 구성 확인하기 →")
    assert app.session_state.stage == 2 and live["parse"] == 0
    assert not app.session_state.real_mode


def test_cost_rows_and_markdown_escape():
    rows = [{"항목": "센서|키트", "수량": 2, "단가(만원)": None, "납기": "<b>2주</b>"}]
    assert cost_rows_list(rows) == rows
    md = cost_markdown(rows)
    assert "센서\\|키트" in md and "&lt;b&gt;2주&lt;/b&gt;" in md
    assert "| 센서\\|키트 | 2 |  |  | &lt;b&gt;2주&lt;/b&gt; |" in md
