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


def test_refresh_reconnects_only_saved_job_without_starting_worker(monkeypatch):
    import frontend.workflow_resume as resume
    import time

    draft = IdeaDraft(original_text=IDEA, **FIELDS, revenue="구독", status="complete")
    context = dict(
        draft=draft.model_dump(),
        parts=["진동 분석"],
        questions=[],
        area=None,
        raw=IDEA,
        title="설비 검토",
    )
    with WORKFLOW_JOBS_LOCK:
        WORKFLOW_JOBS["saved-private-job"] = dict(
            resume_context=context,
            phase="patent",
            done=False,
            result=None,
            error=None,
            started_at=time.monotonic(),
        )
    monkeypatch.setattr(resume, "browser_workflow", lambda active: "saved-private-job")
    try:
        app = AppTest.from_file(str(APP), default_timeout=30).run()
        assert app.button(key="header_about")
        app.button(key="resume_previous_workflow").click().run()
        assert not app.exception
        assert app.session_state.analysis_workflow_id == "saved-private-job"
        assert app.session_state.raw == IDEA
        assert app.session_state.stage == 2
        assert app.button(key="rail_2")
        assert app.button(key="rail_3")
        button_keys = {button.key for button in app.button}
        assert not any(
            key in button_keys
            for key in ("nav_1", "nav_2", "nav_4", "subnav_2", "subnav_3")
        )
        assert "saved-private-job" in WORKFLOW_JOBS
    finally:
        with WORKFLOW_JOBS_LOCK:
            WORKFLOW_JOBS.pop("saved-private-job", None)


def test_unknown_tab_token_does_not_expose_other_users_job(monkeypatch):
    import frontend.workflow_resume as resume

    monkeypatch.setattr(resume, "browser_workflow", lambda active: "unknown-job")
    with WORKFLOW_JOBS_LOCK:
        WORKFLOW_JOBS["other-private-job"] = {
            "done": False,
            "resume_context": {"raw": "private"},
        }
    try:
        app = AppTest.from_file(str(APP), default_timeout=30).run()
        assert not app.exception
        assert not any(b.key == "resume_previous_workflow" for b in app.button)
    finally:
        with WORKFLOW_JOBS_LOCK:
            WORKFLOW_JOBS.pop("other-private-job", None)


def test_expired_finished_jobs_are_removed_without_removing_active_jobs():
    import time
    from frontend.workflow import prune_finished_jobs

    with WORKFLOW_JOBS_LOCK:
        WORKFLOW_JOBS["old-job"] = {"done": True, "updated_at": time.monotonic() - 1201}
        WORKFLOW_JOBS["active-job"] = {"done": False, "updated_at": 0}
    try:
        prune_finished_jobs()
        assert "old-job" not in WORKFLOW_JOBS
        assert "active-job" in WORKFLOW_JOBS
    finally:
        with WORKFLOW_JOBS_LOCK:
            WORKFLOW_JOBS.pop("old-job", None)
            WORKFLOW_JOBS.pop("active-job", None)


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
