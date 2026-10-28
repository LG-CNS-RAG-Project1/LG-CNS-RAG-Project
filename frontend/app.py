"""아이디어 초안 → 특허 비교 → 시장성 → 사업 실행 검토의 단계형 UI."""

import sys
import threading
import time
from uuid import uuid4
from copy import deepcopy
from pathlib import Path
import streamlit as st
from dotenv import load_dotenv

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
load_dotenv(Path(__file__).resolve().parents[1] / ".env")
from frontend.live import (
    COST_NOTE,
    FIELD_LABELS,
    LINK_LABELS,
    MAX_PASSWORD_FAILURES,
    PASSWORD_LOCK_SECONDS,
    PATENT_MODE_LABELS,
    RUN_LOCK,
    analysis_key,
    app_password,
    cost_markdown,
    cost_rows_list,
    friendly_error,
    live_available,
    password_matches,
    run_line,
)
from src.generation.input_guard import MAX_IDEA_CHARS, MIN_IDEA_CHARS
from frontend.quick import (
    ORIGIN_LABELS,
    DEMO_TEXT,
    DEMO_PARTS,
    candidates,
    validate_parts,
    selected_sources,
    report,
    DEMO_QUESTIONS,
    RELATIONS,
    validate_questions,
    validate_link,
    review_rows,
)
from frontend.workspace import EXAMPLE, empty_costs, cost_summary
from frontend.workflow import WORKFLOW_JOBS, WORKFLOW_JOBS_LOCK
from frontend.automatic import automatic_links
from frontend.presentation import hero_parts, brand_style
from frontend.workspace_view import report_payload, render_report, render_history

st.set_page_config(page_title="IdeaLens · 빠른 조사", page_icon="▤", layout="wide")
st.html("""<style>
    @keyframes idealens-spin { to { transform: rotate(360deg); } }
    .workflow-spinner { display:inline-block; width:.82em; height:.82em; border:2px solid #9aa8a4;
      border-top-color:#1f4943; border-radius:50%; animation:idealens-spin .8s linear infinite;
      vertical-align:-.08em; margin-right:.18em; }
    .patent-quote { border-left:4px solid #d4a72c; background:#fff8d8; padding:1rem 1.1rem;
      line-height:1.9; white-space:pre-wrap; overflow-wrap:anywhere; }
    .patent-quote mark { background:#ffec80; color:#1f302e; padding:.08em .12em; }
    </style>""")
st.html(Path(__file__).with_name("styles.css").read_text(encoding="utf-8"))
st.html(brand_style())
for key, value in {
    "stage": 1,
    "page": "home",
    "records": [],
    "raw": "",
    "research_title": "",
    "parts": [],
    "selected": [],
    "recent": [],
    "saved_memo": "",
    "report_snapshot": None,
    "version": 0,
    "questions": [],
    "links": {},
    "excluded_questions": [],
    "confirmed_context": False,
    "link_version": 0,
    "next_qid": 3,
    "idea_draft": None,
    "real_mode": False,
    "pipeline_result": None,
    "analysis_sources": None,
    "analysis_key": "",
    "workflow_cancelled": False,
    "technology_area_id": "SF-02",
    "cost_rows": empty_costs(),
}.items():
    if key not in st.session_state:
        st.session_state[key] = value
s = st.session_state


def password_gate():
    """IDEALENS_APP_PASSWORD가 설정된 배포에서는 비밀번호를 확인하기 전까지 화면을 그리지 않는다."""
    expected = app_password()
    if not expected or s.get("authenticated"):
        return
    st.title("IdeaLens")
    st.caption("접속 비밀번호를 입력해 주세요.")
    locked_until = s.get("auth_locked_until", 0)
    if time.time() < locked_until:
        st.error(
            f"비밀번호를 {MAX_PASSWORD_FAILURES}회 틀렸습니다. 잠시 후 다시 시도해 주세요."
        )
        st.stop()
    with st.form("password_form"):
        entered = st.text_input("비밀번호", type="password", key="app_password")
        submitted = st.form_submit_button("들어가기")
    if submitted:
        if password_matches(entered, expected):
            s.authenticated = True
            s.auth_failures = 0
            st.rerun()
        s.auth_failures = s.get("auth_failures", 0) + 1
        if s.auth_failures >= MAX_PASSWORD_FAILURES:
            s.auth_locked_until = time.time() + PASSWORD_LOCK_SECONDS
            s.auth_failures = 0
        st.error("비밀번호가 맞지 않습니다.")
    st.stop()


password_gate()


def invalidate_context():
    s.confirmed_context = False
    s.selected = []
    s.links = {}
    s.excluded_questions = []
    s.link_version += 1
    s.report_snapshot = None


def sync_context():
    parts = [s.get(f"part_{s.version}_{i}", p) for i, p in enumerate(s.parts)]
    questions = [
        dict(
            q,
            question=s.get(f"question_{s.version}_{q['id']}", q["question"]),
            condition=s.get(f"condition_{s.version}_{q['id']}", q["condition"]),
        )
        for q in s.questions
    ]
    if parts != s.parts or questions != s.questions:
        s.parts = parts
        s.questions = questions
        invalidate_context()


def input_changed():
    invalidate_context()
    s.idea_draft = None
    s.real_mode = False
    s.pipeline_result = None
    s.analysis_sources = None
    s.analysis_key = ""


def prepare_input():
    text = s.get("raw_input", s.raw).strip()
    title = s.get("title_input", s.research_title).strip()
    if len(text) < MIN_IDEA_CHARS:
        return False
    if text != s.raw or title != s.research_title or not s.parts:
        s.raw = text
        s.research_title = title
        s.parts = list(DEMO_PARTS) if text == DEMO_TEXT else [""]
        s.questions = (
            deepcopy(DEMO_QUESTIONS)
            if text == DEMO_TEXT
            else [{"id": "Q1", "question": "", "condition": ""}]
        )
        s.version += 1
        invalidate_context()
        s.memo = ""
        s.idea_draft = None
        s.real_mode = False
        s.pipeline_result = None
        s.analysis_sources = None
        s.analysis_key = ""
        s.saved_memo = ""
        item = {"text": text, "title": title}
        s.recent = [item] + [x for x in s.recent if x != item][:4]
    return True


def apply_complete_draft(draft):
    """완성된 초안으로 핵심 구성·기본 질문을 채우고 실제 분석 모드로 바꾼다."""
    from src.pipeline import default_questions

    s.real_mode = True
    s.pipeline_result = None
    s.parts = list(draft.technical_components) or [
        value for value in (draft.technology, draft.problem) if value.strip()
    ]
    s.questions = default_questions(draft)
    s.version += 1
    invalidate_context()


def make_ai_draft():
    from src.generation.idea_parser import parse_idea

    try:
        draft = parse_idea(s.get("raw_input", s.raw).strip())
        s.idea_draft = draft
        s.real_mode = False
        s.pipeline_result = None
        if draft.status == "complete":
            apply_complete_draft(draft)
            accept_draft_and_start()
        st.session_state.ai_draft_error = None
    except Exception as exc:
        st.session_state.ai_draft_error = friendly_error(exc)


def apply_ai_answers():
    from src.generation.idea_parser import apply_answers

    rounds = s.idea_draft.rounds
    answers = {
        field: st.session_state.get(f"ai_answer_{field}_{rounds}", "")
        for field in s.idea_draft.questions
    }
    try:
        s.idea_draft = apply_answers(s.idea_draft, answers)
        s.real_mode = False
        if s.idea_draft.status == "complete":
            apply_complete_draft(s.idea_draft)
            accept_draft_and_start()
        st.session_state.ai_draft_error = None
    except Exception as exc:
        st.session_state.ai_draft_error = friendly_error(exc)


