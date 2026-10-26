"""브리프 전환, 비용의 미확인 값, 근거와 보고서 일관성을 검증한다."""

from copy import deepcopy
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from frontend.workspace import (
    EXAMPLE,
    SOURCES,
    TASKS,
    cost_summary,
    example_costs,
    export_report,
)

APP = Path(__file__).resolve().parents[1] / "frontend" / "app.py"


def click(app, label):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception
    return app


def sample_app():
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    click(app, "예시 불러오기")
    return click(app, "브리프 확정하고 조사 노트 열기 →")


def go(app, page):
    app.radio(key="nav_page").set_value(page).run()
    assert not app.exception


def test_costs_keep_missing_distinct_from_zero():
    rows = example_costs()
    result = cost_summary(rows)
    assert result == {"total": 315.0, "missing": ["설치·설비 연동"], "errors": []}
    rows[-1]["단가(만원)"] = 0
    assert not cost_summary(rows)["missing"]
    assert cost_summary(rows)["total"] == 315


@pytest.mark.parametrize(
    "quantity,price",
    [
        (0, 10),
        (-1, 10),
        (1.5, 10),
        (1, -1),
        (1, float("nan")),
        (1, float("inf")),
        ("bad", 10),
    ],
)
def test_invalid_cost_does_not_contribute_to_total(quantity, price):
    result = cost_summary([{"항목": "bad", "수량": quantity, "단가(만원)": price}])
    assert result["errors"] == ["bad"]
    assert result["total"] == 0


def test_export_contains_all_sources_costs_and_saved_review():
    report = export_report(EXAMPLE, example_costs(), "견적 요청", [TASKS[0]])
    assert all(s["quote"] in report and s["limit"] in report for s in SOURCES)
    assert "315.0만원" in report and "설치·설비 연동" in report
    assert "[x] " + TASKS[0] in report
    assert "견적 요청" in report and "실제 검색/AI 분석 API 미연결" in report


def test_custom_export_never_inherits_sample_evidence():
    brief = deepcopy(EXAMPLE) | {"idea": "<script>alert(1)</script>"}
    report = export_report(brief, [], "<img src=x onerror=alert(1)>", [])
    assert "가상 경쟁사" not in report and "[P1]" not in report
    assert "<script>" not in report and "<img" not in report
    assert "&lt;script&gt;" in report


def test_empty_input_and_unconfirmed_navigation_are_guarded():
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    click(app, "아이디어 정리하기 →")
    assert app.error and app.session_state.confirmed is None
    go(app, "종합 보고서")
    assert not app.get("download_button")


def test_custom_idea_can_be_structured_without_fake_analysis():
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    app.text_area(key="idea_input").set_value("새 아이디어")
    click(app, "아이디어 정리하기 →")
    click(app, "브리프 확정하고 조사 노트 열기 →")
    assert app.error
    for key in ("problem", "technology", "customers"):
        app.text_area(key=f"field_{key}").set_value(f"직접 작성 {key}")
    click(app, "브리프 확정하고 조사 노트 열기 →")
    assert not app.selectbox
    assert any("아직 수집된 시장" in x.value for x in app.info)
    assert app.session_state.costs[0]["단가(만원)"] is None


def test_sample_source_selection_and_cost_report_navigation():
    app = sample_app()
    click(app, "P2 근거 읽기")
    assert app.selectbox(key="source").value == "P2"
    assert any(SOURCES[-1]["quote"] in x.value for x in app.markdown)
    go(app, "구현 비용")
    assert app.metric[0].value == "315.0 만원"
    click(app, "비용 반영하기")
    assert app.metric[0].value == "315.0 만원"
    go(app, "종합 보고서")
    app.text_area(key="note_input").set_value("현장 견적 먼저")
    app.checkbox(key="task_0").check()
    click(app, "메모와 확인 항목 저장")
    go(app, "조사 노트")
    go(app, "종합 보고서")
    assert app.text_area(key="note_input").value == "현장 견적 먼저"
    assert app.checkbox(key="task_0").value


def test_editing_sample_clears_sample_costs_and_claims():
    app = sample_app()
    go(app, "분석 브리프")
    app.text_input(key="field_idea").set_value("실제 사용자 아이디어")
    click(app, "브리프 확정하고 조사 노트 열기 →")
    assert not app.selectbox
    assert cost_summary(app.session_state.costs)["total"] == 0
    go(app, "종합 보고서")
    assert app.metric[0].value == "0.0 만원"
    click(app, "예시 불러오기")
    click(app, "브리프 확정하고 조사 노트 열기 →")
    assert app.session_state.confirmed == EXAMPLE


def test_invalid_revised_brief_blocks_old_report():
    app = sample_app()
    go(app, "분석 브리프")
    app.text_area(key="field_problem").set_value("")
    click(app, "브리프 확정하고 조사 노트 열기 →")
    assert app.error and app.session_state.confirmed is None
    go(app, "종합 보고서")
    assert not app.get("download_button")


def test_cost_editor_applies_additions_once_and_preserves_on_navigation():
    app = sample_app()
    go(app, "구현 비용")
    key = f"cost_editor_{app.session_state.editor_version}"
    app.session_state[key] = {
        "edited_rows": {0: {"수량": 3}},
        "added_rows": [
            {
                "항목": "배송",
                "수량": 1,
                "단가(만원)": 10.0,
                "근거 / 가정": "직접 입력",
                "납기": "미확인",
            }
        ],
        "deleted_rows": [],
    }
    click(app, "비용 반영하기")
    assert app.metric[0].value == "405.0 만원"
    click(app, "비용 반영하기")
    assert len(app.session_state.costs) == 5
    go(app, "종합 보고서")
    assert app.metric[0].value == "405.0 만원"
