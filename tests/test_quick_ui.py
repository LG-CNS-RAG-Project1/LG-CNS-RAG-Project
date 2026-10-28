"""새 4단계 화면 흐름과 시연 경계, 보조 검증 함수를 확인한다."""

from pathlib import Path
from streamlit.testing.v1 import AppTest
from frontend.quick import DEMO_TEXT, DEMO_PARTS, candidates, report, validate_parts

APP = Path(__file__).resolve().parents[1] / "frontend" / "app.py"


def click(app, label):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception, app.exception
    return app


def demo_app():
    app = AppTest.from_file(str(APP), default_timeout=20).run()
    click(app, "예시 불러오기")
    return app


def test_four_stages_and_demo_disclosure():
    app = AppTest.from_file(str(APP)).run()
    assert [app.button(key=f"nav_{i}").label for i in range(1, 5)] == [
        "1  아이디어 입력·초안 확인",
        "2  특허 비교 보고서",
        "3  시장성 보고서",
        "4  최종 실행 검토",
    ]
    assert app.button(key="nav_2").disabled
    app = demo_app()
    assert app.session_state.stage == 1
    assert app.session_state.raw_input == DEMO_TEXT
    app.session_state.raw = DEMO_TEXT
    app.session_state.confirmed_context = True
    app.session_state.real_mode = False
    app.session_state.parts = list(DEMO_PARTS)
    app.session_state.selected = [item["id"] for item in candidates(DEMO_TEXT)]
    app.session_state.stage = 2
    app.run()
    assert app.session_state.stage == 2
    assert any("가상 시연 자료" in item.value for item in app.warning)
    click(app, "시장성 보고서 →")
    assert app.session_state.stage == 3
    click(app, "최종 실행 검토 →")
    assert app.session_state.stage == 4
    assert any("시연용 초안" in item.value for item in app.warning)


def test_blank_input_is_rejected_before_proceeding():
    app = AppTest.from_file(str(APP)).run()
    click(app, "아이디어 구조화·전체 보고서 시작 · API 비용 발생")
    assert app.session_state.stage == 1
    assert app.error


def test_custom_input_does_not_show_sample_evidence(monkeypatch):
    import frontend.live

    monkeypatch.setattr(frontend.live, "live_available", lambda: False)
    app = AppTest.from_file(str(APP)).run()
    app.text_area(key="raw_input").set_value(
        "실제 사용자가 직접 작성한 새로운 기술 아이디어"
    )
    click(app, "아이디어 구조화·전체 보고서 시작 · API 비용 발생")
    assert app.session_state.stage == 1
    assert app.session_state.real_mode is False
    assert any("실제 AI 분석 키가 없어 시연 경로" in item.value for item in app.info)


def test_component_validation_and_demo_report_helpers():
    assert validate_parts([])
    assert validate_parts(["x"] * 8)
    assert validate_parts(["x", " x "])
    assert validate_parts([""])
    assert validate_parts(["구성"]) is None
    output = report(DEMO_TEXT, "<script>", DEMO_PARTS, ["P1", "P2"], "<img>")
    assert "선택 근거 없음" in output
    assert "<script>" not in output and "<img>" not in output
    assert "시연용 가상 자료" in output