def current_analysis_key():
    return analysis_key(s.idea_draft, s.parts, s.technology_area_id)


def run_real_pipeline():
    """조사(구성·분야가 같으면 재사용)와 질문 연결을 실행한다. 결과는 화면 호출 전에 세션에 저장한다."""
    from src.pipeline import analyze_sources, run_pipeline, screen_inputs

    if not RUN_LOCK.acquire(blocking=False):
        st.session_state.pipeline_error = (
            "다른 화면에서 분석이 진행 중입니다. 끝난 뒤 다시 실행해 주세요."
        )
        return
    s.running_since = time.time()
    try:
        questions = screen_inputs(s.parts, s.questions)
        key = current_analysis_key()
        if s.analysis_sources is None or s.analysis_key != key:
            s.analysis_sources = analyze_sources(
                s.idea_draft,
                technical_components=s.parts,
                technology_area_id=s.technology_area_id,
            )
            s.analysis_key = key
        s.pipeline_result = run_pipeline(
            s.idea_draft,
            questions,
            technical_components=s.parts,
            technology_area_id=s.technology_area_id,
            sources=s.analysis_sources,
        )
        st.session_state.pipeline_error = None
    except Exception as exc:
        from src.pipeline import LOG, redact

        LOG.warning("실제 분석 실패: %s", redact(f"{type(exc).__name__}: {exc}"))
        st.session_state.pipeline_error = friendly_error(exc)
    finally:
        s.running_since = None
        RUN_LOCK.release()


def _workflow_worker(job_id, draft_data, parts, questions, area, cached_sources):
    """분석을 백그라운드에서 수행하고 단계별 결과를 UI 폴링에 공개한다."""
    from src.pipeline import analyze_sources, redact, run_pipeline, screen_inputs

    with WORKFLOW_JOBS_LOCK:
        job = WORKFLOW_JOBS.get(job_id)
    if job is None:
        return
    if not RUN_LOCK.acquire(blocking=False):
        with WORKFLOW_JOBS_LOCK:
            job["error"] = "다른 분석이 진행 중입니다. 잠시 후 다시 시도해 주세요."
            job["phase"] = "failed"
            job["done"] = True
        return

    try:
        from src.schemas import IdeaDraft

        draft = IdeaDraft.model_validate(draft_data)
        screened_questions = screen_inputs(parts, questions)

        def publish(kind, report, run):
            with WORKFLOW_JOBS_LOCK:
                if job.get("cancelled"):
                    return
                job[f"{kind}_report"] = report
                job[f"{kind}_run"] = run
                job["phase"] = "market" if kind == "patent" else "final_report"
                job["updated_at"] = time.monotonic()

        sources = cached_sources
        if sources is None:
            sources = analyze_sources(
                draft,
                technical_components=parts,
                technology_area_id=area,
                progress_callback=publish,
            )
        else:
            publish("patent", sources.patent, sources.patent_run)
            publish("market", sources.market, sources.market_run)
        with WORKFLOW_JOBS_LOCK:
            if job.get("cancelled"):
                return
            job["sources"] = sources
            job["phase"] = "final_report"

        result = run_pipeline(
            draft,
            screened_questions,
            technical_components=parts,
            technology_area_id=area,
            sources=sources,
        )
        with WORKFLOW_JOBS_LOCK:
            if job.get("cancelled"):
                return
            job["result"] = result
            job["phase"] = "complete"
            job["done"] = True
            job["updated_at"] = time.monotonic()
    except Exception as exc:
        from src.pipeline import LOG

        message = redact(f"{type(exc).__name__}: {exc}")
        LOG.warning("단계별 실제 분석 실패: %s", message)
        with WORKFLOW_JOBS_LOCK:
            if job.get("cancelled"):
                return
            job["error"] = friendly_error(exc)
            job["phase"] = "failed"
            job["done"] = True
            job["updated_at"] = time.monotonic()
    finally:
        RUN_LOCK.release()


def start_report_workflow():
    """초안 확정 뒤 분석을 시작하고 특허 화면부터 순서대로 보여준다."""
    job_id = uuid4().hex
    key = current_analysis_key()
    cached_sources = (
        s.analysis_sources
        if s.analysis_sources is not None and s.analysis_key == key
        else None
    )
    with WORKFLOW_JOBS_LOCK:
        WORKFLOW_JOBS[job_id] = {
            "patent_report": None,
            "patent_run": None,
            "market_report": None,
            "market_run": None,
            "sources": cached_sources,
            "result": None,
            "error": None,
            "phase": "patent",
            "done": False,
            "updated_at": time.monotonic(),
            "started_at": time.monotonic(),
        }
    s.workflow_ready_key = (False, False)
    s.analysis_workflow_id = job_id
    s.workflow_cancelled = False
    s.analysis_key = key
    s.workflow_stage_entered_at = time.monotonic()
    s.workflow_patent_displayed_at = None
    s.workflow_auto_patent_advanced = False
    s.workflow_market_displayed_at = None
    s.pipeline_result = None
    s.stage = 2
    s.pipeline_error = None
    threading.Thread(
        target=_workflow_worker,
        args=(
            job_id,
            s.idea_draft.model_dump(),
            list(s.parts),
            deepcopy(s.questions),
            s.technology_area_id,
            cached_sources,
        ),
        daemon=True,
        name=f"idealens-workflow-{job_id[:8]}",
    ).start()


def cancel_report_workflow():
    """화면 전환 전 진행 중 상태를 취소 처리해 늦은 결과와 새 입력이 섞이지 않게 한다."""
    job_id = s.get("analysis_workflow_id")
    if job_id:
        with WORKFLOW_JOBS_LOCK:
            job = WORKFLOW_JOBS.get(job_id)
            if job is not None:
                job["cancelled"] = True
                job["done"] = True
                job["phase"] = "cancelled"
        s.analysis_workflow_id = None
        s.pipeline_result = None
        s.analysis_sources = None
        s.analysis_key = ""
        s.workflow_cancelled = True
        s.stage = 1


def accept_draft_and_start():
    """완성된 초안을 확정하고 특허 단계부터 자동 조사를 시작한다."""
    s.confirmed_context = True
    s.selected = [item["id"] for item in candidates(s.raw)]
    start_report_workflow()


def partial_workflow_result(job):
    """완료된 조사 영역을 기존 보고서 화면에서 표시할 임시 결과로 묶는다."""
    from src.pipeline import PartRun, PipelineReport
    from src.schemas import MarketReport, PatentReport

    patent = job.get("patent_report") or PatentReport(
        status="no_results", search_scope="특허 비교 보고서 생성 중"
    )
    market = job.get("market_report") or MarketReport(
        status="no_results", search_scope="시장성 보고서 생성 중"
    )
    return PipelineReport(
        status="partial",
        title=s.idea_draft.title,
        patent=patent,
        market=market,
        patent_run=job.get("patent_run") or PartRun(state="skipped"),
        market_run=job.get("market_run") or PartRun(state="skipped"),
    )


def current_workflow_job():
    job_id = s.get("analysis_workflow_id")
    if not job_id:
        return None
    with WORKFLOW_JOBS_LOCK:
        job = WORKFLOW_JOBS.get(job_id)
        return dict(job) if job else None


