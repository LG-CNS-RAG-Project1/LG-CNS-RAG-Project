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
    click(app, "3개 구성으로 조사 시작하기 →")
    for source_id in list(app.session_state.selected):
        app.button(key=f"pick_{source_id}").click().run()
    return app


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
    app.text_area[1].set_value("고객의 설치 조건에 대응하는가?")
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


def test_home_and_numbered_navigation_keep_work():
    app = investigate()
    app.button(key="pick_P1").click().run()
    app.button(key="pick_M1").click().run()
    app.button(key="nav_4").click().run()
    assert app.session_state.stage == 4
    app.text_area(key="memo").set_value("검토 메모").run()
    app.button(key="home").click().run()
    assert app.session_state.stage == 1
    assert app.text_area(key="raw_input").value == DEMO_TEXT
    app.button(key="nav_3").click().run()
    assert app.session_state.selected == ["P1", "M1"]
    app.button(key="nav_4").click().run()
    assert app.text_area(key="memo").value == "검토 메모"


def test_future_stages_locked_until_confirmed():
    app = AppTest.from_file(str(APP)).run()
    assert app.button(key="nav_2").disabled
    assert app.button(key="nav_3").disabled
    assert app.button(key="nav_4").disabled
    app = begin()
    assert app.button(key="nav_3").disabled
    click(app, "3개 구성으로 조사 시작하기 →")
    assert not app.button(key="nav_3").disabled
    assert not app.button(key="nav_4").disabled


def test_question_revision_requires_reconfirmation():
    app = investigate()
    app.button(key="pick_P1").click().run()
    app.button(key="nav_2").click().run()
    version = app.session_state.version
    app.text_area(key=f"question_{version}_Q1").set_value(
        "현장 사용 조건과 관련되는가?"
    ).run()
    assert not app.session_state.confirmed_context
    assert app.session_state.selected == []
    assert app.button(key="nav_3").disabled
    click(app, "3개 구성으로 조사 시작하기 →")
    assert app.session_state.questions[0]["question"] == "현장 사용 조건과 관련되는가?"


def save_first_link(app):
    version = app.session_state.link_version
    prefix = f"link_{version}_Q1_"
    app.multiselect(key=prefix + "comps").set_value(["C3"])
    app.multiselect(key=prefix + "markets").set_value(["M1"])
    app.multiselect(key=prefix + "patents").set_value(["P1"])
    app.selectbox(key=prefix + "relation").set_value("도입 조건과 충돌 가능")
    app.text_area(key=prefix + "reason").set_value("추가 설치 검토")
    app.text_area(key=prefix + "counter_reason").set_value(
        "시연 문헌에 설치 시간 측정값이 없음"
    )
    app.text_area(key=prefix + "next_check").set_value("현장 설치 시간 확인")
    app.button(key="save_Q1").click().run()
    assert not app.exception
    return app


def test_saved_link_report_and_source_removal():
    from frontend.quick import review_rows

    app = investigate()
    app.button(key="pick_P1").click().run()
    app.button(key="pick_M1").click().run()
    save_first_link(app)
    assert app.session_state.links["Q1"]["market_ids"] == ["M1"]
    assert app.session_state.report_snapshot is None
    app.button(key="nav_4").click().run()
    snap = app.session_state.report_snapshot
    output = report(
        snap["raw"],
        snap["title"],
        snap["parts"],
        snap["ids"],
        "",
        snap["questions"],
        snap["links"],
    )
    assert "현장 설치 시간 확인" in output
    assert "설치 시간 측정값이 없음" in output
    assert "사용자 수정 가설" in output
    assert "통합 판단 보류" in output
    app.button(key="nav_3").click().run()
    app.button(key="exclude_M1").click().run()
    rows = review_rows(
        app.session_state.raw,
        app.session_state.parts,
        app.session_state.selected,
        app.session_state.questions,
        app.session_state.links,
    )
    assert rows[0]["market_ids"] == []
    assert "판단 보류" in rows[0]["status"]
    assert app.session_state.report_snapshot is None


def test_link_exclusion_clears_judgment():
    app = investigate()
    app.button(key="pick_P1").click().run()
    app.button(key="pick_M1").click().run()
    save_first_link(app)
    app.button(key="drop_link_Q1").click().run()
    assert "Q1" not in app.session_state.links
    assert app.session_state.report_snapshot is None


def test_joint_selection_never_automatically_confirms_connection():
    from frontend.quick import DEMO_QUESTIONS, review_rows, validate_link

    questions = DEMO_QUESTIONS
    rows = review_rows(DEMO_TEXT, DEMO_PARTS, ["M1", "P1"], questions, {})
    assert all("판단 보류" in r["status"] for r in rows)
    link = {
        "question_id": "Q1",
        "market_ids": ["P1"],
        "patent_ids": ["M1"],
        "component_ids": ["C1"],
        "relation": "해결 방식 관련",
        "reason": "관계",
        "next_check": "원문",
    }
    assert validate_link(link, DEMO_TEXT, DEMO_PARTS, ["M1", "P1"], questions)
    link.update(market_ids=["M1"], patent_ids=["P1"])
    assert validate_link(link, DEMO_TEXT, DEMO_PARTS, ["M1", "P1"], questions) is None
    assert validate_link(link, DEMO_TEXT, DEMO_PARTS, ["P1"], questions)
    rows = review_rows(DEMO_TEXT, DEMO_PARTS, ["M1", "P1"], questions, {"Q1": link})
    assert "사용자 수정 가설" in rows[0]["status"]
    assert "검증 전" in rows[0]["status"]


def test_automatic_default_and_exclusion_restore_report():
    app = begin()
    click(app, "3개 구성으로 조사 시작하기 →")
    assert set(app.session_state.selected) == {"M1", "M2", "P1", "P2"}
    assert app.session_state.links == {}
    app.button(key="nav_4").click().run()
    assert app.session_state.report_snapshot["links"]["Q2"]["origin"] == "demo_rule"
    app.button(key="nav_3").click().run()
    app.button(key="exclude_auto_Q2").click().run()
    assert app.session_state.report_snapshot is None
    app.button(key="nav_4").click().run()
    assert app.session_state.report_snapshot["links"]["Q2"]["origin"] == "excluded"
    app.button(key="nav_3").click().run()
    app.button(key="restore_Q2").click().run()
    app.button(key="nav_4").click().run()
    assert app.session_state.report_snapshot["links"]["Q2"]["origin"] == "demo_rule"
    assert not app.exception
