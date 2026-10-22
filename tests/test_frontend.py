"""입력 검증과 시연 결과의 표시·유지를 확인한다."""

from pathlib import Path

from streamlit.testing.v1 import AppTest

from frontend.demo import build_demo, report_markdown
from src.schemas import PatentReport, StructuredIdea

APP = Path(__file__).resolve().parents[1] / "frontend" / "app.py"


def test_required_input_and_empty_state():
    app = AppTest.from_file(str(APP)).run()
    assert not app.exception
    next(b for b in app.button if b.label == "시연 결과 보기").click().run()
    assert app.error
    assert "result" not in app.session_state


def test_example_submit_persist_and_reset():
    app = AppTest.from_file(str(APP)).run()
    app.selectbox[0].select("설비 이상 탐지 예시").run()
    next(b for b in app.button if b.label == "시연 결과 보기").click().run()
    assert not app.exception
    assert app.session_state.result["idea"]["title"] == "설비 이상 탐지"
    assert len(app.tabs) == 3
    app.run()
    assert "result" in app.session_state
    next(b for b in app.button if b.label == "결과 초기화").click().run()
    assert "result" not in app.session_state


def test_report_marks_fictional_sources_and_keeps_input():
    result = build_demo(StructuredIdea(title="예시", problem="문제", technology="기술"))
    report = PatentReport.model_validate(result["patent"])
    assert report.evidence[0].source_url is None
    assert report.evidence[0].similarity is None
    download = report_markdown(result)
    assert "시연용 데이터" in download
    assert "가상 특허" in download
    assert "예시" in download