@st.fragment(run_every=1)
def workflow_progress_fragment():
    job_id = s.get("analysis_workflow_id")
    if not job_id:
        return
    with WORKFLOW_JOBS_LOCK:
        job = WORKFLOW_JOBS.get(job_id)
        if job is None:
            return
        snapshot = dict(job)

    if snapshot.get("cancelled"):
        return

    patent_ready = snapshot.get("patent_report") is not None
    market_ready = snapshot.get("market_report") is not None
    now = time.monotonic()
    phase = snapshot.get("phase", "patent")

    def report_state(report, run, active):
        if run and run.state in {"error", "timeout"}:
            return "실패"
        if report is not None:
            if report.status == "no_results":
                return "근거 부족"
            if report.status == "completed":
                return "완료"
            if report.status == "error" or (run and run.state in {"error", "timeout"}):
                return "실패"
            return "근거 부족"
        return "분석 중" if active else "대기"

    final_result = snapshot.get("result")
    if snapshot.get("error"):
        final_state = "실패"
    elif final_result is None:
        final_state = "작성 중" if phase == "final_report" else "대기"
    else:
        final_state = "완료" if final_result.status == "completed" else "일부 보류"

    steps = [
        ("입력 확정", "완료"),
        (
            "특허 조사",
            report_state(
                snapshot.get("patent_report"),
                snapshot.get("patent_run"),
                phase == "patent",
            ),
        ),
        (
            "시장 분석",
            report_state(
                snapshot.get("market_report"),
                snapshot.get("market_run"),
                phase == "market",
            ),
        ),
        ("보고서 작성", final_state),
    ]
    with st.container(border=True):
        columns = st.columns(4)
        for index, (column, (name, state)) in enumerate(zip(columns, steps), 1):
            column.caption(name)
            active = (
                (index == 2 and phase == "patent" and not patent_ready)
                or (index == 3 and phase == "market" and not market_ready)
                or (index == 4 and phase == "final_report" and final_result is None)
            )
            marker = (
                '<span class="workflow-spinner" aria-label="분석 중"></span> '
                if active
                else ""
            )
            column.markdown(f"{marker}**{state}**", unsafe_allow_html=True)

    if snapshot.get("error"):
        s.pipeline_error = snapshot["error"]
        s.analysis_sources = snapshot.get("sources")
        if snapshot.get("patent_report") or snapshot.get("market_report"):
            s.pipeline_result = partial_workflow_result(snapshot)
        s.stage = 4
        s.analysis_workflow_id = None
        with WORKFLOW_JOBS_LOCK:
            WORKFLOW_JOBS.pop(job_id, None)
        st.rerun(scope="app")

    if snapshot.get("result") is not None:
        s.pipeline_result = snapshot["result"]
        s.analysis_sources = snapshot.get("sources")
        s.analysis_workflow_id = None
        with WORKFLOW_JOBS_LOCK:
            WORKFLOW_JOBS.pop(job_id, None)
        st.rerun(scope="app")
    ready_key = (patent_ready, market_ready)
    if ready_key != s.get("workflow_ready_key") and any(ready_key):
        s.workflow_ready_key = ready_key
        s.pipeline_result = partial_workflow_result(snapshot)
        st.rerun(scope="app")

    if not snapshot.get("done"):
        messages = {
            "patent": "특허 문헌과 청구항에서 아이디어 구성요소의 유사점·차이점을 확인하고 있습니다.",
            "market": "특허 비교가 끝났습니다. 목표 고객·수요·도입 장벽에 관한 시장 근거를 분석하고 있습니다.",
            "final_report": "두 조사가 끝났습니다. 핵심 근거와 다음 행동을 묶어 최종 검토를 작성하고 있습니다.",
        }
        st.info(messages.get(phase, "보고서를 준비하고 있습니다."))
        elapsed = max(0, int(now - snapshot.get("started_at", now)))
        st.caption(
            f"현재 단계: {steps[{ 'patent': 1, 'market': 2, 'final_report': 3 }.get(phase, 0)][0]} · "
            f"진행 시간 {elapsed // 60}분 {elapsed % 60}초"
        )
        st.caption(
            "새 입력이 분석 결과에 섞이지 않도록 입력은 잠겨 있습니다. 이전 완료 단계는 상단 메뉴에서 다시 볼 수 있습니다."
        )
        if st.button("분석 취소하고 아이디어 수정", key=f"cancel_workflow_{job_id}"):
            cancel_report_workflow()
            st.rerun(scope="app")


def render_patent_report(patent):
    """특허 화면에는 핵심 대응을 우선 표시하고 원문·전체 비교는 접는다."""
    from src.generation.report_builder import escape_md, patent_location, safe_url

    if patent.status == "error":
        st.error(patent.error_message or "특허 조사에 실패했습니다.")
    elif patent.status == "no_results":
        st.warning(
            "검색 범위에서 특허 근거를 찾지 못했습니다. 위험이 없다는 뜻은 아닙니다."
        )

    precheck = patent.patentability_precheck
    precheck_labels = {
        "overlap_concern": "유사 청구항 주의",
        "potentially_distinct": "차별 구성 신호",
        "insufficient_evidence": "판단 근거 부족",
    }
    if precheck and precheck.citation_ids:
        st.subheader("등록 가능성 예비 신호")
        st.info(f"{precheck_labels[precheck.status]} · {precheck.summary}")
        st.caption("검색된 자료를 바탕으로 한 예비 비교이며, 법률 의견이 아닙니다.")
    elif precheck:
        st.warning(
            "등록 가능성 예비 신호에 연결된 특허 인용이 없어 결론을 표시하지 않습니다."
        )

    relevance_labels = {
        "high": "높음",
        "medium": "보통",
        "low": "낮음",
        "insufficient": "근거 부족",
    }
    comparison_labels = {
        "overlap": "직접 대응",
        "partial": "부분 대응",
        "different": "차이 확인",
        "not_found": "제공 근거에서 미발견",
        "uncertain": "근거 부족",
    }
    from src.generation.patent_analysis import (
        PATENT_PRIORITY_LABELS,
        patent_review_priority,
    )

    reviews = sorted(patent.patent_reviews, key=patent_review_priority)[:5]
    for review in reviews:
        with st.container(border=True):
            st.subheader(
                f"{review.title} · {PATENT_PRIORITY_LABELS[patent_review_priority(review)]} · 관련성 {relevance_labels[review.relevance]}"
            )
            if review.overall_summary and review.citation_ids:
                st.write(review.overall_summary)
            elif review.overall_summary:
                st.caption("특허별 요약에 연결된 원문 인용이 없습니다.")
            if review.relevance_reason and review.citation_ids:
                st.caption(review.relevance_reason)

            comparisons = sorted(
                review.component_comparisons,
                key=lambda item: {
                    "overlap": 0,
                    "partial": 1,
                    "uncertain": 2,
                    "different": 3,
                    "not_found": 4,
                }[item.status],
            )
            for item in comparisons[:3]:
                display_status = item.status if item.citation_ids else "uncertain"
                refs = (
                    ", ".join(f"P:{cid}" for cid in item.citation_ids)
                    or "근거 없음·판단 보류"
                )
                st.markdown(
                    f"- **{escape_md(item.idea_component)}** · {comparison_labels[display_status]} ({refs})"
                )
                detail = (
                    " · ".join(
                        value
                        for value in (item.overlap, item.difference, item.uncertainty)
                        if value
                    )
                    if item.citation_ids
                    else "인용 근거가 없어 유사·차이 판단을 보류합니다."
                )
                if detail:
                    st.caption(detail)
                citation_id = next(
                    (
                        cid
                        for cid in item.citation_ids
                        if any(ev.citation_id == cid for ev in patent.evidence)
                    ),
                    None,
                )
                if citation_id is not None:
                    evidence = next(
                        ev for ev in patent.evidence if ev.citation_id == citation_id
                    )
                    if st.button(
                        f"P:{citation_id} 근거 원문 확인",
                        key=f"patent_evidence_{review.patent_id}_{item.component_id}_{citation_id}",
                    ):
                        patent_evidence_dialog(
                            evidence.model_dump(),
                            item.idea_component,
                            item.overlap or item.difference or item.uncertainty,
                            item.matched_text,
                        )

            with st.expander("전체 구성 비교와 청구항 원문"):
                rows = [
                    {
                        "아이디어 구성": item.idea_component,
                        "비교": comparison_labels[
                            item.status if item.citation_ids else "uncertain"
                        ],
                        "공통점": item.overlap if item.citation_ids else "",
                        "차이점": item.difference if item.citation_ids else "",
                        "근거": ", ".join(f"P:{cid}" for cid in item.citation_ids),
                        "미확인": item.uncertainty
                        or ("비교 인용 근거 없음" if not item.citation_ids else ""),
                    }
                    for item in review.component_comparisons
                ]
                if rows:
                    st.dataframe(rows, width="stretch", hide_index=True)
                citation_ids = list(
                    dict.fromkeys(
                        review.citation_ids
                        + [
                            cid
                            for item in review.component_comparisons
                            for cid in item.citation_ids
                        ]
                    )
                )
                for citation_id in citation_ids:
                    evidence = next(
                        (
                            item
                            for item in patent.evidence
                            if item.citation_id == citation_id
                        ),
                        None,
                    )
                    if not evidence:
                        continue
                    st.markdown(f"**P:{citation_id} · {patent_location(evidence)}**")
                    st.caption(
                        f"{evidence.title} · 출원일 {evidence.application_date or '미확인'}"
                    )
                    st.text(evidence.quote)
                    if safe_url(evidence.source_url):
                        st.link_button("특허 원문 열기", safe_url(evidence.source_url))
                for item in review.watchouts:
                    st.warning(item)
                for item in review.unknowns:
                    st.caption(f"미확인: {item}")

    if (
        precheck
        and precheck.citation_ids
        and (
            precheck.distinction_hypotheses
            or precheck.expert_questions
            or precheck.limitations
        )
    ):
        with st.expander("차별점 가설·전문가 확인사항"):
            for item in precheck.distinction_hypotheses:
                st.write(f"차별점 가설: {item}")
            for item in precheck.expert_questions:
                st.write(f"전문가 확인: {item}")
            for item in precheck.limitations:
                st.caption(f"한계: {item}")

    if patent.unknowns:
        with st.expander(f"특허 검색 미확인 사항 ({len(patent.unknowns)}건)"):
            for item in patent.unknowns:
                st.write(f"- {item}")
    if not patent.patent_reviews and patent.comparisons:
        with st.expander("특허별 비교 및 원문"):
            for comparison in patent.comparisons[:10]:
                evidence = next(
                    (
                        item
                        for item in patent.evidence
                        if item.citation_id == comparison.citation_id
                    ),
                    None,
                )
                st.write(
                    f"P:{comparison.citation_id} · {comparison.similarity} · 차이: {comparison.difference}"
                )
                if evidence:
                    st.text(evidence.quote)


