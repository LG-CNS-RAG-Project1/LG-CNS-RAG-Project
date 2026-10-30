"""소개에서 설명 단계로 이동할 때 조사 입력을 보존하고 API를 실행하지 않는다."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from frontend.process_guide import GUIDES


def test_guide_cards_open_tracks_and_preserve_research_input():
    app = AppTest.from_file(
        str(Path(__file__).resolve().parents[1] / "frontend/app.py")
    ).run()
    app.session_state.idea_input_buffer = "보존할 아이디어"
    app.button(key="header_about").click().run()
    assert not app.exception
    app.button(key="intro_open_patent").click().run()
    assert app.session_state.introduction_view == "patent"
    assert app.session_state.page == "about"
    assert app.session_state.idea_input_buffer == "보존할 아이디어"
    assert not app.session_state.get("analysis_workflow_id")
    assert any("특허가 내 아이디어" in x.value for x in app.title)
    app.button(key="process_patent_3").click().run()
    assert app.session_state.process_step_patent == 3
    assert any(x.value == "내 구성과 비교" for x in app.subheader)
    app.button(key="intro_tab_market").click().run()
    assert app.session_state.introduction_view == "market"
    app.button(key="process_market_4").click().run()
    assert any(x.value == "주장과 인용 검사" for x in app.subheader)
    assert app.button(key="process_market_4").proto.type == "primary"
    app.button(key="intro_tab_overview").click().run()
    assert app.button(key="intro_open_market")
    assert app.session_state.idea_input_buffer == "보존할 아이디어"
    assert not app.exception


def test_process_guide_implementation_links_exist():
    root = Path(__file__).resolve().parents[1]
    for guide in GUIDES.values():
        for step in guide["steps"]:
            for source in step[-1]:
                assert (root / source).is_file(), source
        for source in guide["evaluation_sources"]:
            assert (root / source).is_file(), source
