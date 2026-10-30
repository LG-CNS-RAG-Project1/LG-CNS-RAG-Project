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
    build_version,
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
from frontend.quick_nav import render_page_nav, render_quick_nav

st.set_page_config(page_title="IdeaLens · 빠른 조사", page_icon="▤", layout="wide")
st.html("""<style>
    @keyframes idealens-spin { to { transform: rotate(360deg); } }
    .workflow-spinner { display:inline-block; width:.82em; height:.82em; border:2px solid #9aa8a4;
      border-top-color:#1f4943; border-radius:50%; animation:idealens-spin .8s linear infinite;
      vertical-align:-.08em; margin-right:.18em; }
    .patent-quote { border-left:4px solid #d4a72c; background:#fff8d8; padding:1rem 1.1rem;
      line-height:1.9; white-space:pre-wrap; overflow-wrap:anywhere; }
    .patent-quote mark { background:#ffec80; color:#1f302e; padding:.08em .12em; }
    .patent-quote u { text-decoration-thickness:2px; text-decoration-color:#d4a72c; }
    </style>""")
st.html(Path(__file__).with_name("styles.css").read_text(encoding="utf-8"))
st.html(brand_style())
for key, value in {
    "app_view": "landing",
    "page": "home",
    "records": [],
    "stage": 1,
    "idea_page_view": "input",
    "show_examples": False,
    "show_recent": False,
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
    "workflow_preview_stage": None,
    "selected_patent_detail_id": None,
    "patent_orbit_chart_version": 0,
    "workflow_cancelled": False,
    "technology_area_id": None,
    "technology_area_choice": "AUTO",
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
    version = build_version(Path(__file__).resolve().parents[1])
    if version:
        st.caption(f"버전 {version}")
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


def show_landing():
    """모든 화면에서 브랜드 메인 페이지로 돌아간다."""
    s.page = "home"
    s.app_view = "landing"


def enter_analysis():
    """랜딩 화면에서 아이디어 입력 단계로 진입한다."""
    s.page = "workspace"
    s.app_view = "analysis"
    s.stage = 1


def open_example_draft(text, title):
    """예시 입력만 설정해 다음 화면 실행에서 LLM 초안을 생성한다."""
    s.raw_input = text
    s.idea_input_buffer = text
    s.raw = text
    input_changed()
    s.title_input = title
    s.idea_draft = None
    s.ai_draft_error = None
    prepare_input()
    s.idea_page_view = "generate_example"
    s.show_examples = False


def clear_workflow_preview():
    s.workflow_preview_stage = None


def clear_patent_detail():
    s.selected_patent_detail_id = None
    s.patent_orbit_chart_version = s.get("patent_orbit_chart_version", 0) + 1


@st.dialog("특허 비교 상세", width="large", on_dismiss=clear_patent_detail)
def patent_detail_dialog(patent, patent_id):
    """선택한 문헌의 검증된 비교와 원문만 표시한다."""
    from src.generation.patent_analysis import (
        highlight_verbatim_excerpt,
        kipris_application_search_url,
    )
    from src.generation.report_builder import safe_url
    from frontend.patent_orbit import (
        drawing_image_metadata,
        fetch_first_kipris_drawing,
        kipris_drawing_url,
        tooltip_text,
    )

    review = next(
        (item for item in patent.patent_reviews if item.patent_id == patent_id), None
    )
    evidence_by_id = {
        item.citation_id: item
        for item in patent.evidence
        if item.patent_id == patent_id
    }
    if review is None and not evidence_by_id:
        st.info("선택한 특허의 비교 결과를 찾을 수 없습니다.")
        return
    title = review.title if review else next(iter(evidence_by_id.values())).title
    st.subheader(title)
    st.caption(
        " · ".join(
            value
            for value in (
                f"출원번호 {next((item.application_number for item in evidence_by_id.values() if item.application_number), '미확인')}",
                f"공개번호 {next((item.publication_number for item in evidence_by_id.values() if item.publication_number), '미확인')}",
            )
        )
    )
    drawing_evidence = next(
        (
            item
            for item in evidence_by_id.values()
            if item.representative_thumbnail_url or item.representative_drawing_url
        ),
        None,
    )
    image_bytes = None
    image_status = "missing_url"
    loaded_url = None
    if drawing_evidence:
        image_bytes, image_status, loaded_url = fetch_first_kipris_drawing(
            (
                drawing_evidence.representative_drawing_url,
                drawing_evidence.representative_thumbnail_url,
            )
        )
    full_drawing_url = (
        kipris_drawing_url(
            drawing_evidence.representative_drawing_url
            or drawing_evidence.representative_thumbnail_url
        )
        if drawing_evidence
        else None
    )

    left, right = st.columns([3, 1.15], gap="large", vertical_alignment="top")
    with left:
        if review:
            reason = tooltip_text(review.relevance_reason, "우선 확인 이유 미제공")
            st.info(f"**관련성: {review.relevance}** · {reason}")
            if review.overall_summary:
                st.write(review.overall_summary)
        else:
            st.info("원문은 확보했지만 이 문헌의 비교 분석 결과는 제공되지 않았습니다.")

    with right:
        st.markdown("#### 대표도면")
        if image_bytes:
            try:
                image_width, image_height, _, image_format = drawing_image_metadata(
                    image_bytes
                )
                original_url = kipris_drawing_url(
                    drawing_evidence.representative_drawing_url
                )
                is_original = loaded_url == original_url
                resolution_note = "원본 도면" if is_original else "썸네일 · 저해상도"
                caption = drawing_evidence.representative_drawing_caption or (
                    f"KIPRIS 대표도면 · 출원번호 "
                    f"{drawing_evidence.application_number or patent_id}"
                )
                st.image(image_bytes, caption=caption, width=min(image_width, 240))
                st.caption(
                    f"{resolution_note} · {image_width}×{image_height} px · {image_format}"
                )
                with st.popover("도면 크게 보기"):
                    st.image(image_bytes, caption=caption, width=min(image_width, 1200))
                    st.caption(f"{image_width}×{image_height} px · {image_format}")
                    if full_drawing_url:
                        st.link_button("KIPRIS 대표도면 원문 열기", full_drawing_url)
                st.caption("출처: KIPRIS Plus · 선택한 문헌")
            except Exception:
                st.info(
                    "대표도면 형식을 표시할 수 없습니다. KIPRIS 원문 링크에서 확인해 주세요."
                )
        elif drawing_evidence:
            failure_messages = {
                "invalid_source": "저장된 도면 주소가 KIPRIS 공식 호스트가 아니어서 표시하지 않았습니다.",
                "redirect": "도면 서버가 다른 주소로 안내했습니다. 안전 검증을 위해 자동 이동하지 않았습니다.",
                "http_error": "KIPRIS 도면 서버에서 이미지 파일을 가져오지 못했습니다.",
                "non_image_response": "KIPRIS 도면 서버가 이미지가 아닌 응답을 반환했습니다.",
                "invalid_image": "KIPRIS 응답이 유효한 이미지 파일이 아닙니다.",
                "too_large": "도면 파일이 허용 크기인 8MB를 초과했습니다.",
                "network_error": "KIPRIS 도면 서버에 연결하지 못했습니다.",
                "missing_url": "이미지 경로를 찾을 수 없습니다.",
            }
            st.info(
                "대표도면을 불러오지 못했습니다. "
                + failure_messages.get(
                    image_status, "이미지 응답을 확인할 수 없습니다."
                )
            )
        else:
            st.info("이 문헌에는 대표도면 경로가 없습니다.")
        if full_drawing_url:
            st.link_button("KIPRIS 도면 원문", full_drawing_url)

    st.markdown("#### 아이디어 구성요소별 비교")
    status_labels = {
        "overlap": "유사",
        "partial": "일부 유사",
        "different": "차이",
        "not_found": "근거에서 찾지 못함",
        "uncertain": "불확실",
    }
    comparisons = review.component_comparisons if review else []
    if comparisons:
        for comparison in comparisons:
            st.markdown(
                f"**{comparison.idea_component}** · "
                f"{status_labels.get(comparison.status, '불확실')}"
            )
            if comparison.overlap:
                st.write(f"유사점: {comparison.overlap}")
            if comparison.difference:
                st.write(f"차이점: {comparison.difference}")
            if comparison.uncertainty:
                st.caption(f"확인 한계: {comparison.uncertainty}")
            cited = [
                evidence_by_id[cid]
                for cid in comparison.citation_ids
                if cid in evidence_by_id
            ]
            for evidence in cited:
                claim_label = (
                    f"청구항 {evidence.claim_number}"
                    if evidence.claim_number
                    else evidence.section
                )
                st.caption(f"P:{evidence.citation_id} · {claim_label}")
                matched = comparison.matched_text
                rendered_quote = highlight_verbatim_excerpt(evidence.quote, matched)
                st.markdown(
                    f'<div class="patent-quote">{rendered_quote}</div>',
                    unsafe_allow_html=True,
                )
                source_url = safe_url(evidence.source_url)
                if source_url:
                    st.link_button(
                        f"P:{evidence.citation_id} 원문 출처 열기", source_url
                    )
                if matched and matched not in evidence.quote:
                    st.caption(
                        "강조 문구가 제공된 원문과 일치하지 않아 표시하지 않았습니다."
                    )
    else:
        st.info("확인된 구성요소별 비교가 없습니다.")
    if review and review.unknowns:
        st.markdown("#### 추가 확인")
        for item in review.unknowns:
            st.write(f"- {item}")
    elif not review:
        st.markdown("#### 확보된 원문")
        for evidence in evidence_by_id.values():
            claim_label = (
                f"청구항 {evidence.claim_number}"
                if evidence.claim_number
                else evidence.section
            )
            st.caption(f"P:{evidence.citation_id} · {claim_label}")
            st.write(evidence.quote)

    if review and (review.watchout_findings or review.design_recommendations):
        st.markdown("#### 이 문헌의 주의점과 개선 제안")
        for item in review.watchout_findings:
            linked = [
                evidence_by_id[cid]
                for cid in item.citation_ids
                if cid in evidence_by_id
            ]
            basis = "문헌 근거 연결" if linked else "추가 확인이 필요한 가설"
            st.warning(
                f"**{item.issue} · {basis}**\n\n{item.why_it_matters}\n\n"
                f"다음 확인: {item.next_check}"
            )
            for evidence in linked:
                claim = (
                    f" · 청구항 {evidence.claim_number}"
                    if evidence.claim_number
                    else ""
                )
                st.caption(f"P:{evidence.citation_id}{claim} · {evidence.title}")
                st.text(evidence.quote)
        for item in review.design_recommendations:
            refs = ", ".join(f"P:{cid}" for cid in item.citation_ids)
            basis = "근거 기반" if item.basis == "evidence_based" else "검증 전 가설"
            st.markdown(f"**개선 제안 · {basis}:** {item.recommendation}")
            st.write(item.rationale)
            if item.validation_needed:
                st.caption(f"검증할 내용: {item.validation_needed}")
            if refs:
                st.caption(f"연결 근거: {refs}")

    application_number = next(
        (
            item.application_number
            for item in evidence_by_id.values()
            if item.application_number
        ),
        None,
    )
    kipris_url = kipris_application_search_url(application_number)
    if kipris_url:
        st.link_button("KIPRIS에서 출원번호 검색", kipris_url)
    elif not application_number:
        st.caption("출원번호 미확인 · KIPRIS 검색 링크를 만들 수 없습니다.")


@st.dialog("2. 주의점 및 개선 제안 상세", width="large")
def patent_watchouts_dialog(patent):
    """주의점·공통 설계 권고와 이를 뒷받침하는 특허 근거를 표시한다."""
    precheck = patent.patentability_precheck
    if precheck is None:
        st.info("특허 비교 신호가 없어 상세 내용을 제공할 수 없습니다.")
        return

    evidence_by_id = {item.citation_id: item for item in patent.evidence}
    st.caption(
        "검색 문헌을 바탕으로 한 기술 검토 보조입니다. 출원·신규성·진보성·침해·실시 자유에 대한 법률 의견이 아닙니다."
    )
    if precheck.common_watchouts:
        st.markdown("### 주의 항목 · 문헌 근거 연결 여부 확인")
        for item in precheck.common_watchouts:
            linked = [
                evidence_by_id[cid]
                for cid in item.citation_ids
                if cid in evidence_by_id
            ]
            basis = "문헌 근거 연결" if linked else "추가 확인이 필요한 가설"
            st.warning(
                f"**{item.issue} · {basis}**\n\n{item.why_it_matters}\n\n다음 확인: {item.next_check}"
            )
            if not linked:
                st.caption("연결된 문헌·청구항이 없어 분석 가설로만 표시합니다.")
            for evidence in linked:
                claim = (
                    f" · 청구항 {evidence.claim_number}"
                    if evidence.claim_number
                    else ""
                )
                st.caption(f"P:{evidence.citation_id}{claim} · {evidence.title}")
                st.text(evidence.quote)
    else:
        st.info("문헌 전체에서 근거가 연결된 공통 주의점은 확인되지 않았습니다.")

    if precheck.common_design_recommendations:
        st.markdown("### 공통 개선 제안")
        for item in precheck.common_design_recommendations:
            refs = ", ".join(f"P:{cid}" for cid in item.citation_ids)
            basis = "근거 기반" if item.basis == "evidence_based" else "검증 전 가설"
            st.markdown(
                f"**{item.recommendation}** · {basis}{f' ({refs})' if refs else ''}"
            )
            st.write(item.rationale)
            if item.validation_needed:
                st.caption(f"확인할 사항: {item.validation_needed}")
            for citation_id in item.citation_ids:
                evidence = evidence_by_id.get(citation_id)
                if evidence:
                    claim = (
                        f" · 청구항 {evidence.claim_number}"
                        if evidence.claim_number
                        else ""
                    )
                    st.caption(f"근거 P:{citation_id}{claim} · {evidence.title}")

    if precheck.expert_questions:
        st.markdown("### 전문가 확인 질문")
        for question in precheck.expert_questions:
            st.write(f"- {question}")
    if precheck.limitations:
        st.caption("공통 검토 한계: " + " · ".join(precheck.limitations))


@st.dialog("3. 설계 대안 상세", width="large")
def patent_design_dialog(patent):
    """설계 대안의 구현 내용·근거·검증 계획을 한국어로 표시한다."""
    analysis = patent.design_analysis
    if analysis is None:
        st.info("설계 대안 분석 결과가 없습니다.")
        return

    status_labels = {
        "success": "근거를 바탕으로 대안을 구성했습니다.",
        "partial": "일부 정보가 부족해 제한적으로 제안합니다.",
        "insufficient_evidence": "설계 대안을 뒷받침할 근거가 부족합니다.",
        "failed": "대안 생성이 완료되지 않았습니다.",
    }
    feasibility_labels = {
        "low": "낮음",
        "medium": "보통",
        "high": "높음",
        "unknown": "미확인",
    }
    evidence_labels = {"grounded": "근거 연결", "insufficient_evidence": "근거 부족"}
    evidence_by_id = {item.citation_id: item for item in patent.evidence}
    st.caption(status_labels[analysis.status])
    if analysis.evidence_level == "abstract_only":
        st.warning("청구항 원문이 없어 초록 수준의 근거로만 분석했습니다.")
    for component in analysis.technical_components:
        st.caption(f"{component.id} · {component.name} — {component.description}")

    if not analysis.proposals:
        st.info("표시할 설계 대안이 없습니다.")
    for index, proposal in enumerate(analysis.proposals, 1):
        with st.container(border=True):
            st.markdown(f"### 대안 {index} · {proposal.title}")
            st.markdown(f"**현재 문제**\n\n{proposal.problem}")
            st.markdown(f"**변경 대상**\n\n{', '.join(proposal.target_component_ids)}")
            st.markdown(f"**설계 변경**\n\n{proposal.proposed_change}")
            st.markdown("**구현 방법**")
            for step in proposal.implementation_approach:
                st.markdown(f"- {step}")
            st.markdown(f"**기술적 차이**\n\n{proposal.technical_difference}")
            if proposal.expected_benefits:
                st.markdown(
                    "**기대 효과**\n\n" + " · ".join(proposal.expected_benefits)
                )
            if proposal.limitations:
                st.markdown("**구현상 제약**\n\n" + " · ".join(proposal.limitations))
            st.caption(
                f"기술 구현 가능성: {feasibility_labels[proposal.feasibility]} · "
                f"근거 상태: {evidence_labels[proposal.evidence_status]}"
            )
            for citation_id in proposal.citation_ids:
                source = evidence_by_id.get(citation_id)
                if source:
                    claim = (
                        f" · 청구항 {source.claim_number}"
                        if source.claim_number
                        else ""
                    )
                    st.caption(f"근거 P:{citation_id} · {source.title}{claim}")
                    st.text(source.quote)
            st.markdown(f"**검증 방법**\n\n{proposal.verification_plan.method}")
            if proposal.verification_plan.metrics:
                st.caption(
                    "측정 항목: " + " · ".join(proposal.verification_plan.metrics)
                )
            st.caption("성공 기준: " + proposal.verification_plan.success_criteria)
            st.caption(
                "추가 특허 확인 필요"
                if proposal.patent_verification_required
                else "추가 특허 확인 표시 없음"
            )
    for item in analysis.missing_information:
        st.warning("추가 확인: " + item)
    for item in analysis.limitations:
        st.caption("한계: " + item)
    st.caption("기술 검토용이며 침해·특허성·실시 자유에 대한 법률 의견이 아닙니다.")


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
    s.selected_patent_detail_id = None
    s.patent_orbit_chart_version = s.get("patent_orbit_chart_version", 0) + 1
    s.idea_page_view = "input"
    s.title_input = ""
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
        s.parts = [""]
        s.questions = [{"id": "Q1", "question": "", "condition": ""}]
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
        st.session_state.ai_draft_error = None
    except Exception as exc:
        st.session_state.ai_draft_error = friendly_error(exc)


def current_analysis_key():
    return analysis_key(s.idea_draft, s.parts, s.technology_area_id)


def run_real_pipeline():
    """조사(구성·분야가 같으면 재사용)와 질문 연결을 실행한다. 결과는 화면 호출 전에 세션에 저장한다."""
    from src.pipeline import analyze_sources, run_pipeline, screen_inputs
    from src.generation.cost_estimation import call_cost_llm
    from src.generation.market_analysis import call_analysis_llm

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
            cost_llm_fn=call_cost_llm,
            swot_llm_fn=call_analysis_llm,
            canvas_llm_fn=call_analysis_llm,
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
        from src.generation.cost_estimation import call_cost_llm
        from src.generation.market_analysis import call_analysis_llm

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
            cost_llm_fn=call_cost_llm,
            swot_llm_fn=call_analysis_llm,
            canvas_llm_fn=call_analysis_llm,
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
    s.idea_draft.to_structured_idea()
    s.selected_patent_detail_id = None
    s.patent_orbit_chart_version = s.get("patent_orbit_chart_version", 0) + 1
    job_id = uuid4().hex
    key = current_analysis_key()
    cached_sources = (
        s.analysis_sources
        if s.analysis_sources is not None and s.analysis_key == key
        else None
    )
    with WORKFLOW_JOBS_LOCK:
        WORKFLOW_JOBS[job_id] = {
            "resume_context": dict(
                draft=s.idea_draft.model_dump(),
                parts=list(s.parts),
                questions=deepcopy(s.questions),
                area=s.technology_area_id,
                raw=s.raw,
                title=s.research_title,
            ),
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
    s.workflow_preview_stage = None
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
        s.workflow_preview_stage = None
        s.pipeline_result = None
        s.analysis_sources = None
        s.analysis_key = ""
        s.workflow_cancelled = True
        s.stage = 1


def accept_draft_and_start():
    """완성된 초안을 확정하고 특허 단계부터 자동 조사를 시작한다."""
    s.idea_draft.to_structured_idea()
    s.confirmed_context = True
    s.selected = []
    start_report_workflow()


def save_draft_and_start(draft, title, values, components, hypotheses, details):
    """편집한 초안을 확인하고, 필수 정보가 채워졌을 때만 분석을 시작한다."""
    from src.generation.idea_parser import check_draft

    labels = {
        **FIELD_LABELS,
        "current_alternative": "현재 대안",
        "target_segment": "목표 세그먼트",
        "technical_components": "기술 구성요소",
        "value_hypotheses": "가치 가설",
    }
    edits = {
        **values,
        **details,
        "technical_components": components,
        "value_hypotheses": hypotheses,
    }
    sources = dict(draft.field_sources)
    unknowns = list(draft.unknowns)
    for field, value in edits.items():
        previous = getattr(draft, field)
        if value != previous or field not in sources:
            sources[field] = "user_answer" if value else "unknown"
        label = labels[field]
        if value:
            unknowns = [item for item in unknowns if item != label]
        elif sources.get(field) == "unknown" and label not in unknowns:
            unknowns.append(label)
    if title.strip() != draft.title:
        sources["title"] = "user_answer" if title.strip() else "unknown"
    updated = type(draft).model_validate(
        {
            **draft.model_dump(),
            **values,
            **details,
            "title": title.strip(),
            "technical_components": components,
            "value_hypotheses": hypotheses,
            "field_sources": sources,
            "unknowns": unknowns,
            "status": "complete",
            "missing_fields": [],
            "questions": {},
        }
    )
    updated = check_draft(updated)
    missing = [FIELD_LABELS[field] for field in updated.missing_fields]
    if not updated.title.strip():
        missing.insert(0, "아이디어 이름")
    s.idea_draft = updated
    if missing or updated.status != "complete":
        return missing or ["필수 아이디어 항목"]
    updated.to_structured_idea()
    apply_complete_draft(updated)
    accept_draft_and_start()
    return []


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
def workflow_progress_fragment(compact=False):
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
            if report.status == "partial":
                return "부분 완료"
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
    if not compact:
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
        st.rerun(scope="app")

    if snapshot.get("result") is not None:
        s.pipeline_result = snapshot["result"]
        s.analysis_sources = snapshot.get("sources")
        s.analysis_workflow_id = None
        st.rerun(scope="app")
    ready_key = (patent_ready, market_ready)
    if ready_key != s.get("workflow_ready_key") and any(ready_key):
        s.workflow_ready_key = ready_key
        s.pipeline_result = partial_workflow_result(snapshot)
        st.rerun(scope="app")

    if compact:
        phase_label = {
            "patent": "특허 조사",
            "market": "시장 분석",
            "final_report": "보고서 작성",
        }.get(phase, "분석")
        st.info(f"{phase_label} 진행 중 · 다른 화면을 둘러보셔도 분석은 계속됩니다.")
        st.button(
            "진행 중인 조사로 돌아가기",
            key="return_running_research",
            on_click=resume_research,
        )
        return

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


def render_patent_report(patent, *, widget_suffix="", preview=False):
    """최대 8개 특허를 궤도에 배치하고 호버 요약과 종합 근거를 제공한다."""
    import math
    from frontend.patent_orbit import (
        dense_similarity_text,
        patent_dense_similarity,
        patent_orbit_position,
        tooltip_text,
    )

    from src.generation.patent_analysis import (
        PATENT_ORBIT_COLORS,
        PATENT_ORBIT_LABELS,
        patent_orbit_category,
        patent_review_priority,
    )

    if patent.status == "error":
        st.error("특허 비교 보고서를 완성하지 못했습니다.")
        if "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR" in (
            patent.error_message or ""
        ):
            st.warning(
                "로컬 특허 색인에서 관련 후보를 확인하지 못했고, KIPRIS 요청 한도 초과로 보충 검색이 중단됐습니다. "
                "따라서 현재 결과는 ‘특허 없음’이 아니라 ‘검색 미완료’입니다. KIPRIS 이용 한도를 확인한 뒤 다시 조사해 주세요."
            )
        if patent.evidence:
            st.info(
                f"비교 생성은 실패했지만 원문 근거 {len(patent.evidence)}건은 보존했습니다."
            )
        st.caption(
            "원인과 조치 방법을 확인한 뒤 다시 분석해 주세요. 재시도는 API 비용이 발생할 수 있습니다."
        )
        if patent.error_message:
            from src.pipeline import redact

            with st.expander("오류 상세"):
                st.code(redact(patent.error_message))
    elif patent.status == "partial":
        st.warning("특허 원문은 확보했지만 비교 분석을 완료하지 못했습니다.")
        st.info(f"원문 근거 {len(patent.evidence)}건을 보존했습니다.")
        st.caption(
            "아래 문헌과 원문은 확인할 수 있지만, 구성요소별 비교와 설계 대안은 미완료입니다."
        )
        if patent.error_message:
            from src.pipeline import redact

            with st.expander("비교 생성 오류 상세"):
                st.code(redact(patent.error_message))
    elif patent.status == "no_results":
        st.warning(
            "검색 범위에서 특허 근거를 찾지 못했습니다. 위험이 없다는 뜻은 아닙니다."
        )
        st.caption(f"검색 범위: {patent.search_scope}")
        if patent.unknowns:
            st.caption(f"검색 상태: {patent.unknowns[0]}")

    precheck = patent.patentability_precheck
    evidence_by_id = {item.citation_id: item for item in patent.evidence}
    reviews_by_patent = {item.patent_id: item for item in patent.patent_reviews}
    design_analysis = patent.design_analysis
    related_stats = getattr(patent, "related_statistics", None)

    st.subheader("1. 특허 비교 궤도")
    st.caption(
        "검색된 문헌과 청구항을 아이디어 구성요소에 대조한 기술 예비 검토입니다."
    )
    with st.container(border=True):
        documents = []
        for evidence in patent.evidence:
            if evidence.patent_id not in {item["patent_id"] for item in documents}:
                documents.append(
                    {
                        "patent_id": evidence.patent_id,
                        "title": evidence.title,
                        "evidence": [],
                    }
                )
            next(item for item in documents if item["patent_id"] == evidence.patent_id)[
                "evidence"
            ].append(evidence)
        documents = documents[:8]
        if documents:
            candidate_count = related_stats.total_patents if related_stats else None
            if candidate_count is not None:
                st.caption(
                    f"관련 검색 후보 {candidate_count}건 중 최종 비교 {len(documents)}건 · 목표 5~8건"
                )
            else:
                st.caption(f"최종 비교 문헌 {len(documents)}건 · 목표 5~8건")
            if len(documents) < 5:
                st.warning(
                    f"관련 특허를 {len(documents)}건만 확인했습니다. 검색 범위에서 근거가 있는 문헌만 보여주며, 수를 맞추기 위해 관련성이 낮은 특허를 추가하지 않았습니다."
                )
            orbit_reviews = []
            for document in documents:
                review = reviews_by_patent.get(document["patent_id"])
                if review is None:
                    from src.schemas import PatentDocumentReview

                    review = PatentDocumentReview(
                        patent_id=document["patent_id"],
                        title=document["title"],
                        citation_ids=[
                            item.citation_id for item in document["evidence"]
                        ],
                        relevance="insufficient",
                    )
                orbit_reviews.append((review, document["evidence"]))
            orbit_reviews.sort(
                key=lambda pair: (
                    ("red", "yellow", "green", "blue").index(
                        patent_orbit_category(pair[0], evidence_by_id)
                    ),
                    patent_review_priority(pair[0]),
                )
            )
            count = len(orbit_reviews)
            points = []
            for index, (review, document_evidence) in enumerate(orbit_reviews):
                category = patent_orbit_category(review, evidence_by_id)
                reason = tooltip_text(review.relevance_reason, "우선 확인 이유 미제공")
                similarity = patent_dense_similarity(document_evidence)
                x, y = patent_orbit_position(index, count, similarity)
                points.append(
                    {
                        "patent_id": review.patent_id,
                        "title": review.title,
                        "number": f"P{index + 1}",
                        "priority_reason_display": reason[:180],
                        "dense_score_display": dense_similarity_text(similarity),
                        "category": category,
                        "color": PATENT_ORBIT_COLORS[category],
                        "x": x,
                        "y": y,
                    }
                )

            st.subheader("특허 비교 궤도")
            st.caption(
                "Dense 점수(1−cosine distance를 0~1로 제한한 문헌별 최고값)는 hover에서 확인할 수 있으며 관련성 확률이 아닙니다. 점수가 높을수록 중심에 가깝게 배치합니다(반경 2.8−1.35×점수, 미제공은 외곽). KIPRIS 보충 문헌은 Dense 검색 점수가 없으므로 hover에 미제공으로 표시합니다. 색상은 구성 비교 근거에 따른 검토 우선순위이며 법률상 위험 등급이 아닙니다."
            )
            legend = st.columns(4)
            for column, category in zip(legend, ("red", "yellow", "green", "blue")):
                column.markdown(
                    f'<span style="color:{PATENT_ORBIT_COLORS[category]}">●</span> '
                    f"{PATENT_ORBIT_LABELS[category]}",
                    unsafe_allow_html=True,
                )

            selected_patent = None
            try:
                import altair as alt

                orbit_values = []
                for ring, (radius_x, radius_y) in enumerate(
                    ((2.7, 2.1), (1.85, 1.44), (1.05, 0.82))
                ):
                    orbit_values.extend(
                        {
                            "order": index,
                            "ring": ring,
                            "x": radius_x * math.cos(2 * math.pi * index / 120),
                            "y": radius_y * math.sin(2 * math.pi * index / 120),
                        }
                        for index in range(121)
                    )
                hover = alt.selection_point(
                    name=f"patent_hover{widget_suffix}",
                    fields=["patent_id"],
                    on="pointerover",
                    clear="pointerout",
                    nearest=True,
                )
                click = None
                if not preview:
                    click = alt.selection_point(
                        name=f"patent_click{widget_suffix}",
                        fields=["patent_id"],
                        on="click",
                        clear="dblclick",
                        empty=False,
                    )
                orbit = (
                    alt.Chart(alt.Data(values=orbit_values))
                    .mark_line(
                        color="#97aaa0",
                        strokeDash=[3, 6],
                        strokeWidth=1.15,
                        opacity=0.62,
                    )
                    .encode(
                        x=alt.X("x:Q", axis=None, scale=alt.Scale(domain=[-3.5, 3.5])),
                        y=alt.Y("y:Q", axis=None, scale=alt.Scale(domain=[-2.8, 2.8])),
                        order="order:Q",
                        detail="ring:N",
                    )
                )
                center_data = alt.Data(values=[{"x": 0, "y": 0, "label": "아이디어"}])
                center = (
                    alt.Chart(center_data)
                    .mark_circle(
                        size=1900, color="#214c45", stroke="#d5b96a", strokeWidth=2
                    )
                    .encode(x="x:Q", y="y:Q", tooltip="label:N")
                )
                center_label = (
                    alt.Chart(center_data)
                    .mark_text(color="white", fontSize=15, fontWeight="bold")
                    .encode(x="x:Q", y="y:Q", text="label:N")
                )
                points_chart = (
                    alt.Chart(alt.Data(values=points))
                    .mark_circle(
                        size=1120,
                        stroke="#fffdf5",
                        strokeWidth=3,
                        cursor="help" if preview else "pointer",
                    )
                    .encode(
                        x="x:Q",
                        y="y:Q",
                        color=alt.Color(
                            "color:N", scale=None, legend=None, title="검토 우선순위"
                        ),
                        tooltip=[
                            alt.Tooltip("title:N", title="문헌"),
                            alt.Tooltip(
                                "dense_score_display:N",
                                title="Dense 검색 점수",
                            ),
                            alt.Tooltip(
                                "priority_reason_display:N",
                                title="우선 확인 이유",
                            ),
                        ],
                        opacity=alt.condition(hover, alt.value(1), alt.value(0.88)),
                    )
                    .add_params(*([hover, click] if click is not None else [hover]))
                )
                point_labels = (
                    alt.Chart(alt.Data(values=points))
                    .mark_text(color="white", fontSize=15, fontWeight="bold")
                    .encode(x="x:Q", y="y:Q", text="number:N")
                )
                chart = (
                    (orbit + center + center_label + points_chart + point_labels)
                    .properties(
                        height=380,
                        padding={"top": 12, "right": 12, "bottom": 12, "left": 12},
                    )
                    .configure_view(stroke=None)
                )
                chart_state = st.altair_chart(
                    chart,
                    key=(
                        f"patent_orbit_v4{widget_suffix}"
                        if preview
                        else f"patent_orbit_v4{widget_suffix}_{s.patent_orbit_chart_version}"
                    ),
                    on_select="ignore" if preview else "rerun",
                    selection_mode=None if preview else click.name,
                    width="stretch",
                    alt="중앙 아이디어를 둘러싼 특허 검토 우선순위 궤도 시각화",
                )
                if not preview:
                    selected_rows = chart_state.selection.get(click.name, [])
                    if selected_rows:
                        selected_patent = selected_rows[-1].get("patent_id")
                        if selected_patent in {item["patent_id"] for item in documents}:
                            s.selected_patent_detail_id = selected_patent
            except Exception as exc:
                st.warning(
                    f"궤도 차트를 표시하지 못했습니다 ({type(exc).__name__}). 페이지를 새로고침하거나 다른 브라우저에서 다시 열어 주세요."
                )

            selected_patent = s.get("selected_patent_detail_id") or selected_patent
            if not preview and selected_patent in {
                item["patent_id"] for item in documents
            }:
                patent_detail_dialog(patent, selected_patent)

        else:
            if patent.status in {"error", "partial"}:
                st.info("검색이 완료되지 않아 특허 부재 여부를 판단할 수 없습니다.")
            else:
                st.info(
                    "표시할 특허 문헌이 없습니다. 검색 결과가 없다는 뜻이 특허 위험이 없다는 의미는 아닙니다."
                )

    st.subheader("2. 주의점 및 개선 제안")
    if precheck:
        st.caption(
            "특허 문헌 비교를 위한 기술 검토 보조입니다. 특허성·침해·실시 자유에 대한 법률 판단이 아닙니다."
        )
        precheck_labels = {
            "overlap_concern": "유사 구성에 주의",
            "potentially_distinct": "차이 가능성 확인",
            "insufficient_evidence": "근거 부족 · 판단 보류",
        }
        st.info(f"{precheck_labels[precheck.status]} · {precheck.summary}")
        for item in precheck.common_watchouts[:2]:
            refs = ", ".join(f"P:{cid}" for cid in item.citation_ids)
            linked = any(cid in evidence_by_id for cid in item.citation_ids)
            basis = "문헌 근거" if linked else "확인 필요 가설"
            st.markdown(
                f"- **주의 · {basis}:** {item.issue} — {item.why_it_matters}"
                + (f" · 다음 확인: {item.next_check}" if item.next_check else "")
                + (f" · {refs}" if refs else "")
            )
        for item in precheck.common_design_recommendations[:2]:
            refs = ", ".join(f"P:{cid}" for cid in item.citation_ids)
            basis = "근거 기반" if item.basis == "evidence_based" else "검증 전 가설"
            st.markdown(
                f"- **개선 · {basis}:** {item.recommendation}"
                + (f" — {item.rationale}" if item.rationale else "")
                + (f" · {refs}" if refs else "")
            )
            if item.validation_needed:
                st.caption(f"확인할 사항: {item.validation_needed}")
        if not precheck.common_watchouts and not precheck.common_design_recommendations:
            st.caption("문헌 공통 주의점·개선 제안은 확인되지 않았습니다.")
        if not preview and st.button(
            "2 상세 보기", key=f"patent_watchouts_{widget_suffix}"
        ):
            patent_watchouts_dialog(patent)
    else:
        st.info(
            "특허 비교 신호가 제공되지 않아 주의점과 개선 제안을 판단하지 않았습니다."
        )

    st.subheader("3. 설계 대안")
    if design_analysis:
        design_status_labels = {
            "success": "근거 기반 제안",
            "partial": "제한적 제안",
            "insufficient_evidence": "근거 부족",
            "failed": "생성 실패",
        }
        st.caption(design_status_labels[design_analysis.status])
        for index, proposal in enumerate(design_analysis.proposals, 1):
            refs = ", ".join(f"P:{cid}" for cid in proposal.citation_ids)
            st.markdown(
                f"- **대안 {index} · {proposal.title}:** {proposal.proposed_change}"
                + (f" · 근거 {refs}" if refs else " · 검증 전 제안")
            )
        if not design_analysis.proposals:
            st.caption("표시할 설계 대안이 없습니다.")
        if not preview and st.button(
            "3 상세 보기", key=f"patent_design_{widget_suffix}"
        ):
            patent_design_dialog(patent)
    else:
        st.info("설계 대안 분석 결과가 없습니다.")
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


def _render_market_details(market, draft=None, widget_suffix=""):
    """실제 시장 근거·시각화와 조사 범위를 중심으로 보고서를 표시한다."""
    from src.generation.market_markdown import NATURE_LABELS
    from src.retrieval.market_relevance import DIMENSION_LABELS

    if market.status == "error":
        st.error(
            "시장 조사를 완료하지 못했습니다. 조사 범위와 오류 상태를 확인해 주세요."
        )
    elif market.status == "no_results":
        st.warning(
            "현재 검색 범위에서 시장 근거를 찾지 못했습니다. 수요가 없다는 뜻은 아닙니다."
        )
    else:
        st.caption(
            f"조사 범위: {market.search_scope} · 기준일 {market.data_as_of or '미제공'}"
        )

    trend = getattr(market, "search_trend", None)
    from frontend.market_trend_view import render_search_trend

    if trend is None:
        st.info("이번 분석 결과에 검색 관심도 데이터가 포함되지 않았습니다.")
    else:
        render_search_trend(trend, widget_suffix)
        st.caption(
            "검색 관심도는 기준 검색어 대비 상대 지수이며 시장 규모나 고객 수요의 근거가 아닙니다."
        )

    network = getattr(market, "keyword_network", None)
    from frontend.market_network_view import render_keyword_network

    if network is None:
        st.info("이번 분석 결과에 뉴스 키워드 네트워크 데이터가 포함되지 않았습니다.")
    else:
        render_keyword_network(network, widget_suffix)
        st.caption(
            "뉴스 제목·요약에서 함께 나온 단어의 관계이며 수요·인과·고객 유형을 뜻하지 않습니다."
        )

    financials = getattr(market, "company_financials", None)
    if financials is not None:
        from frontend.market_financials_view import render_company_financials

        render_company_financials(financials)
    procurement = getattr(market, "procurement", None)
    if procurement is not None:
        from frontend.market_procurement_view import render_procurement

        render_procurement(procurement)

    observed_dimensions = [
        dimension
        for dimension in market.dimensions
        if dimension.verdict in {"confirmed", "signal_only"} and dimension.claims
    ]
    if observed_dimensions:
        st.subheader("시장 자료에서 확인된 관찰")
        st.caption("각 문장은 시장 보고서의 기존 분석과 인용을 그대로 표시합니다.")
        for dimension in observed_dimensions:
            with st.container(border=True):
                state = (
                    "근거 확인" if dimension.verdict == "confirmed" else "신호만 확인"
                )
                st.markdown(f"#### {DIMENSION_LABELS[dimension.dimension]} · {state}")
                for claim in dimension.claims[:2]:
                    claim_type = {
                        "fact": "자료 사실",
                        "user_claim": "사용자 입력",
                        "ai_hypothesis": "검증 전 가설",
                    }[claim.claim_type]
                    refs = (
                        ", ".join(f"M:{cid}" for cid in claim.citation_ids)
                        or "인용 근거 없음"
                    )
                    st.markdown(f"- **{claim_type}:** {claim.statement}")
                    st.caption(f"근거: {refs}")
                if dimension.relevant_count is not None:
                    st.caption(
                        f"관련 판정 자료 {dimension.relevant_count}건 · 인용 수와는 별도 집계"
                    )
                if dimension.limitation:
                    st.caption("해석 한계: " + dimension.limitation)
    elif market.status == "completed":
        st.info("이번 조사에서 인용으로 확인된 시장 관찰 문장은 없습니다.")

    pending_checks = [
        (dimension, dimension.next_check)
        for dimension in market.dimensions
        if dimension.next_check and dimension.verdict == "unverified"
    ]
    if pending_checks:
        st.markdown("#### 근거를 더 확인할 항목")
        for dimension, next_check in pending_checks:
            label = DIMENSION_LABELS[dimension.dimension]
            limitation = f" · {dimension.limitation}" if dimension.limitation else ""
            st.markdown(f"- **{label}:** {next_check}{limitation}")

    dart_evidence = [item for item in market.evidence if item.source_type == "dart"]
    if dart_evidence:
        st.subheader("관련 기업의 DART 공시 발췌")
        st.caption(
            "아이디어 관련 검색에서 연결된 기업의 자체 사업보고서입니다. 검색된 기업이 실제 경쟁사라는 확인이나 특허 보유 관계를 뜻하지 않습니다."
        )
        companies = {}
        for item in dart_evidence:
            company = (
                item.publisher.removesuffix(" (DART 사업보고서)").strip()
                or "공시 기업 미제공"
            )
            companies.setdefault(company, []).append(item)
        company_columns = st.columns(min(len(companies), 2))
        for index, (company, items) in enumerate(companies.items()):
            with company_columns[index % len(company_columns)]:
                with st.container(border=True):
                    st.markdown(f"#### {company}")
                    for item in items[:3]:
                        period = item.period or "사업연도 미제공"
                        section = item.section or "원문 위치 미제공"
                        st.caption(f"M:{item.citation_id} · {period} · {section}")
                        st.markdown(f"**{item.title}**")
                        st.write(item.quote)
                        if item.url and item.url.startswith(("https://", "http://")):
                            st.link_button("공시 원문 열기 ↗", item.url)
        st.caption(
            "공시 발췌 수는 기업 규모·경쟁력·시장 점유율의 비교 지표가 아닙니다."
        )

    if market.evidence:
        from src.generation.market_markdown import market_report_to_markdown
        from src.generation.report_builder import escape_md, safe_url

        with st.expander(f"시장 근거 전체와 분석 원문 ({len(market.evidence)}건)"):
            st.markdown(market_report_to_markdown(market, heading_level=3))
            for item in market.evidence:
                st.markdown(f"**M:{item.citation_id} · {escape_md(item.title)}**")
                details = [
                    item.publisher,
                    item.period or "기간 미제공",
                    item.section or "원문 위치 미제공",
                ]
                st.caption(
                    " · ".join(details)
                    + f" · {NATURE_LABELS.get(item.evidence_nature, item.evidence_nature)}"
                )
                st.write(item.quote)
                url = safe_url(item.url)
                if url:
                    st.link_button("시장 원문 열기", url)

    if market.unknowns:
        with st.expander(f"시장 조사 한계와 미확인 항목 ({len(market.unknowns)}건)"):
            for item in market.unknowns:
                st.write(f"- {item}")


def render_market_report(market, draft=None, widget_suffix=""):
    """요약을 먼저 보여주고 팀 공용 상세 렌더러는 접어 제공한다."""
    from frontend.report_reading import render_market_brief

    if market.status == "error":
        st.error("시장 조사를 완료하지 못했습니다. 상세에서 처리 상태를 확인해 주세요.")
    render_market_brief(market)
    with st.expander("상세 근거·시각화 펼쳐보기"):
        _render_market_details(market, draft, widget_suffix)


@st.dialog("완료된 단계 결과", width="large", on_dismiss=clear_workflow_preview)
def workflow_stage_result_dialog(stage, draft, job, pipeline_result):
    """저장된 현재 실행 결과를 최신 단계 화면과 같은 읽기 전용 구성으로 보여준다."""
    labels = {
        1: "아이디어 구조화",
        2: "특허 비교 보고서",
        3: "시장성 보고서",
        4: "최종 실행 검토",
    }
    st.subheader(labels[stage])
    if stage == 1:
        if draft is None:
            st.info("확인할 아이디어 초안이 없습니다.")
            return
        st.caption("현재 분석 실행에서 확정한 초안입니다.")
        st.markdown(f"### {draft.title or '이름 없는 아이디어'}")
        st.caption(draft.original_text)
        fields = [
            ("해결할 문제", "problem"),
            ("핵심 기술", "technology"),
            ("목표 고객", "customers"),
            ("차별점", "difference"),
            ("수익모델", "revenue"),
        ]
        for offset in range(0, len(fields), 2):
            columns = st.columns(2)
            for column, (label, field) in zip(columns, fields[offset : offset + 2]):
                value = getattr(draft, field, "") or "미확인"
                source = draft.field_sources.get(field)
                source_label = {
                    "ai_hypothesis": "검증 전 AI 가설",
                    "extracted": "입력에서 정리",
                    "user_answer": "사용자 확인",
                    "unknown": "미확인",
                }.get(source, "미확인" if value == "미확인" else "분석 입력")
                with column.container(border=True):
                    st.markdown(f"**{label}** · {source_label}")
                    st.write(value)
        if draft.technical_components:
            st.markdown("**기술 구성요소**")
            st.write(" · ".join(draft.technical_components))
        if draft.value_hypotheses:
            st.markdown("**검증 전 가치 가설**")
            for item in draft.value_hypotheses:
                st.write(f"- {item}")
        return

    patent = None
    market = None
    result = None
    if job:
        patent = job.get("patent_report")
        market = job.get("market_report")
        result = job.get("result")
    if pipeline_result is not None:
        patent = patent or pipeline_result.patent
        market = market or pipeline_result.market
        result = result or pipeline_result

    if stage == 2:
        if patent is None:
            st.info("특허 비교 결과가 아직 준비되지 않았습니다.")
            return
        render_patent_report(
            patent,
            widget_suffix="_preview",
            preview=True,
        )
        return

    if stage == 3:
        if market is None:
            st.info("시장성 분석 결과가 아직 준비되지 않았습니다.")
            return
        render_market_report(market, draft, widget_suffix="_preview")
        return

    if stage == 4:
        if result is None:
            st.info("최종 실행 검토가 아직 준비되지 않았습니다.")
            return
        if result.markdown:
            st.markdown(result.markdown)
        else:
            st.warning(
                "최종 보고서가 완성되지 않았습니다. 확보된 특허·시장 결과는 보존되어 있습니다."
            )
            if result.executive_review:
                st.write(result.executive_review.decision_summary)
        estimate = result.cost_estimate
        if estimate:
            st.subheader("구현비용과 사업성 가설")
            if estimate.status == "estimated":
                st.caption(
                    f"{estimate.region} · {estimate.currency} · 기준일 {estimate.as_of} · 검증 전 추정"
                )
                if estimate.items:
                    rows = [
                        {
                            "항목": item.name,
                            "수량": f"{item.quantity:g} {item.unit}",
                            "단가 범위": f"{item.low_unit_cost:,.0f}–{item.high_unit_cost:,.0f} {estimate.unit}",
                            "구분": item.cost_type,
                            "산식·가정": item.basis,
                            "근거": ", ".join(f"M:{cid}" for cid in item.citation_ids)
                            or "검증 전 가설",
                        }
                        for item in estimate.items
                    ]
                    st.dataframe(rows, hide_index=True, width="stretch")
                totals = result.cost_totals
                if totals:
                    left, right = st.columns(2)
                    left.metric(
                        "초기 구축비 · 기준",
                        f"{totals.initial_base:,.0f} {estimate.unit}",
                    )
                    right.metric(
                        "월 반복비 · 기준",
                        f"{totals.recurring_monthly_base:,.0f} {estimate.unit}",
                    )
                    if totals.break_even_units_base is not None:
                        st.write(
                            f"단순 손익분기 판매량(기준): **{totals.break_even_units_base:,}개**"
                        )
                    st.caption(totals.calculation_note)
                if estimate.assumptions:
                    st.markdown(
                        "**비용 가정:** " + " · ".join(estimate.assumptions[:4])
                    )
                if estimate.omissions:
                    st.markdown(
                        "**포함하지 않은 비용:** " + " · ".join(estimate.omissions[:4])
                    )
            else:
                st.info("비용 범위를 산정하지 않았습니다.")
            if estimate.unknowns:
                st.caption("미확인: " + " · ".join(estimate.unknowns[:3]))


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
    s.app_view = "analysis"
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
    if number == 4:
        snapshot()
    s.stage = number


def load(text, title=""):
    s.page = "workspace"
    s.app_view = "analysis"
    input_changed()
    s.raw_input = text
    s.idea_input_buffer = text
    s.raw = text
    s.title_input = title
    s.idea_page_view = "input"
    s.show_recent = False
    s.show_examples = False
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
    if s.page == "home" and page != "home":
        s.home_intro_played = True
    if s.page == "workspace" and s.idea_page_view == "input":
        s.idea_input_buffer = s.get("raw_input", s.raw)
    s.page = page
    s.scroll_to_top = True


def start_research():
    s.home_intro_played = True
    if s.get("analysis_workflow_id"):
        resume_research()
        return
    s.page = "workspace"
    s.app_view = "analysis"
    s.stage = 1
    s.scroll_to_top = True


def resume_research():
    """입력과 결과를 초기화하지 않고 마지막에 보던 조사로 돌아간다."""
    s.page = "workspace"
    s.app_view = "analysis"
    s.scroll_to_top = True
    if s.idea_page_view == "input":
        s.raw_input = s.get("idea_input_buffer", s.raw)


has_research = bool(
    s.get("raw_input")
    or s.get("idea_input_buffer")
    or s.raw
    or s.idea_draft
    or s.get("analysis_workflow_id")
)
if s.page == "home" and not s.get("home_intro_played", False):
    from frontend.landing_motion import intro_completed

    if intro_completed():
        s.home_intro_played = True
play_intro = s.page == "home" and not s.get("home_intro_played", False)
if play_intro:
    from frontend.landing_motion import intro_styles

    st.html(intro_styles())


def settle_navigation():
    """페이지 렌더링 후 이전 화면의 스크롤 위치를 제거한다."""
    if not s.pop("scroll_to_top", False):
        return
    st.html(
        """<script>(() => {
        const navigationId = 'NAVIGATION_ID';
        const until = performance.now() + 650;
        const main = document.querySelector('[data-testid="stMain"]');
        if (!main) return;
        const previousAnchor = main.style.overflowAnchor;
        main.style.overflowAnchor = 'none';
        main.dataset.navigationId = navigationId;
        const heading = main.querySelector('h1');
        if (heading) {
            heading.setAttribute('tabindex','-1');
            heading.focus({preventScroll:true});
        }
        const controller = new AbortController();
        let stopped = false;
        const stop = () => {
            stopped = true;
            main.style.overflowAnchor = previousAnchor;
            controller.abort();
        };
        for (const event of ['wheel','touchstart','keydown']) {
            window.addEventListener(event, stop, {once:true,passive:true,signal:controller.signal});
        }
        function alignPage() {
            if (stopped) return;
            main.scrollTo({top:0,behavior:'instant'});
            if (performance.now() < until) requestAnimationFrame(alignPage);
            else stop();
        }
        requestAnimationFrame(alignPage);
        })();</script>""".replace("NAVIGATION_ID", uuid4().hex),
        unsafe_allow_javascript=True,
    )


st.html('<div id="research-top"></div>')
from frontend.information_nav import render_information_header

render_information_header(open_page)

from frontend.workflow import prune_finished_jobs

prune_finished_jobs()
from frontend.workflow_resume import browser_workflow

saved_workflow = browser_workflow(s.get("analysis_workflow_id"))
if (
    isinstance(saved_workflow, str)
    and saved_workflow
    and not s.get("analysis_workflow_id")
    and not s.get("pipeline_result")
):
    with WORKFLOW_JOBS_LOCK:
        recoverable = WORKFLOW_JOBS.get(saved_workflow)
        context = (
            deepcopy(recoverable.get("resume_context"))
            if recoverable and not recoverable.get("cancelled")
            else None
        )
    if context:
        st.info(
            "이 탭에서 시작한 분석이 있습니다. 추가 API 호출 없이 진행 상태와 결과를 다시 확인할 수 있습니다."
        )
        if st.button("이전 분석 이어보기", key="resume_previous_workflow"):
            from src.schemas import IdeaDraft

            s.idea_draft = IdeaDraft.model_validate(context["draft"])
            s.parts, s.questions = context["parts"], context["questions"]
            s.technology_area_id = context["area"]
            s.raw, s.research_title = context["raw"], context["title"]
            s.confirmed_context = True
            s.real_mode = True
            s.pipeline_error = None
            s.analysis_workflow_id = saved_workflow
            s.workflow_ready_key = (False, False)
            s.stage = 2
            resume_research()
            st.rerun()


if s.page != "workspace":
    if s.get("analysis_workflow_id"):
        workflow_progress_fragment(compact=True)
    elif s.get("pipeline_result") is not None or s.get("pipeline_error"):
        st.info("조사가 종료되었습니다. 조사 화면에서 결과와 처리 상태를 확인하세요.")
        st.button(
            "조사 결과 확인", key="return_completed_research", on_click=resume_research
        )

if s.page == "home":
    with st.container(key="landing"):
        copy_markup, art_markup = hero_parts()
        copy_column, art_column = st.columns(
            [1, 1.08], gap="large", vertical_alignment="center"
        )
        with copy_column:
            from frontend.landing_motion import intro_styles

            st.html((intro_styles() if play_intro else "") + copy_markup)
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
    render_page_nav(s.page, open_page, resume_research, has_research=has_research)
    settle_navigation()
    st.stop()
if s.page in ("about", "difference"):
    from frontend.introduction import render_introduction

    render_introduction(s.page)
    render_page_nav(s.page, open_page, resume_research, has_research=has_research)
    settle_navigation()
    st.stop()
if s.page == "history":
    render_history(s)
    render_page_nav(s.page, open_page, resume_research, has_research=has_research)
    settle_navigation()
    st.stop()

steps = [
    "아이디어 입력·초안 확인",
    "특허 비교 보고서",
    "시장성 보고서",
    "최종 실행 검토",
]
active_job = current_workflow_job() if s.get("analysis_workflow_id") else None


def review_navigation(number, label, column, key, *, icon=None):
    if column.button(
        label,
        key=key,
        type=(
            "primary"
            if s.stage == number or (key in {"rail_2", "nav_2"} and s.stage == 3)
            else "secondary"
        ),
        disabled=not can_visit(number)
        or (active_job is not None and s.stage == number),
        width="stretch",
        icon=icon,
    ):
        if active_job is not None:
            s.workflow_preview_stage = number
            st.rerun(scope="app")
        else:
            navigate(number)
            st.rerun(scope="app")


with st.container(key="stage_navigation"):
    for column, number, label in zip(
        st.columns(3),
        (1, 2, 4),
        ("1 아이디어 구체화", "2 특허·시장 검토", "3 종합 보고서"),
    ):
        review_navigation(number, label, column, f"nav_{number}")
if s.stage in (2, 3):
    for column, number, label in zip(
        st.columns(2), (2, 3), ("특허 비교", "시장성 분석")
    ):
        review_navigation(number, label, column, f"subnav_{number}")
render_quick_nav(review_navigation, open_page)


preview_stage = s.get("workflow_preview_stage")
if preview_stage:
    workflow_stage_result_dialog(
        preview_stage, s.idea_draft, active_job, s.pipeline_result
    )
if not s.confirmed_context and s.raw:
    st.caption(
        "입력·구성·질문을 바꾼 경우 아이디어 구체화에서 다시 확정해야 조사와 보고서를 볼 수 있습니다."
    )

previous_stage = s.get("displayed_stage", s.stage)
if previous_stage != s.stage:
    s.turn_direction = "forward" if s.stage > previous_stage else "backward"
s.displayed_stage = s.stage
direction = s.get("turn_direction", "still")
with st.container(key=f"workspace_{1 if s.stage == 1 else 3 if s.stage == 4 else 2}"):
    st.html(
        f'<div class="page-folio">{1 if s.stage == 1 else 3 if s.stage == 4 else 2:02d} / 03 · {steps[s.stage - 1]}</div>'
    )
    if s.get("analysis_workflow_id"):
        workflow_progress_fragment()
    if s.stage == 1:
        st.html('<div id="idea-input" class="sheet-label">01 / 아이디어 노트</div>')
        if s.get("workflow_cancelled"):
            st.info(
                "이전 분석은 취소했습니다. 입력을 수정하고 새 분석을 시작할 수 있습니다."
            )
            if RUN_LOCK.locked():
                st.caption(
                    "이미 외부로 전송된 분석 요청은 즉시 중단되지 않을 수 있으며 비용이 발생할 수 있습니다."
                )
            s.workflow_cancelled = False

        if s.idea_page_view == "generate_example":
            if not live_available():
                s.ai_draft_error = (
                    "예시 초안을 만들려면 .env에 OPENAI_API_KEY를 설정해야 합니다."
                )
                s.idea_page_view = "input"
            else:
                with st.spinner("예시 아이디어를 LLM 초안으로 구체화하고 있습니다…"):
                    make_ai_draft()
                s.idea_page_view = "draft" if s.idea_draft is not None else "input"
            st.rerun()

        if s.idea_page_view == "input":
            st.title("어떤 아이디어를 조사할까요?")
            st.caption("한두 문장으로 적어 주세요. AI가 분석용 초안을 만들어 드립니다.")
            s.setdefault("raw_input", s.get("idea_input_buffer", s.raw))
            raw = st.text_area(
                "아이디어",
                height=150,
                max_chars=MAX_IDEA_CHARS,
                key="raw_input",
                on_change=input_changed,
                disabled=bool(s.get("analysis_workflow_id")),
                placeholder="예: 공장 설비의 진동 데이터를 분석해 고장을 미리 알려주는 서비스",
                label_visibility="collapsed",
            )
            st.caption(f"{len(raw):,} / {MAX_IDEA_CHARS:,}자")
            if s.get("ai_draft_error"):
                st.error(s.ai_draft_error)
            if st.button(
                "AI 초안 만들기",
                key="create_idea_draft",
                type="primary",
                width="stretch",
                disabled=bool(s.get("analysis_workflow_id")),
            ):
                if len(raw.strip()) < MIN_IDEA_CHARS:
                    st.error(f"아이디어를 {MIN_IDEA_CHARS}자 이상 입력해 주세요.")
                elif not live_available():
                    st.error(
                        "실제 AI 초안을 만들려면 .env에 OPENAI_API_KEY를 설정해야 합니다."
                    )
                else:
                    prepare_input()
                    with st.spinner("AI가 아이디어 초안을 작성하고 있습니다…"):
                        make_ai_draft()
                    if s.idea_draft is not None:
                        s.idea_page_view = "draft"
                    st.rerun()
            st.caption("초안 생성과 이후 분석에서 외부 API 비용이 발생할 수 있습니다.")

            examples_col, recent_col = st.columns(2)
            if examples_col.button(
                "예시 아이디어", key="toggle_examples", width="stretch"
            ):
                s.show_examples = not s.show_examples
                s.show_recent = False
            if recent_col.button("최근 입력", key="toggle_recent", width="stretch"):
                s.show_recent = not s.show_recent
                s.show_examples = False

            if s.show_examples:
                with st.container(border=True):
                    st.caption(
                        "예시를 선택하면 LLM 초안만 작성합니다. 전체 분석은 초안을 확인한 뒤 시작하세요."
                    )
                    examples = [
                        (
                            "공장 설비 고장 예측",
                            "공장 설비의 진동 데이터를 분석해 고장을 미리 알려주는 서비스를 만들고 싶어요.",
                        ),
                        (
                            "불량 검사 자동화",
                            "기존 생산라인에 카메라와 조명을 설치해 제품 불량을 자동으로 찾아내고 싶어요.",
                        ),
                        (
                            "현장 작업 지원",
                            "작업자가 설비 점검 절차와 과거 고장 사례를 현장에서 빠르게 확인하는 도구를 만들고 싶어요.",
                        ),
                    ]
                    for index, (title, text) in enumerate(examples):
                        st.button(
                            title,
                            key=f"idea_example_{index}",
                            width="stretch",
                            on_click=open_example_draft,
                            args=(text, title),
                        )
            if s.show_recent:
                with st.container(border=True):
                    if not s.recent:
                        st.caption("현재 세션에 저장된 최근 입력이 없습니다.")
                    else:
                        st.caption("이 세션에서 입력한 최근 아이디어")
                        for index, item in enumerate(s.recent):
                            st.button(
                                item["title"] or item["text"][:55],
                                key=f"recent_{index}",
                                width="stretch",
                                disabled=bool(s.get("analysis_workflow_id")),
                                on_click=load,
                                args=(item["text"], item["title"]),
                            )
        elif s.idea_draft is None:
            s.idea_page_view = "input"
            st.rerun()
        elif s.idea_draft.status == "rejected":
            st.error(s.idea_draft.rejection_reason)
            if st.button("아이디어 다시 입력", key="retry_idea_input"):
                s.idea_draft = None
                s.idea_page_view = "input"
                s.ai_draft_error = None
                st.rerun()
        else:
            draft = s.idea_draft
            st.info(
                "AI 제안은 검증 전 초안입니다. 내용을 확인·수정한 뒤 전체 분석을 시작하세요."
            )
            if st.button("← 입력 수정", key="back_to_idea_input"):
                s.idea_page_view = "input"
                st.rerun()

            key_suffix = str(s.version)
            title_value = st.text_input(
                "아이디어 이름", value=draft.title, key=f"draft_title_{key_suffix}"
            )
            first, second = st.columns(2, gap="medium")
            core_fields = {
                "problem": "해결할 문제",
                "technology": "핵심 기술",
                "customers": "목표 고객",
                "difference": "차별점",
            }
            values = {}
            for index, (field, label) in enumerate(core_fields.items()):
                with first if index % 2 == 0 else second:
                    values[field] = st.text_area(
                        label,
                        value=getattr(draft, field),
                        key=f"draft_{field}_{key_suffix}",
                        height=76,
                    )
                    source = draft.field_sources.get(field)
                    if source == "ai_hypothesis":
                        st.caption("AI 제안 가설 · 확인 후 수정하세요")
                    elif source == "extracted":
                        st.caption("입력에서 정리됨")
                    elif field in draft.missing_fields:
                        st.caption("미확인 · 직접 보완해 주세요")

            values["revenue"] = st.text_area(
                "수익모델",
                value=draft.revenue,
                key=f"draft_revenue_{key_suffix}",
                height=76,
                help="AI가 제안한 방식은 검증 전 가설입니다. 실제 계획에 맞게 수정할 수 있습니다.",
            )
            revenue_source = draft.field_sources.get("revenue")
            if revenue_source == "ai_hypothesis":
                st.caption("AI 제안 가설 · 확인 후 수정하세요")
            elif revenue_source == "extracted":
                st.caption("입력에서 정리됨")
            elif "revenue" in draft.missing_fields:
                st.caption("미확인 · 직접 보완해 주세요")

            with st.expander("상세 내용과 조사 설정", expanded=False):
                details = {}
                for field, label in (
                    ("current_alternative", "현재 대안"),
                    ("target_segment", "초기 고객 세그먼트"),
                ):
                    details[field] = st.text_area(
                        label,
                        value=getattr(draft, field),
                        key=f"draft_{field}_{key_suffix}",
                        height=68,
                    )
                components = st.text_area(
                    "기술 구성요소 · 한 줄에 하나씩",
                    value="\n".join(draft.technical_components),
                    key=f"draft_components_{key_suffix}",
                    height=84,
                )
                hypotheses = st.text_area(
                    "검증 전 가치 가설 · 한 줄에 하나씩",
                    value="\n".join(draft.value_hypotheses),
                    key=f"draft_hypotheses_{key_suffix}",
                    height=68,
                )
                area_choice = st.selectbox(
                    "특허 조사 분야",
                    ["AUTO", "SF-02", "SF-05"],
                    format_func=lambda key: {
                        "AUTO": "자동 · 전체 특허 색인",
                        "SF-02": "AI 비전 품질검사 우선",
                        "SF-05": "지능형 공정제어 우선",
                    }[key],
                    key="technology_area_choice",
                )
                s.technology_area_id = None if area_choice == "AUTO" else area_choice
                st.caption(
                    "분야를 선택해도 관련 결과가 부족하면 전체 특허 색인으로 검색 범위를 넓힙니다."
                )

            if st.button(
                "수정 내용으로 전체 분석 시작",
                key="start_idea_analysis",
                type="primary",
                width="stretch",
                disabled=bool(s.get("analysis_workflow_id")),
            ):
                component_values = [
                    item.strip() for item in components.splitlines() if item.strip()
                ][:7]
                hypothesis_values = [
                    item.strip() for item in hypotheses.splitlines() if item.strip()
                ][:3]
                missing = save_draft_and_start(
                    draft,
                    title_value,
                    {field: value.strip() for field, value in values.items()},
                    component_values,
                    hypothesis_values,
                    {field: value.strip() for field, value in details.items()},
                )
                if missing:
                    st.error(
                        "분석을 시작하려면 필수 항목을 입력해 주세요: "
                        + ", ".join(missing)
                    )
                else:
                    st.rerun()
            st.caption(
                "특허·시장 분석과 최종 검토에 추가 API 비용이 발생할 수 있습니다."
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
                render_patent_report(patent)
                if patent.status in {"error", "partial"} and not s.get(
                    "analysis_workflow_id"
                ):
                    st.caption(
                        "특허 비교가 완료되지 않아 다시 조사할 수 있습니다. 재실행은 API 비용이 발생할 수 있습니다."
                    )
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
                elif patent.status == "no_results" and not s.get(
                    "analysis_workflow_id"
                ):
                    st.caption(
                        "검색 분야를 자동·전체 색인으로 넓혀 특허와 시장 근거를 다시 조사할 수 있습니다. API 비용이 발생할 수 있습니다."
                    )
                    if st.button(
                        "전체 특허 색인으로 다시 조사 · API 비용 발생",
                        key="retry_empty_patent_global",
                        disabled=RUN_LOCK.locked(),
                    ):
                        s.technology_area_choice = "AUTO"
                        s.technology_area_id = None
                        s.pipeline_result = None
                        s.analysis_sources = None
                        s.analysis_key = ""
                        start_report_workflow()
                        st.rerun()
                if s.get("analysis_workflow_id"):
                    st.caption(
                        "시장성 분석은 계속 진행됩니다. 준비된 결과는 위 메뉴에서 확인하세요."
                    )
                else:
                    left, right = st.columns(2)
                    left.button("← 아이디어 수정", on_click=navigate, args=(1,))
                    if right.button("시장성 보고서 →", type="primary"):
                        s.stage = 3
                        st.rerun()
        else:
            st.warning(
                "실제 분석 결과가 없습니다. 아이디어 초안을 검토한 뒤 분석을 시작해 주세요."
            )
            st.button("아이디어 입력으로", on_click=navigate, args=(1,))
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
            render_market_report(market, s.idea_draft)
            if s.get("analysis_workflow_id"):
                st.caption(
                    "최종 실행 검토를 작성 중입니다. 완료되면 종합 보고서에서 확인하세요."
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
            st.warning(
                "실제 시장 분석 결과가 아직 없습니다. 특허 단계에서 분석을 시작해 주세요."
            )
            st.button("특허 분석으로", on_click=navigate, args=(2,))
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
            s.pipeline_result.patent.status in {"error", "partial"}
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

if previous_stage != s.stage:
    s.scroll_to_top = True
settle_navigation()