@st.dialog("특허 근거 원문", width="large")
def patent_evidence_dialog(evidence_data, component, explanation, matched_text=""):
    """원문 발췌와 비교 지점을 이스케이프 후 강조해 모달로 표시한다."""
    from src.generation.report_builder import patent_location, safe_url
    from src.generation.patent_analysis import highlight_verbatim_excerpt
    from src.schemas import PatentEvidence

    evidence = PatentEvidence.model_validate(evidence_data)
    st.caption(
        f"P:{evidence.citation_id} · {evidence.title} · {patent_location(evidence)}"
    )
    st.write(f"대응 아이디어 구성: **{component}**")
    if explanation:
        st.write(f"비교 판단: {explanation}")
    if matched_text:
        st.caption(
            "아래는 검색·분석에 사용된 특허 원문 발췌입니다. 노란색 구절은 분석기가 인용문에서 그대로 지정한 대응 문구이며, 전체 문서는 출처 링크에서 확인하세요."
        )
    else:
        st.caption(
            "아래는 검색·분석에 사용된 특허 원문 발췌입니다. 분석기가 정확한 대응 구절을 지정하지 않아 자동 강조는 없습니다. 전체 문서는 출처 링크에서 확인하세요."
        )
    escaped = highlight_verbatim_excerpt(evidence.quote, matched_text)
    st.markdown(
        '<div class="patent-quote">' + escaped + "</div>",
        unsafe_allow_html=True,
    )
    if safe_url(evidence.source_url):
        st.link_button("공식 특허 원문 열기", safe_url(evidence.source_url))
    else:
        st.info("안전한 원문 링크가 없어 검색된 발췌만 표시합니다.")


def render_market_report(market, draft=None):
    """시장성 화면에는 고객 신호와 다음 검증을 우선 표시하고 상세 자료를 접는다."""
    if market.status == "error":
        st.error(market.error_message or "시장 조사에 실패했습니다.")
    elif market.status == "no_results":
        st.warning(
            "검색 범위에서 시장 근거를 찾지 못했습니다. 수요가 없다는 뜻은 아닙니다."
        )

    review = market.opportunity_review
    labels = {
        "validated_demand": "직접 고객 검증 자료 있음",
        "buyer_signals": "구매자 신호",
        "indirect_signals": "간접 산업 신호",
        "insufficient_evidence": "근거 부족",
    }
    if review:
        st.subheader("사업 승인 관점 요약")
        st.info(
            f"{labels[review.status]} · 목표 고객: {review.target_segment or '미확인'}"
        )
        if review.status in {"buyer_signals", "indirect_signals"}:
            st.caption("기업·뉴스 자료의 산업 신호는 실제 구매 의사 검증과 구분됩니다.")
        if review.value_hypotheses:
            st.markdown("**검증 전 가치 가설**")
            for hypothesis in review.value_hypotheses[:2]:
                st.markdown(f"- {hypothesis}")
        if draft:
            st.markdown("**고객·업무 적합성**")
            c1, c2 = st.columns(2)
            c1.write(f"**사용자 후보**\n\n{draft.customers or '미확인'}")
            c2.write("**구매자·예산 주체**\n\n근거 자료에서 구분 확인 필요")
            st.caption(
                f"문제: {draft.problem or '미확인'} · 현재 대안: {draft.current_alternative or '미확인'}"
            )
            st.caption(
                f"과금 가설: {draft.revenue or '미확인'} · 전환 이유: {draft.difference or '미확인'}"
            )
        if review.reasons:
            st.markdown("**사업 판단에 참고할 시장 신호**")
            for item in review.reasons[:2]:
                refs = (
                    ", ".join(f"M:{cid}" for cid in item.citation_ids)
                    or "근거 인용 없음"
                )
                st.markdown(f"- **{item.topic}:** {item.statement} ({refs})")
        if review.validation_actions:
            st.markdown("**다음 검증 행동**")
            for action in review.validation_actions[:3]:
                st.markdown(
                    f"- **{action.title} · {action.target or '대상 미정'}:** {action.method}"
                )
                st.caption(f"성공 신호: {action.success_signal}")
    elif market.status == "completed":
        st.info("아이디어별 구매 수요 결론은 확보한 자료에서 확인되지 않았습니다.")

    if market.dimensions:
        from src.retrieval.market_relevance import DIMENSION_LABELS

        verdict_labels = {
            "confirmed": "근거 확인",
            "signal_only": "산업 신호",
            "unverified": "미확인",
        }
        key_dimensions = ["demand", "buyer", "competition", "price", "adoption_barrier"]
        for key in key_dimensions:
            dimension = next(
                (item for item in market.dimensions if item.dimension == key), None
            )
            if not dimension:
                continue
            st.markdown(
                f"**{DIMENSION_LABELS[key]} · {verdict_labels[dimension.verdict]}**"
            )
            if dimension.claims:
                for claim in dimension.claims[:1]:
                    label = {
                        "fact": "자료 사실",
                        "user_claim": "입력 내용",
                        "ai_hypothesis": "검증 전 해석",
                    }[claim.claim_type]
                    citations = (
                        ", ".join(f"M:{cid}" for cid in claim.citation_ids)
                        or "인용 근거 없음"
                    )
                    st.markdown(f"- [{label}] {claim.statement} ({citations})")
            else:
                st.caption(dimension.next_check or "검증 자료가 없습니다.")

    if market.dimensions or market.evidence:
        from src.generation.market_markdown import market_report_to_markdown

        with st.expander(f"시장 차원별 분석·기사 목록·원문 ({len(market.evidence)}건)"):
            st.markdown(market_report_to_markdown(market, heading_level=3))
            from src.generation.report_builder import escape_md, safe_url

            for item in market.evidence:
                st.markdown(f"**M:{item.citation_id} · {escape_md(item.title)}**")
                st.caption(
                    f"{item.publisher} · {item.published_at or '발행일 미확인'} · "
                    f"{item.evidence_nature} · 신뢰도 {item.reliability}"
                )
                st.write(item.quote)
                if safe_url(item.url):
                    st.link_button("시장 원문 열기", safe_url(item.url))
    if market.unknowns:
        with st.expander(f"시장 미확인 사항 ({len(market.unknowns)}건)"):
            for item in market.unknowns:
                st.write(f"- {item}")


