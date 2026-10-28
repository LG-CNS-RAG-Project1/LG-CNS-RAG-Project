"""홈 분리·기록 복원과 PDF 내보내기의 문서 계약을 검증한다."""

import json
from pathlib import Path

import pytest
from streamlit.testing.v1 import AppTest

from frontend.report_export import make_pdf
from frontend.workspace_view import validate_records

APP = Path(__file__).resolve().parents[1] / "frontend" / "app.py"


def press(app, label):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception


def test_landing_has_single_start_and_no_research_form():
    app = AppTest.from_file(str(APP)).run()
    assert not app.text_area
    assert not any(b.key and b.key.startswith("nav_") for b in app.button)
    assert sum(b.label == "조사 시작하기 ↗" for b in app.button) == 1
    press(app, "서비스 소개")
    assert not app.text_area
    press(app, "IdeaLens")
    press(app, "조사 시작하기 ↗")
    assert app.text_area(key="raw_input")
    assert [b.key for b in app.button if b.key and b.key.startswith("nav_")] == [
        "nav_1",
        "nav_3",
        "nav_4",
    ]


def test_demo_report_can_be_saved_and_reopened_without_analysis():
    app = AppTest.from_file(str(APP)).run()
    for label in [
        "조사 시작하기 ↗",
        "예시 불러오기",
        "핵심 구성 확인하기 →",
        "3개 구성으로 조사 시작하기 →",
        "종합 보고서 생성 →",
    ]:
        press(app, label)
    app.text_area(key="report_note").input("현장 설치 조건 확인").run()
    press(app, "내 기록에 보관")
    original = app.session_state.records[0]
    assert "현장 설치 조건 확인" in original["appendix"]
    press(app, "내 기록")
    assert len(app.session_state.records) == 1
    assert not app.exception
    assert app.get("download_button")
    raw = json.dumps(
        {"format": "idealens-records-v1", "records": app.session_state.records}
    ).encode()
    assert validate_records(raw)[0] == original


def test_record_import_rejects_unexpected_structure():
    for value in [
        b"[]",
        b'{"format":"idealens-records-v1","records":[{}]}',
        b"x" * 5_000_001,
    ]:
        with pytest.raises(ValueError):
            validate_records(value)


def test_pdf_supports_korean_markdown_and_xml_characters():
    pdf = make_pdf(
        "특허·시장 검토",
        "# 조사 보고서\n\n카메라 <센서> & 조건\n\n| 항목 | 근거 |\n|---|---|\n| 특허 | P:1 청구항 |\n\n"
        + "시장 근거를 원문과 비교합니다.\n" * 180,
    )
    assert pdf.startswith(b"%PDF-") and len(pdf) > 10000
    assert b"/FontFile2" in pdf  # Korean font is embedded, no OS font dependency.
