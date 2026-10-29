"""분석 중 공개 화면 이동과 완료 결과 복귀를 검증한다."""

from pathlib import Path
import pytest
from streamlit.testing.v1 import AppTest
from frontend.workflow import WORKFLOW_JOBS, WORKFLOW_JOBS_LOCK
from src.schemas import IdeaDraft, PatentReport, MarketReport
from src.pipeline import PartRun

APP = Path(__file__).resolve().parents[1] / "frontend" / "app.py"
IDEA = "공장 설비의 진동 데이터를 분석하는 서비스"
FIELDS = dict(
    title="설비 검토",
    problem="갑작스런 고장",
    technology="진동 분석",
    customers="제조사",
    difference="저비용",
)


@pytest.mark.parametrize("page", ["about", "difference", "history", "home"])
def test_public_navigation_preserves_running_job_and_collects_completion(page):
    app = AppTest.from_file(str(APP), default_timeout=30).run()
    app.button(key="lens_start").click().run()
    draft = IdeaDraft(original_text=IDEA, **FIELDS, revenue="구독", status="complete")
    job_id = "public-navigation-test"
    with WORKFLOW_JOBS_LOCK:
        WORKFLOW_JOBS[job_id] = dict(
            phase="patent", result=None, error=None, done=False
        )
    try:
        app.session_state.analysis_workflow_id = job_id
        app.session_state.idea_draft = draft
        app.session_state.confirmed_context = True
        app.session_state.stage = 2
        app.session_state.page = page
        app.run()
        assert not app.exception
        assert app.session_state.analysis_workflow_id == job_id
        assert app.button(key="return_running_research")
        assert app.session_state.stage == 2
        if page == "home":
            app.button(key="lens_start").click().run()
            assert app.session_state.stage == 2
            assert app.session_state.analysis_workflow_id == job_id
            app.session_state.page = page
        from src.pipeline import PipelineReport

        result = PipelineReport(
            status="partial",
            title="완료",
            patent=PatentReport(status="no_results", search_scope="test"),
            market=MarketReport(status="no_results", search_scope="test"),
            patent_run=PartRun(state="skipped"),
            market_run=PartRun(state="skipped"),
        )
        with WORKFLOW_JOBS_LOCK:
            WORKFLOW_JOBS[job_id].update(result=result, done=True)
        app.run()
        assert not app.exception
        assert app.session_state.page == page
        assert app.session_state.analysis_workflow_id is None
        assert app.session_state.pipeline_result.title == "완료"
        app.button(key="return_completed_research").click().run()
        assert not app.exception
        assert app.session_state.page == "workspace"
    finally:
        with WORKFLOW_JOBS_LOCK:
            WORKFLOW_JOBS.pop(job_id, None)