def effective_links():
    generated = automatic_links(s.raw, s.parts, s.selected, s.questions)
    result = {
        qid: link for qid, link in generated.items() if qid not in s.excluded_questions
    }
    for qid in s.excluded_questions:
        result[qid] = dict(
            origin="excluded",
            relation="연결 판단 보류",
            reason="사용자가 보고서 연결 검토에서 제외한 질문입니다.",
        )
    result.update(s.links)
    return result


def snapshot():
    s.report_snapshot = {
        "raw": s.raw,
        "title": s.research_title,
        "parts": list(s.parts),
        "ids": list(s.selected),
        "questions": deepcopy(s.questions),
        "links": deepcopy(effective_links()),
        "sources": deepcopy(selected_sources(s.raw, s.selected)),
    }


def can_visit(number):
    job = current_workflow_job() if s.get("analysis_workflow_id") else None
    if job:
        if number == s.stage:
            return True
        if number == 1:
            return True
        if number == 2:
            return job.get("patent_report") is not None
        if number == 3:
            return job.get("market_report") is not None
        if number == 4:
            return job.get("result") is not None
    if number == 1:
        return True
    if number == 2:
        return s.confirmed_context
    if not s.confirmed_context:
        return False
    if number == 3:
        return not s.real_mode or s.pipeline_result is not None
    if number == 4:
        if s.real_mode:
            return s.pipeline_result is not None
        return (
            s.report_snapshot is not None
            or len(selected_sources(s.raw, s.selected)) >= 2
        )
    return False


def navigate(number):
    s.page = "workspace"
    sync_context()
    if not can_visit(number):
        return
    if number == 2 and not s.get("analysis_workflow_id") and not prepare_input():
        return
    if s.get("analysis_workflow_id") and number in (2, 3):
        job = current_workflow_job()
        if job:
            s.pipeline_result = partial_workflow_result(job)
    if s.get("analysis_workflow_id") and number == 4:
        workflow_id = s.analysis_workflow_id
        job = current_workflow_job()
        if job and job.get("result") is not None:
            s.pipeline_result = job["result"]
            s.analysis_sources = job.get("sources")
            s.analysis_workflow_id = None
            with WORKFLOW_JOBS_LOCK:
                WORKFLOW_JOBS.pop(workflow_id, None)
    if number == 4:
        snapshot()
    s.stage = number


def load(text, title=""):
    s.raw_input = text
    s.title_input = title
    prepare_input()
    invalidate_context()
    s.stage = 1


def add_question():
    sync_context()
    s.questions.append({"id": f"Q{s.next_qid}", "question": "", "condition": ""})
    s.next_qid += 1
    s.version += 1
    invalidate_context()


def remove_question(qid):
    sync_context()
    s.questions = [q for q in s.questions if q["id"] != qid]
    s.version += 1
    invalidate_context()


def edit_part(index, direction):
    sync_context()
    values = [s.get(f"part_{s.version}_{i}", p) for i, p in enumerate(s.parts)]
    if direction == 0:
        values.pop(index)
    else:
        target = index + direction
        values[index], values[target] = values[target], values[index]
    s.parts = values
    s.version += 1
    invalidate_context()


def add_part():
    sync_context()
    s.parts = [s.get(f"part_{s.version}_{i}", p) for i, p in enumerate(s.parts)] + [""]
    s.version += 1
    invalidate_context()


def select(source_id):
    s.selected = (
        [i for i in s.selected if i != source_id]
        if source_id in s.selected
        else s.selected + [source_id]
    )
    s.link_version += 1
    s.report_snapshot = None


if s.stage in (3, 4) and not s.confirmed_context:
    s.stage = 1


def save_memo():
    s.saved_memo = s.memo


def restore_link(qid):
    s.links.pop(qid, None)
    s.excluded_questions = [i for i in s.excluded_questions if i != qid]
    s.link_version += 1
    s.report_snapshot = None


def drop_link(qid):
    s.links.pop(qid, None)
    s.excluded_questions = list(set(s.excluded_questions + [qid]))
    s.link_version += 1
    s.report_snapshot = None


def open_page(page):
    s.page = page


def start_research():
    s.page = "workspace"
    s.stage = 1


with st.container(key="brandbar"):
    brand, intro, guide, records = st.columns([2.6, 1, 1, 1.1])
    brand.button(
        "IdeaLens", key="home", on_click=open_page, args=("home",), help="홈으로"
    )
    intro.button("서비스 소개", on_click=open_page, args=("about",))
    guide.button("왜 IdeaLens인가", on_click=open_page, args=("difference",))
    records.button("내 기록", on_click=open_page, args=("history",))

if s.page == "home":
    play_intro = not s.get("home_intro_played", False)
    with st.container(key="landing"):
        copy_markup, art_markup = hero_parts()
        copy_column, art_column = st.columns(
            [1, 1.08], gap="large", vertical_alignment="center"
        )
        with copy_column:
            st.html(copy_markup)
        with art_column:
            with st.container(key="hero_art"):
                st.html(art_markup)
                st.button(
                    "돋보기로 조사 시작",
                    key="lens_start",
                    type="primary",
                    help="돋보기를 클릭하거나 Enter 키를 눌러 아이디어 조사를 시작하세요.",
                    on_click=start_research,
                )
    if play_intro:
        from frontend.landing_motion import intro_markup

        st.html(intro_markup(), unsafe_allow_javascript=True)
        s.home_intro_played = True
    st.stop()
if s.page in ("about", "difference"):
    from frontend.introduction import render_introduction

    render_introduction(s.page)
    st.button("홈에서 살펴보기 ↗", on_click=open_page, args=("home",))
    st.stop()
if s.page == "history":
    render_history(s)
    st.stop()

steps = ["아이디어 구체화", "특허 비교", "시장성 분석", "종합 보고서"]
with st.container(key="stepnav"):
    for number, label, column in zip(
        [1, 2, 4],
        ["1 아이디어 구체화", "2 특허·시장 검토", "3 종합 보고서"],
        st.columns(3),
    ):
        column.button(
            label,
            key=f"nav_{number}",
            type=(
                "primary"
                if (s.stage in (2, 3) if number == 2 else s.stage == number)
                else "secondary"
            ),
            disabled=not can_visit(number),
            on_click=navigate,
            args=(number,),
            width="stretch",
        )
