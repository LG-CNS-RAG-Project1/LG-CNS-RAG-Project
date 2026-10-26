"""단계 진행·구성 편집·선택 문헌·보고서의 연결을 검증한다."""

from pathlib import Path
from streamlit.testing.v1 import AppTest
from frontend.quick import DEMO_TEXT, DEMO_PARTS, candidates, report, validate_parts

APP = Path(__file__).resolve().parents[1] / "frontend" / "app.py"


def click(app, label):
    next(b for b in app.button if b.label == label).click().run()
    assert not app.exception
    return app


def begin():
    app = AppTest.from_file(str(APP), default_timeout=15).run()
    click(app, "예시 불러오기")
    return click(app, "핵심 구성 확인하기 →")


def investigate():
    app = begin()
    return click(app, "3개 구성으로 조사 시작하기 →")


def test_no_sidebar_and_input_guard():
    app = AppTest.from_file(str(APP)).run()
    assert not app.sidebar.children
    click(app, "핵심 구성 확인하기 →")
    assert app.error and app.session_state.stage == 1


def test_component_order_add_remove_and_confirm():
    app = begin()
    app.button(key="down_0").click().run()
    assert app.session_state.parts[1] == DEMO_PARTS[0]
    click(app, "＋ 구성 추가")
    click(app, "4개 구성으로 조사 시작하기 →")
    assert app.error and app.session_state.stage == 2
    app.button(key="remove_3").click().run()
    click(app, "3개 구성으로 조사 시작하기 →")
    assert app.session_state.stage == 3


def test_maximum_components():
    app = begin()
    for _ in range(4):
        click(app, "＋ 구성 추가")
    assert next(b for b in app.button if b.label == "＋ 구성 추가").disabled
    assert len(app.session_state.parts) == 7


def test_two_documents_gate_and_selected_only_report():
    app = investigate()
    generate = lambda: next(b for b in app.button if b.label == "종합 보고서 생성 →")
    assert generate().disabled
    app.button(key="pick_P1").click().run()
    assert generate().disabled
    app.button(key="pick_M1").click().run()
    assert not generate().disabled
    click(app, "종합 보고서 생성 →")
    assert app.session_state.stage == 4
    assert app.session_state.report_snapshot["ids"] == ["P1", "M1"]
    assert app.get("download_button")
    app.text_area(key="memo").set_value("원문 검토 필요").run()
    text = report(
        DEMO_TEXT,
        "검토",
        DEMO_PARTS,
        app.session_state.report_snapshot["ids"],
        app.session_state.memo,
    )
    assert "[P1]" in text and "[M1]" in text
    assert "[P2]" not in text and "[M2]" not in text
    assert "원문 검토 필요" in text


def test_selection_changes_invalidate_report():
    app = investigate()
    app.button(key="pick_P1").click().run()
    app.button(key="pick_M1").click().run()
    click(app, "종합 보고서 생성 →")
    click(app, "← 문헌 선정으로")
    app.button(key="exclude_P1").click().run()
    assert app.session_state.report_snapshot is None
    assert next(b for b in app.button if b.label == "종합 보고서 생성 →").disabled


def test_custom_input_has_no_sample_results():
    app = AppTest.from_file(str(APP)).run()
    app.text_area(key="raw_input").set_value(
        "실제 사용자가 직접 작성한 새로운 기술 아이디어"
    )
    click(app, "핵심 구성 확인하기 →")
    click(app, "1개 구성으로 조사 시작하기 →")
    assert app.error
    app.text_area[0].set_value("사용자가 정한 핵심 동작")
    click(app, "1개 구성으로 조사 시작하기 →")
    assert not any(b.key and b.key.startswith("pick_") for b in app.button)
    assert any("실제 검색은 연결 전" in i.value for i in app.info)
    assert not candidates(app.session_state.raw)


def test_input_revision_clears_selection():
    app = investigate()
    app.button(key="pick_P1").click().run()
    click(app, "구성 수정")
    click(app, "← 입력 수정")
    assert app.session_state.recent
    app.text_area(key="raw_input").set_value(
        "수정한 실제 아이디어로 자료가 달라지는 상황"
    )
    click(app, "핵심 구성 확인하기 →")
    assert app.session_state.selected == []
    assert app.session_state.report_snapshot is None


def test_report_distinguishes_missing_domain_and_escapes_input():
    output = report(DEMO_TEXT, "<script>", DEMO_PARTS, ["P1", "P2"], "<img>")
    assert "선택 근거 없음" in output
    assert "<script>" not in output and "<img>" not in output
    assert "시연용 가상 자료" in output


def test_component_validation():
    assert validate_parts([])
    assert validate_parts(["x"] * 8)
    assert validate_parts(["x", " x "])
    assert validate_parts([""])
    assert validate_parts(["구성"]) is None
