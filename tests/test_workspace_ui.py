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