if s.stage in (2, 3):
    a, b = st.columns(2)
    a.button(
        "특허 비교",
        key="review_patent",
        type="primary" if s.stage == 2 else "secondary",
        disabled=not can_visit(2),
        on_click=navigate,
        args=(2,),
        width="stretch",
    )
    b.button(
        "시장성 분석",
        key="review_market",
        type="primary" if s.stage == 3 else "secondary",
        disabled=not can_visit(3),
        on_click=navigate,
        args=(3,),
        width="stretch",
    )
active_job = current_workflow_job() if s.get("analysis_workflow_id") else None
if active_job:
    active_phase = active_job.get("phase", "patent")
    active_names = {
        "patent": "특허 비교",
        "market": "시장성 분석",
        "final_report": "최종 검토 작성",
    }
    popover_title = (
        "분석 완료 · 결과 바로가기"
        if active_job.get("done")
        else f"분석 중 · {active_names.get(active_phase, '결과 정리')}"
    )
    with st.popover(popover_title):
        if active_job.get("done"):
            st.write("분석이 끝났습니다. 확인할 단계를 선택하세요.")
        else:
            st.markdown(
                '<span class="workflow-spinner"></span> **분석 작업은 계속 진행 중입니다.**',
                unsafe_allow_html=True,
            )
            st.caption("열람할 단계를 선택해도 백그라운드 분석은 계속됩니다.")
        job_steps = [
            ("완료", True),
            (
                (
                    "완료"
                    if active_job.get("patent_report")
                    else ("분석 중" if active_phase == "patent" else "대기")
                ),
                can_visit(2),
            ),
            (
                (
                    "완료"
                    if active_job.get("market_report")
                    else ("분석 중" if active_phase == "market" else "대기")
                ),
                can_visit(3),
            ),
            (
                (
                    "완료"
                    if active_job.get("result")
                    else ("작성 중" if active_phase == "final_report" else "대기")
                ),
                can_visit(4),
            ),
        ]
        for number, (label, (state_label, available)) in enumerate(
            zip(steps, job_steps), 1
        ):
            if number == s.stage:
                st.button(
                    f"현재 화면 · {number} {label} · {state_label}",
                    disabled=True,
                    key=f"workflow_pop_current_{number}",
                )
            else:
                st.button(
                    f"{number} {label} · {state_label} · 열기",
                    key=f"workflow_pop_{number}",
                    disabled=not available,
                    on_click=navigate,
                    args=(number,),
                )
if not s.confirmed_context and s.raw:
    st.caption(
        "입력·구성을 바꾼 경우 아이디어 구체화에서 다시 확정해야 조사와 보고서를 볼 수 있습니다."
    )

if s.stage == 1:
    if s.get("workflow_cancelled"):
        st.info(
            "이전 분석은 취소했습니다. 입력을 수정하고 새 분석을 시작할 수 있습니다."
        )
        if RUN_LOCK.locked():
            st.caption(
                "이미 외부로 전송된 분석 요청은 즉시 중단되지 않을 수 있습니다. 요청이 끝난 뒤 다시 분석할 수 있으며, 해당 호출의 비용은 발생할 수 있습니다."
            )
        s.workflow_cancelled = False
previous_stage = s.get("displayed_stage", s.stage)
if previous_stage != s.stage:
    s.turn_direction = "forward" if s.stage > previous_stage else "backward"
