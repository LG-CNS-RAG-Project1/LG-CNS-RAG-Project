"""사업기획 근거 화면: 셀 선택과 근거 일치, 미확인 표시, 실제·예시 가격 모드, 빈 상태, 외부 호출 없음."""

import pytest
import requests
from streamlit.testing.v1 import AppTest

from src.planner import store
from src.schemas import IdeaDraft
from tests.planner_fixtures import IDEA, WORLD
from tests.test_planner_service import run_refresh

SCRIPT = """
import streamlit as st
from frontend.planner_view import render_planner_section
render_planner_section(st.session_state.area, st.session_state.draft, root=st.session_state.root)
"""


def draft(**changes):
    fields = IDEA.model_dump() | changes
    return IdeaDraft(
        original_text="가상 아이디어",
        status="complete",
        **{
            k: fields[k]
            for k in (
                "title",
                "problem",
                "technology",
                "customers",
                "difference",
                "revenue",
                "field_sources",
            )
        },
    )


@pytest.fixture
def no_network(monkeypatch):
    def blocked(*args, **kwargs):
        raise AssertionError("화면에서 외부 호출 금지")

    monkeypatch.setattr(requests.Session, "request", blocked)
    import openai

    monkeypatch.setattr(openai, "OpenAI", blocked)


def app_for(root, area="SF-02", idea_draft=None):
    app = AppTest.from_string(SCRIPT, default_timeout=30)
    app.session_state.area = area
    app.session_state.draft = idea_draft if idea_draft is not None else draft()
    app.session_state.root = str(root)
    app.run()
    assert not app.exception, app.exception
    return app


@pytest.fixture
def run_root(tmp_path):
    root = tmp_path / "runs"
    run_refresh(root)
    return root


def texts(app):
    return [
        e.value
        for kind in ("markdown", "caption", "info", "warning", "success", "error")
        for e in getattr(app, kind)
    ]


def select_cell(app, startswith):
    box = app.selectbox(key="planner_cell")
    index = next(
        i for i, label in enumerate(box.options) if label.startswith(startswith)
    )
    box.select_index(index)
    app.run()
    assert not app.exception
    return app


def link_urls(app):
    """경쟁 주장 비교 탭(선택 칸 상세)의 원문 링크만 모은다."""
    return [e.proto.url for e in app.tabs[0].get("link_button")]


def test_empty_state_and_refresh_guidance_without_external_calls(tmp_path, no_network):
    app = app_for(tmp_path / "empty")
    joined = " ".join(texts(app))
    assert "저장된 자료집이 없습니다" in joined
    assert "IDEALENS_PLANNER_REFRESH=1" in joined
    assert not app.button


def test_undefined_and_auto_areas(run_root, no_network):
    app = app_for(run_root, area="SF-05")
    assert any("아직 정의되지 않아" in t for t in texts(app))
    app = app_for(run_root, area=None)
    assert app.selectbox(key="planner_area").value == "SF-02"


def test_selected_cell_shows_its_own_quotes_links_and_next_question(
    run_root, no_network
):
    app = app_for(run_root)
    assert app.dataframe
    joined = " ".join(texts(app))
    assert (
        "분석 해석(규칙 템플릿)" in joined
        and "경쟁력 점수나 성능 순위가 아닙니다" in joined
    )
    app = select_cell(app, "가나비전 (회사 수준·제품 미확인) × 불량 데이터 준비 부담")
    joined = " ".join(texts(app))
    assert (
        "상충 근거" in joined
        and "정상 이미지만으로 학습하는 검사 솔루션을 출시했다" in joined
    )
    assert "다음 질문 C3" in joined
    a1 = next(a["url"] for a in WORLD if a["key"] == "A1")
    a8 = next(a["url"] for a in WORLD if a["key"] == "A8")
    assert a1 in link_urls(app) and a8 in link_urls(app)

    app = select_cell(app, "다라테크 (회사 수준·제품 미확인) × 불량 데이터 준비 부담")
    joined = " ".join(texts(app))
    assert (
        "잘린 요약뿐이고 본문 미확보" in joined
        and "기능이 없다는 뜻이 아닙니다" in joined
    )
    assert a1 not in link_urls(app)


def test_actual_price_mode_withholds_and_example_mode_is_labelled(run_root, no_network):
    app = app_for(run_root)
    joined = " ".join(texts(app))
    assert "계산 보류" in joined and "5715" not in joined

    app.radio(key="planner_price_mode").set_value("example").run()
    joined = " ".join(texts(app))
    assert "예시 모드" in joined and "5715~6200만원" in joined
    assert app.get("vega_lite_chart")

    app.radio(key="planner_price_mode").set_value("actual").run()
    for field, value in {
        "C": "4000",
        "m": "100",
        "B": "3600",
        "I": "1000",
        "T": "24",
    }.items():
        app.text_input(key=f"planner_price_{field}").input(value)
    app.run()
    assert any("입력 오류" in e.value for e in app.error)


def test_saving_actual_price_adds_review_revision(run_root, no_network):
    app = app_for(run_root)
    for field, value in {
        "C": "4000",
        "m": "30",
        "B": "3600",
        "I": "1000",
        "T": "24",
    }.items():
        app.text_input(key=f"planner_price_{field}").input(value)
    app.run()
    app.button(key="planner_price_save").click().run()
    assert not app.exception
    path = store.list_runs(run_root)[0]["path"]
    assert store.latest_revision(path) == 1
    payload, semantic, _ = store.load_revision(path, 1)
    assert payload["user_inputs"]["price"]["values"]["m"] == "0.3"
    assert semantic["price"]["status"] == "overlap"


def test_relations_assumptions_and_dataset_tabs(run_root, no_network):
    app = app_for(run_root)
    assert app.get("graphviz_chart")
    joined = " ".join(texts(app))
    assert "외부 공급·계약 보도 3건" in joined and "계열 적용 제외 1건" in joined
    assert "영향받는 선택" in joined and "반대 근거 있음" in joined
    assert "같은 사례 진행 이력도: 표시 불가" in joined
    assert "재계산 해시 일치" in joined and "픽셀 동일성과는 별개" in joined


def test_run_built_from_different_idea_is_flagged(run_root, no_network):
    app = app_for(run_root, idea_draft=draft(difference="전혀 다른 차별점"))
    assert any("다른 아이디어로 만든 자료집" in w.value for w in app.warning)


def test_suppliers_with_only_unknown_cells_are_collapsed_but_reachable(
    run_root, no_network
):
    app = app_for(run_root)
    options = app.selectbox(key="planner_cell").options
    assert not any(o.startswith("마바솔루션") for o in options)
    app.selectbox(key="planner_cell").select_index(len(options) - 1).run()
    app.checkbox(key="planner_show_all").check().run()
    assert not app.exception
    options = app.selectbox(key="planner_cell").options
    assert any(o.startswith("마바솔루션") for o in options)
    app.checkbox(key="planner_show_all").uncheck().run()
    assert not app.exception
