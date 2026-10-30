"""화면 예시와 실제 성능 자료를 혼동하지 않고 이미지 교체 범위를 제한한다."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from frontend.showcase import ASSETS, asset_file, load_showcase


def test_examples_have_valid_assets_and_no_fabricated_experiment_capture():
    data = load_showcase()
    assert len(data["examples"]) == 3
    for item in data["examples"]:
        assert item["kind"] == "layout_sample"
        assert asset_file(item["image"])
        assert item["look_for"] and item["meaning"] and item["limit"]
    assert all(item["image"] is None for item in data["experiments"])
    assert asset_file("../../../.env") is None
    assert asset_file("missing.png") is None


def test_difference_examples_keep_research_state_and_offer_original_view():
    root = Path(__file__).resolve().parents[1]
    app = AppTest.from_file(str(root / "frontend/app.py")).run()
    app.session_state.idea_input_buffer = "유지할 입력"
    app.button(key="header_difference").click().run()
    app.button(key="difference_tab_examples").click().run()
    assert not app.exception
    assert app.session_state.page == "difference"
    assert app.session_state.idea_input_buffer == "유지할 입력"
    assert any("실제 조사 결과" in x.value for x in app.info)
    app.selectbox(key="showcase_example").set_value(1).run()
    assert any("시장 결과" in x.value for x in app.subheader)
    app.button(key="difference_tab_perspective").click().run()
    assert any("시장 조사를 더하다" in x.value for x in app.title)
    assert not app.exception