s.displayed_stage = s.stage
direction = s.get("turn_direction", "still")
with st.container(key=f"workspace_{1 if s.stage == 1 else 3 if s.stage == 4 else 2}"):
    st.html(
        f'<div class="page-folio">RESEARCH NOTE / {1 if s.stage == 1 else 3 if s.stage == 4 else 2:02d} — 03 · {steps[s.stage - 1]}</div>'
    )
    if s.get("analysis_workflow_id"):
        workflow_progress_fragment()
    elif s.real_mode and s.pipeline_result:
        with st.container(border=True):
            patent_state, market_state, final_state = st.columns(3)
            patent_state.caption(run_line("특허 조사", s.pipeline_result.patent_run))
            market_state.caption(run_line("시장 분석", s.pipeline_result.market_run))
            final_state.caption(
                "보고서 작성 · "
                + ("완료" if s.pipeline_result.status == "completed" else "일부 보류")
                if s.pipeline_result.markdown
                else "보고서 작성 · 미완료"
            )
    if s.stage == 1:
        st.html('<div id="idea-input" class="sheet-label">01 / 아이디어 노트</div>')
        s.setdefault("raw_input", s.raw)
        s.setdefault("title_input", s.research_title)
        st.title("어떤 아이디어를 조사할까요?")
        st.caption(
            "한두 문장으로 시작하면 AI가 내용을 정리하고 특허·시장·최종 보고서까지 순서대로 진행합니다."
        )
        main, recent = st.columns([2.4, 1], gap="large")
        with main:
            with st.container(border=True):
                st.text_input(
                    "아이디어 명칭 (선택)",
                    max_chars=100,
                    key="title_input",
                    on_change=input_changed,
                    disabled=bool(s.get("analysis_workflow_id")),
                )
                raw = st.text_area(
                    "아이디어 내용",
                    height=300,
                    max_chars=MAX_IDEA_CHARS,
                    key="raw_input",
                    on_change=input_changed,
                    disabled=bool(s.get("analysis_workflow_id")),
                    placeholder="해결하려는 문제, 핵심 기술과 동작 방식, 예상 효과를 자유롭게 적어 주세요.",
                )
                st.caption(
                    f"{len(raw):,} / {MAX_IDEA_CHARS:,}자 · 최소 {MIN_IDEA_CHARS}자"
                )
                a, b = st.columns(2)
                a.button(
                    "입력 템플릿",
                    on_click=load,
                    args=("해결할 문제:\n\n핵심 아이디어와 동작 방식:\n\n예상 효과:",),
                    disabled=bool(s.get("analysis_workflow_id")),
                )
                b.button(
                    "예시 불러오기",
                    on_click=load,
                    args=(DEMO_TEXT, EXAMPLE["idea"]),
                    disabled=bool(s.get("analysis_workflow_id")),
                )
                st.selectbox(
                    "특허 색인 분야",
                    ["SF-02", "SF-05"],
                    format_func=lambda key: (
                        "SF-02 · AI 비전 품질검사"
                        if key == "SF-02"
                        else "SF-05 · 지능형 공정제어"
                    ),
                    key="technology_area_id",
                    disabled=bool(s.get("analysis_workflow_id")),
                )
                if st.session_state.get("ai_draft_error"):
                    st.error(st.session_state.ai_draft_error)
                if s.idea_draft is not None:
                    draft = s.idea_draft
                    if draft.status == "rejected":
                        st.warning(draft.rejection_reason)
                    elif draft.status == "needs_input":
                        st.info(
                            "더 정확한 검색을 위해 빠진 항목을 물어봅니다. 모르면 비워 두고 초안을 확정할 수 있습니다."
                        )
                        with st.form("ai_followup_form"):
                            for field, question in draft.questions.items():
                                st.text_input(
                                    question, key=f"ai_answer_{field}_{draft.rounds}"
                                )
                            st.form_submit_button(
                                "답변 반영",
                                on_click=apply_ai_answers,
                                disabled=bool(s.get("analysis_workflow_id")),
                            )
                        if st.button(
                            "모르는 항목은 미확인으로 두고 계속",
                            key="confirm_unknowns",
                            disabled=bool(s.get("analysis_workflow_id")),
                        ):
                            from src.generation.idea_parser import confirm_unknowns

                            s.idea_draft = confirm_unknowns(draft)
                            apply_complete_draft(s.idea_draft)
                            accept_draft_and_start()
                            st.rerun()
                    if s.idea_draft.status == "complete":
                        draft = s.idea_draft
                        st.success(
                            "초안이 준비됐습니다. 아래 내용을 확인하고 수정한 뒤 확정하세요."
                        )
                        with st.form("idea_draft_editor"):
                            title_value = st.text_input(
                                "아이디어 이름",
                                value=draft.title,
                                key=f"draft_title_{s.version}",
                                disabled=bool(s.get("analysis_workflow_id")),
                            )
                            values = {}
                            labels = {
                                "problem": "해결할 문제",
                                "technology": "핵심 기술",
                                "customers": "목표 고객",
                                "difference": "차별점",
                                "revenue": "수익모델",
                                "current_alternative": "현재 대안",
                                "target_segment": "목표 세그먼트",
                            }
                            for field, label in labels.items():
                                values[field] = st.text_area(
                                    label,
                                    value=getattr(draft, field),
                                    key=f"draft_{field}_{s.version}",
                                    height=68,
                                    disabled=bool(s.get("analysis_workflow_id")),
                                )
                            components = st.text_area(
                                "기술 구성요소 (한 줄에 하나씩, 최대 7개)",
                                value="\n".join(draft.technical_components),
                                key=f"draft_components_{s.version}",
                                height=100,
                                disabled=bool(s.get("analysis_workflow_id")),
                            )
                            hypotheses = st.text_area(
                                "검증 전 가치 가설 (한 줄에 하나씩)",
                                value="\n".join(draft.value_hypotheses),
                                key=f"draft_hypotheses_{s.version}",
                                height=80,
                                disabled=bool(s.get("analysis_workflow_id")),
                            )
                            if st.form_submit_button(
                                "초안 확정하고 전체 보고서 만들기 →",
                                type="primary",
                                disabled=bool(s.get("analysis_workflow_id")),
                            ):
                                component_values = [
                                    x.strip()
                                    for x in components.splitlines()
                                    if x.strip()
                                ][:7]
                                hypothesis_values = [
                                    x.strip()
                                    for x in hypotheses.splitlines()
                                    if x.strip()
                                ][:3]
                                labels = {
                                    **FIELD_LABELS,
                                    "current_alternative": "현재 대안",
                                    "target_segment": "목표 세그먼트",
                                    "technical_components": "기술 구성요소",
                                    "value_hypotheses": "가치 가설",
                                }
                                values = {
                                    field: value.strip()
                                    for field, value in values.items()
                                }
                                sources = dict(draft.field_sources)
                                unknowns = list(draft.unknowns)
                                edited_fields = {
                                    **values,
                                    "technical_components": component_values,
                                    "value_hypotheses": hypothesis_values,
                                }
                                for field, value in edited_fields.items():
                                    if (
                                        value != getattr(draft, field)
                                        or field not in sources
                                    ):
                                        sources[field] = (
                                            "user_answer" if value else "unknown"
                                        )
                                    label = labels[field]
                                    if value:
                                        unknowns = [
                                            item for item in unknowns if item != label
                                        ]
                                    elif (
                                        sources.get(field) == "unknown"
                                        and label not in unknowns
                                    ):
                                        unknowns.append(label)
                                updated = type(draft).model_validate(
                                    {
                                        **draft.model_dump(),
                                        **values,
                                        "title": title_value.strip(),
                                        "technical_components": component_values,
                                        "value_hypotheses": hypothesis_values,
                                        "field_sources": sources,
                                        "unknowns": unknowns,
                                    }
                                )
                                s.idea_draft = updated
                                apply_complete_draft(updated)
                                s.confirmed_context = True
                                s.selected = [item["id"] for item in candidates(s.raw)]
                                start_report_workflow()
                                st.rerun()
                elif (not live_available() or s.raw == DEMO_TEXT) and s.raw.strip():
                    if s.raw == DEMO_TEXT and live_available():
                        st.info(
                            "예시 아이디어는 기본적으로 가상 자료로 시연합니다. 실제 AI 분석을 원하면 아래 버튼을 누르세요."
                        )
                        if st.button(
                            "이 예시를 실제 AI로 분석 · API 비용 발생",
                            key="analyze_example_live",
                        ):
                            with st.spinner("AI가 예시 아이디어를 구조화하는 중…"):
                                make_ai_draft()
                            st.rerun()
                    else:
                        st.info(
                            "실제 AI 분석 키가 없어 시연 경로입니다. 아래 핵심 구성을 직접 확인해 주세요."
                        )
                    manual_components = st.text_area(
                        "핵심 구성요소 (한 줄에 하나씩)",
                        value="\n".join(s.parts or [s.raw]),
                        key="manual_components",
                        height=130,
                    )
                    if st.button(
                        "구성 확정하고 특허 비교로 →",
                        type="primary",
                        width="stretch",
                    ):
                        parts = [
                            x.strip()
                            for x in manual_components.splitlines()
                            if x.strip()
                        ][:7]
                        error = validate_parts(parts)
                        if error:
                            st.error(error)
                        else:
                            s.parts = parts
                            s.questions = deepcopy(DEMO_QUESTIONS)
                            s.confirmed_context = True
                            s.selected = [item["id"] for item in candidates(s.raw)]
                            s.stage = 2
                            st.rerun()
                elif s.idea_draft is None:
                    if st.button(
                        "아이디어 구조화·전체 보고서 시작 · API 비용 발생",
                        type="primary",
                        width="stretch",
                    ):
                        if len(raw.strip()) < MIN_IDEA_CHARS:
                            st.error(
                                f"아이디어 내용을 {MIN_IDEA_CHARS}자 이상 입력해 주세요."
                            )
                        elif live_available() and raw != DEMO_TEXT:
                            prepare_input()
                            with st.spinner("AI가 아이디어를 구조화하는 중…"):
                                make_ai_draft()
                            st.rerun()
                        else:
                            prepare_input()
                            st.rerun()
            st.caption(
                "키가 있으면 버튼 한 번으로 초안 작성, 특허 조사, 시장성 분석, 최종 보고서를 차례로 진행합니다."
                " 빠진 정보가 있으면 먼저 짧게 질문합니다. 키가 없으면 가상 시연으로 표시합니다."
            )
            if s.idea_draft is not None and s.idea_draft.status == "complete":
                st.caption("초안 검토·수정이 필요하면 상단 1단계로 돌아오세요.")
        with recent:
            st.subheader("최근 입력 내용")
            st.caption("현재 세션에서만 보관합니다.")
            if not s.recent:
                st.info("입력한 아이디어를 여기서 다시 불러올 수 있어요.")
            for i, item in enumerate(s.recent):
                with st.container(border=True):
                    st.write(item["title"] or item["text"][:45])
                    st.caption(item["text"][:100])
                    st.button(
                        "불러오기",
                        key=f"recent_{i}",
                        on_click=load,
                        args=(item["text"], item["title"]),
                        disabled=bool(s.get("analysis_workflow_id")),
                    )
    if s.stage == 2:
        st.title("특허 비교 보고서")
        st.caption(
            "실제 특허 문헌의 청구항과 아이디어 구성요소를 대조합니다. 검색 결과는 등록 가능성을 확정하는 법률 의견이 아닙니다."
        )
        if not s.confirmed_context:
            st.warning("먼저 아이디어 초안을 확정해 주세요.")
            st.button("← 아이디어 입력", on_click=navigate, args=(1,))
        elif s.real_mode:
            if s.pipeline_result is None:
                if s.get("analysis_workflow_id"):
                    st.caption("특허 분석 결과가 준비되면 이 화면에 먼저 표시합니다.")
                else:
                    cached = (
                        s.analysis_sources is not None
                        and s.analysis_key == current_analysis_key()
                    )
                    st.info(
                        "특허와 시장 자료를 한 번 수집·분석해 결과를 단계별로 보여줍니다. API 호출 비용이 발생할 수 있습니다."
                        if not cached
                        else "현재 아이디어와 분야에 대한 기존 수집 결과를 재사용합니다."
                    )
                    if st.button(
                        "특허·시장 근거 조사 시작" if not cached else "분석 결과 생성",
                        type="primary",
                        disabled=RUN_LOCK.locked(),
                    ):
                        start_report_workflow()
                        st.rerun()
                    if st.session_state.get("pipeline_error"):
                        st.error(st.session_state.pipeline_error)
            else:
                result = s.pipeline_result
                patent = result.patent
                if result.readiness:
                    st.caption(
                        f"특허 검색: {PATENT_MODE_LABELS.get(result.readiness.patent_mode, result.readiness.patent_mode)}"
                    )
                with st.container(height=580, border=False):
                    render_patent_report(patent)
                if patent.status == "error" and not s.get("analysis_workflow_id"):
                    st.caption("이전 특허 조사에 오류가 있어 다시 조사가 필요합니다.")
                    if st.button(
                        "특허·시장 근거 다시 조사 · API 비용 발생",
                        key="retry_source_analysis",
                        disabled=RUN_LOCK.locked(),
                    ):
                        s.pipeline_result = None
                        s.analysis_sources = None
                        s.analysis_key = ""
                        start_report_workflow()
                        st.rerun()
                if s.get("analysis_workflow_id"):
                    st.caption(
                        "시장성 분석은 계속 진행됩니다. 위 탭에서 준비된 결과를 확인할 수 있습니다."
                    )
                else:
                    left, right = st.columns(2)
                    left.button("← 아이디어 수정", on_click=navigate, args=(1,))
                    if right.button("시장성 보고서 →", type="primary"):
                        s.stage = 3
                        st.rerun()
        else:
            st.warning(
                "가상 시연 자료 · 실제 특허 검색이나 등록 가능성 판단이 아닙니다."
            )
            rows = [r for r in candidates(s.raw) if r["kind"] == "특허"]
            if not rows:
                st.info("표시할 특허 시연 자료가 없습니다.")
            for row in rows:
                with st.container(border=True):
                    st.subheader(row["title"])
                    st.caption(f"{row['id']} · 가상 자료 · 구성별 청구항 대응 미검토")
                    st.write(row["quote"])
                    st.caption(row["limit"])
            st.button("← 아이디어 수정", on_click=navigate, args=(1,))
            if st.button("시장성 보고서 →", type="primary"):
                s.stage = 3
                st.rerun()
    elif s.stage == 3:
        st.title("시장성 보고서")
        st.caption(
            "산업 동향을 아이디어의 고객·현재 대안·구매 조건에 연결합니다. 기사·기업 신호와 실제 구매 의사는 구분합니다."
        )
        workflow_job = current_workflow_job()
        if s.real_mode and workflow_job and not workflow_job.get("market_report"):
            st.caption(
                "특허 결과를 확인할 수 있습니다. 시장 결과가 준비되면 이 화면에 이어서 표시합니다."
            )
        elif s.real_mode and s.pipeline_result:
            market = s.pipeline_result.market
            with st.container(height=580, border=False):
                render_market_report(market, s.idea_draft)
            if s.get("analysis_workflow_id"):
                st.caption(
                    "최종 보고서를 작성 중입니다. 완료되면 상단 종합 보고서에서 확인할 수 있습니다."
                )
            else:
                left, right = st.columns(2)
                left.button("← 특허 비교", on_click=navigate, args=(2,))
                if right.button("최종 실행 검토 →", type="primary"):
                    s.stage = 4
                    st.rerun()
        elif s.real_mode:
            st.info(
                "시장 분석은 특허 단계에서 한 번 조사됩니다. 특허 보고서에서 ‘시장성 보고서’를 눌러 다음 단계로 이동해 주세요."
            )
            if st.button("조사 결과 다시 불러오기", type="primary"):
                st.stage = 2
                st.rerun()
        else:
            st.warning("가상 시연 자료 · 실제 시장 수요 분석이 아닙니다.")
            rows = [r for r in candidates(s.raw) if r["kind"] in {"시장", "기업"}]
            if not rows:
                st.info("표시할 시장 시연 자료가 없습니다.")
            for row in rows:
                with st.container(border=True):
                    st.subheader(row["title"])
                    st.caption(f"{row['id']} · 가상 자료")
                    st.write(row["quote"])
                    st.caption(row["limit"])
            st.button("← 특허 비교", on_click=navigate, args=(2,))
            if st.button("최종 실행 검토 →", type="primary"):
                snapshot()
                s.stage = 4
                st.rerun()
    elif s.stage == 4 and s.real_mode and s.pipeline_result is None:
        st.title("최종 사업 실행 검토")
        st.error(
            st.session_state.get("pipeline_error")
            or "분석 결과를 만들지 못했습니다. 다시 시도해 주세요."
        )
        cached = (
            s.analysis_sources is not None and s.analysis_key == current_analysis_key()
        )
        if st.button(
            (
                "최종 보고서 생성 다시 시도"
                if cached
                else "특허·시장 조사 다시 시작 · API 비용 발생"
            ),
            type="primary",
            disabled=RUN_LOCK.locked(),
        ):
            if not cached:
                s.analysis_sources = None
                s.analysis_key = ""
            start_report_workflow()
            st.rerun()
        st.button("← 아이디어 수정", on_click=navigate, args=(1,))
    elif s.stage == 4 and s.real_mode and s.pipeline_result:
        st.title("최종 사업 실행 검토")
        st.button("← 근거·연결 검토로", on_click=navigate, args=(3,))
        if not s.pipeline_result.markdown:
            st.error(
                s.get("pipeline_error")
                or "통합 실행 검토를 만들지 못했습니다. 완료된 조사 결과는 보존했습니다."
            )
            st.caption(
                "특허·시장 근거는 각 단계에서 확인할 수 있습니다. 최종 보고서만 다시 생성할 수 있습니다."
            )
            if st.button(
                "최종 검토 다시 작성",
                key="retry_executive_report",
                disabled=RUN_LOCK.locked()
                or s.analysis_sources is None
                or s.analysis_key != current_analysis_key(),
            ):
                start_report_workflow()
                st.rerun()
        if (
            s.pipeline_result.patent.status == "error"
            or s.pipeline_result.market.status == "error"
        ):
            st.warning(
                "일부 조사가 실패했습니다. 해당 영역의 결과를 다시 확인할 수 있습니다."
            )
            if st.button(
                "특허·시장 근거 다시 조사 · API 비용 발생",
                key="retry_from_final_report",
                disabled=RUN_LOCK.locked(),
            ):
                s.pipeline_result = None
                s.analysis_sources = None
                s.analysis_key = ""
                start_report_workflow()
                st.rerun()
        render_report(s, report_payload(s))
    elif s.stage == 4 and s.report_snapshot:
        render_report(s, report_payload(s))
    st.caption(
        "입력은 현재 세션에서만 유지됩니다. 실제 조사는 API 키와 로컬 색인 범위에 따라 결과가 달라집니다."
    )

if previous_stage != s.stage:
    st.html(
        """<script>(() => {
        const until = performance.now() + 650;
        function alignPage() {
            const main = document.querySelector('[data-testid="stMain"]');
            if (main) main.scrollTo({top: 0, behavior: 'instant'});
            if (performance.now() < until) requestAnimationFrame(alignPage);
        }
        requestAnimationFrame(alignPage);
        })();</script>""",
        unsafe_allow_javascript=True,
    )
