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
    assert not app.session_state.get("home_intro_played", False)
    assert not app.text_area
    assert not any(b.key and b.key.startswith("nav_") for b in app.button)
    assert sum(b.label == "돋보기로 조사 시작" for b in app.button) == 1
    press(app, "서비스 소개")
    assert not app.text_area
    intro = " ".join(x.value for x in app.markdown)
    press(app, "차별점")
    assert not app.text_area
    difference = " ".join(x.value for x in app.markdown)
    assert "어떤 고객에게 어떻게 쓰일 아이디어인지" in difference
    assert intro != difference
    press(app, "IdeaLens")
    press(app, "돋보기로 조사 시작")
    assert app.text_area(key="raw_input")
    assert all(app.button(key=f"rail_{i}") for i in (1, 2, 4))
    assert not any(
        button.key in {"nav_1", "nav_2", "nav_4", "subnav_2", "subnav_3"}
        for button in app.button
    )
    assert [b.key for b in app.button if b.key and b.key.startswith("rail_")][:4] == [
        "rail_home",
        "rail_1",
        "rail_2",
        "rail_3",
    ]


def test_demo_report_can_be_saved_and_reopened_without_analysis():
    app = AppTest.from_file(str(APP)).run()
    from frontend.quick import DEMO_TEXT, DEMO_PARTS, DEMO_QUESTIONS, candidates

    press(app, "돋보기로 조사 시작")
    app.session_state.raw = DEMO_TEXT
    app.session_state.confirmed_context = True
    app.session_state.report_snapshot = dict(
        raw=DEMO_TEXT,
        title="시연 기록",
        parts=list(DEMO_PARTS),
        ids=[x["id"] for x in candidates(DEMO_TEXT)],
        questions=DEMO_QUESTIONS,
        links={},
        sources=candidates(DEMO_TEXT),
    )
    app.session_state.stage = 4
    app.run()
    assert [tab.label for tab in app.get("tab")] == ["보고서 요약", "보고서 원문"]
    assert all(app.button(key=f"rail_{i}") for i in (1, 2, 4))
    assert not any(
        button.key in {"nav_1", "nav_2", "nav_4", "subnav_2", "subnav_3"}
        for button in app.button
    )
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
