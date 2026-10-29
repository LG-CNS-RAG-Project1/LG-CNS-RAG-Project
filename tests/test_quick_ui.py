"""랜딩·초안 화면 분리와 실제 분석 진입 조건을 확인한다."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from frontend.quick import DEMO_TEXT, DEMO_PARTS, report, validate_parts

APP = Path(__file__).resolve().parents[1] / "frontend" / "app.py"


def click(app, label):
    next(button for button in app.button if button.label == label).click().run()
    assert not app.exception, app.exception
    return app


def test_landing_preserves_home_and_enters_compact_analysis():
    app = AppTest.from_file(str(APP)).run()
    assert app.button(key="lens_start").label == "돋보기로 조사 시작"
    assert "hero-copy" in "\n".join(item.value for item in app.html)
    assert not any((button.key or "").startswith("rail_") for button in app.button)
    click(app, "돋보기로 조사 시작")
    assert app.text_area(key="raw_input")
    assert app.button(key="create_idea_draft")
    assert not any("시연" in button.label for button in app.button)
    assert [app.button(key=f"nav_{i}").label.split()[0] for i in (1, 2, 4)] == [
        "1",
        "2",
        "3",
    ]
    assert not app.button(key="rail_1").disabled
    assert all(app.button(key=f"rail_{i}").disabled for i in (2, 3, 4))
    assert any('href="#research-top"' in item.value for item in app.html)


def test_quick_history_preserves_input_and_returns_without_reanalysis():
    app = AppTest.from_file(str(APP)).run()
    click(app, "돋보기로 조사 시작")
    text = "공장 설비의 진동 데이터를 분석하는 새로운 서비스"
    app.text_area(key="raw_input").set_value(text).run()
    app.session_state.saved_memo = "검토 중인 메모"
    app.button(key="rail_history").click().run()
    assert not app.exception
    assert app.session_state.page == "history"
    assert app.session_state.raw_input == text
    assert app.session_state.saved_memo == "검토 중인 메모"
    assert not any((button.key or "").startswith("rail_") for button in app.button)
    app.button(key="home").click().run()
    click(app, "돋보기로 조사 시작")
    assert app.text_area(key="raw_input").value == text
    assert app.session_state.idea_draft is None
    assert app.session_state.pipeline_result is None


def test_example_and_recent_are_separate_controls():
    app = AppTest.from_file(str(APP)).run()
    click(app, "돋보기로 조사 시작")
    assert app.button(key="toggle_examples").label == "예시 아이디어"
    assert app.button(key="toggle_recent").label == "최근 입력"
    click(app, "예시 아이디어")
    assert any("공장 설비 고장 예측" in button.label for button in app.button)
    assert app.session_state.show_examples and not app.session_state.show_recent
    click(app, "최근 입력")
    assert app.session_state.show_recent and not app.session_state.show_examples
    assert any("현재 세션" in item.value for item in app.caption)


def test_recent_session_input_reloads_into_the_editable_input_view():
    app = AppTest.from_file(str(APP)).run()
    app.session_state.recent = [
        {"title": "진동 예측", "text": "공장 설비 진동을 분석하는 서비스 아이디어"}
    ]
    click(app, "돋보기로 조사 시작")
    click(app, "최근 입력")
    click(app, "진동 예측")
    assert app.session_state.raw_input == "공장 설비 진동을 분석하는 서비스 아이디어"
    assert app.session_state.idea_page_view == "input"
    assert app.session_state.app_view == "analysis"


def test_custom_input_does_not_show_sample_evidence(monkeypatch):
    import frontend.live

    monkeypatch.setattr(frontend.live, "live_available", lambda: False)
    app = AppTest.from_file(str(APP)).run()
    click(app, "돋보기로 조사 시작")
    app.text_area(key="raw_input").set_value(
        "실제 사용자가 직접 작성한 새로운 기술 아이디어"
    )
    click(app, "AI 초안 만들기")
    assert app.session_state.stage == 1
    assert app.session_state.real_mode is False
    assert any("OPENAI_API_KEY" in item.value for item in app.error)


def test_blank_input_is_rejected_before_draft_generation():
    app = AppTest.from_file(str(APP)).run()
    click(app, "돋보기로 조사 시작")
    click(app, "AI 초안 만들기")
    assert app.session_state.stage == 1
    assert app.error


def test_component_validation_and_legacy_report_helpers():
    assert validate_parts([])
    assert validate_parts(["x"] * 8)
    assert validate_parts(["x", " x "])
    assert validate_parts([""])
    assert validate_parts(["구성"]) is None
    output = report(DEMO_TEXT, "<script>", DEMO_PARTS, ["P1", "P2"], "<img>")
    assert "선택 근거 없음" in output
    assert "<script>" not in output and "<img>" not in output
