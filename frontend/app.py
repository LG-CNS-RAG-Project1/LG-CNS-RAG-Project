"""큰 입력란 → 구성 확인 → 특허·시장 자료 선정 → 보고서의 단계형 UI."""

import sys
import time
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
    SOURCE_LABELS,
    analysis_key,
    app_password,
    cost_markdown,
    cost_rows_list,
    friendly_error,
    live_available,
    password_matches,
    run_line,
)
from src.generation.input_guard import MAX_IDEA_CHARS
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
from frontend.automatic import automatic_links
from frontend.presentation import hero_parts, brand_style

st.set_page_config(page_title="IdeaLens · 빠른 조사", page_icon="▤", layout="wide")
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


def prepare_input():
    text = s.get("raw_input", s.raw).strip()
    title = s.get("title_input", s.research_title).strip()
    if len(text) < 10:
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
    s.parts = [draft.technology] if draft.technology else [draft.problem]
    s.questions = default_questions(draft)
    s.version += 1
    invalidate_context()
    s.stage = 2


def make_ai_draft():
    from src.generation.idea_parser import parse_idea

    try:
        draft = parse_idea(s.get("raw_input", s.raw).strip())
        s.idea_draft = draft
        s.real_mode = False
        s.pipeline_result = None
        if draft.status == "complete":
            apply_complete_draft(draft)
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
    if number == 1:
        return True
    if number == 2:
        return len(s.get("raw_input", s.raw).strip()) >= 10
    if not s.confirmed_context:
        return False
    if number == 4 and s.real_mode:
        return s.pipeline_result is not None
    return number == 3 or len(selected_sources(s.raw, s.selected)) >= 2


def navigate(number):
    s.page = "workspace"
    sync_context()
    if not can_visit(number):
        return
    if number == 2 and not prepare_input():
        return
    if number == 4:
        snapshot()
    s.stage = number


def load(text, title=""):
    s.raw_input = text
    s.title_input = title
    invalidate_context()
    s.stage = 1
    s.page = "workspace"


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
    s.stage = 2 if s.raw else 1


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


def render_input():
    st.html('<div id="idea-input" class="sheet-label">01 / 아이디어 노트</div>')
    s.setdefault("raw_input", s.raw)
    s.setdefault("title_input", s.research_title)
    st.title("어떤 아이디어를 조사할까요?")
    st.caption("내용을 입력하고 구성을 확인한 뒤, 특허와 시장 근거를 함께 살펴보세요.")
    main, recent = st.columns([2.6, 1], gap="large")
    with main:
        with st.container(border=True):
            st.text_input(
                "아이디어 명칭 (선택)",
                max_chars=100,
                key="title_input",
                on_change=input_changed,
            )
            raw = st.text_area(
                "아이디어 내용",
                height=190,
                max_chars=MAX_IDEA_CHARS,
                key="raw_input",
                on_change=input_changed,
                placeholder="해결하려는 문제, 핵심 기술과 동작 방식, 예상 효과를 자유롭게 적어 주세요.",
            )
            st.caption(f"{len(raw):,} / {MAX_IDEA_CHARS:,}자 · 최소 10자")
            a, b = st.columns(2)
            a.button(
                "입력 템플릿",
                on_click=load,
                args=("해결할 문제:\n\n핵심 아이디어와 동작 방식:\n\n예상 효과:",),
            )
            b.button("예시 불러오기", on_click=load, args=(DEMO_TEXT, EXAMPLE["idea"]))
            st.selectbox(
                "특허 색인 분야",
                ["SF-02", "SF-05"],
                format_func=lambda key: (
                    "SF-02 · AI 비전 품질검사"
                    if key == "SF-02"
                    else "SF-05 · 지능형 공정제어"
                ),
                key="technology_area_id",
            )
            if st.button("AI로 항목 초안 만들기 · 재질문", use_container_width=True):
                if len(raw.strip()) < 10:
                    st.error("아이디어 내용을 10자 이상 입력해 주세요.")
                else:
                    prepare_input()
                    with st.spinner("AI가 아이디어를 구조화하는 중…"):
                        make_ai_draft()
            if st.session_state.get("ai_draft_error"):
                st.error(st.session_state.ai_draft_error)
            if s.idea_draft is not None:
                draft = s.idea_draft
                if draft.status == "rejected":
                    st.warning(draft.rejection_reason)
                elif draft.status == "needs_input":
                    st.info("빈 항목을 보완해 주세요. ‘모름’도 입력할 수 있습니다.")
                    with st.form("ai_followup_form"):
                        for field, question in draft.questions.items():
                            st.text_input(
                                question, key=f"ai_answer_{field}_{draft.rounds}"
                            )
                        st.form_submit_button("답변 반영", on_click=apply_ai_answers)
                elif draft.status == "complete":
                    st.success(
                        "AI 초안이 준비됐습니다. 구성·질문을 검토한 뒤 실제 조사를 실행할 수 있습니다."
                    )
            if st.button(
                "핵심 구성 확인하기 →", type="primary", use_container_width=True
            ):
                if len(raw.strip()) < 10:
                    st.error("아이디어 내용을 10자 이상 입력해 주세요.")
                else:
                    prepare_input()
                    needs_ai = (
                        live_available()
                        and s.raw != DEMO_TEXT
                        and not (s.idea_draft and s.idea_draft.status == "complete")
                    )
                    if needs_ai:
                        with st.spinner("AI가 아이디어를 구조화하는 중…"):
                            make_ai_draft()
                    if not needs_ai or s.real_mode:
                        s.stage = 2
                    st.rerun()
        st.caption(
            "OpenAI 키가 있으면 직접 입력한 아이디어를 AI로 구조화한 뒤 실제 조사로 이어집니다."
            " 키가 없으면 구성만 작성하는 시연 경로로 진행합니다."
        )
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
                )


def render_context():
    st.title("조사할 내용을 확인해 주세요")
    st.caption("핵심 구성이 두 조사의 공통 기준이 됩니다. 직접 수정한 후 시작하세요.")
    editor, original = st.columns([1.7, 1], gap="large")
    with editor:
        components_tab, questions_tab = st.tabs(["핵심 구성", "검토 질문·조건"])
        with components_tab:
            with st.container(height=420, border=False):
                st.subheader("핵심 구성")
                st.info(
                    "AI가 추출한 초안입니다. 검색 전에 내용을 확인하고 수정해 주세요."
                    if s.real_mode
                    and s.idea_draft
                    and s.idea_draft.status == "complete"
                    else (
                        "예시는 미리 작성된 구성입니다. AI 추출 결과가 아닙니다."
                        if s.raw == DEMO_TEXT
                        else "특징 추출 미연결 · 핵심 구성을 직접 작성해 주세요."
                    )
                )
                for i, part in enumerate(s.parts):
                    with st.container(border=True):
                        value, up, down, remove = st.columns([8, 1, 1, 1])
                        value.text_area(
                            f"구성 {i+1}",
                            value=part,
                            key=f"part_{s.version}_{i}",
                            height=85,
                            on_change=sync_context,
                        )
                        up.button(
                            "↑",
                            key=f"up_{i}",
                            disabled=i == 0,
                            on_click=edit_part,
                            args=(i, -1),
                            help="위로 이동",
                        )
                        down.button(
                            "↓",
                            key=f"down_{i}",
                            disabled=i == len(s.parts) - 1,
                            on_click=edit_part,
                            args=(i, 1),
                            help="아래로 이동",
                        )
                        remove.button(
                            "×",
                            key=f"remove_{i}",
                            on_click=edit_part,
                            args=(i, 0),
                            help="구성 삭제",
                        )
                st.button("＋ 구성 추가", disabled=len(s.parts) >= 7, on_click=add_part)
                st.caption("최대 7개 · 빈 구성과 중복 구성은 정리해 주세요.")
        with questions_tab:
            with st.container(height=420, border=False):
                st.subheader("검토 질문과 도입 조건")
                st.caption(
                    "시장 요구 → 관련 구성 → 특허 해결 방식의 연결을 검토할 질문입니다."
                )
                for q in s.questions:
                    with st.container(border=True):
                        st.text_area(
                            f"{q['id']} 검토 질문",
                            value=q["question"],
                            key=f"question_{s.version}_{q['id']}",
                            on_change=sync_context,
                            height=85,
                        )
                        st.text_input(
                            "도입·사용 조건",
                            value=q["condition"],
                            key=f"condition_{s.version}_{q['id']}",
                            on_change=sync_context,
                        )
                        st.button(
                            "질문 삭제",
                            key=f"delete_{q['id']}",
                            on_click=remove_question,
                            args=(q["id"],),
                        )
                st.button(
                    "＋ 질문 추가",
                    disabled=len(s.questions) >= 5,
                    on_click=add_question,
                )
        if st.button(
            f"{len(s.parts)}개 구성으로 조사 시작하기 →",
            type="primary",
            use_container_width=True,
        ):
            parts = [
                s.get(f"part_{s.version}_{i}", p).strip() for i, p in enumerate(s.parts)
            ]
            sync_context()
            error = validate_parts(parts) or validate_questions(s.questions)
            if error:
                st.error(error)
            else:
                s.parts = parts
                s.questions = [
                    dict(
                        q,
                        question=q["question"].strip(),
                        condition=q["condition"].strip(),
                    )
                    for q in s.questions
                ]
                s.confirmed_context = True
                if s.real_mode and s.idea_draft and s.idea_draft.status == "complete":
                    s.pipeline_result = None
                    s.stage = 3
                else:
                    s.selected = [source["id"] for source in candidates(s.raw)]
                    s.stage = 3
                st.rerun()
    with original:
        with st.container(border=True):
            st.subheader("입력한 아이디어")
            st.write(s.research_title)
            st.write(s.raw)
        if s.real_mode and s.idea_draft and s.idea_draft.status == "complete":
            with st.container(border=True):
                st.subheader("AI 구조화 결과")
                for field, label in FIELD_LABELS.items():
                    source = SOURCE_LABELS.get(
                        s.idea_draft.field_sources.get(field, ""), "입력에서 추출"
                    )
                    st.text(f"{label}: {getattr(s.idea_draft, field) or '모름'}")
                    st.caption(source)
        st.warning(
            "구성은 검색 기준입니다. 시장 수요나 특허성을 확인한 결과가 아닙니다."
        )
    st.button("← 입력 수정", on_click=navigate, args=(1,))


def render_demo_review():
    chosen = selected_sources(s.raw, s.selected)
    bar, action = st.columns([3, 1])
    bar.subheader(s.research_title or "문헌 선정·근거 검토")
    with action:
        if st.button(
            "종합 보고서 생성 →",
            type="primary",
            disabled=len(chosen) < 2,
            use_container_width=True,
        ):
            snapshot()
            s.stage = 4
            st.rerun()
    st.caption(
        "특허·시장 조사는 별도 결과로 검토합니다. 현재 후보는 실제 검색 결과가 아닌 가상 자료입니다."
    )
    left, middle, right = st.columns([1, 2.1, 1.5], gap="medium")
    with left:
        with st.container(height=500, border=False):
            st.subheader("아이디어의 구성")
            for i, part in enumerate(s.parts, 1):
                with st.container(border=True):
                    st.caption(f"구성 {i}")
                    st.write(part)
            st.button("구성 수정", on_click=navigate, args=(2,))
    with middle:
        with st.container(height=500, border=False):
            st.subheader("후보 자료")
            connections, patent, market = st.tabs(
                ["자동 연결 결과", "특허·기술 조사", "시장·기업 조사"]
            )
            for tab, kinds in [(patent, {"특허"}), (market, {"시장", "기업"})]:
                with tab:
                    rows = [r for r in candidates(s.raw) if r["kind"] in kinds]
                    st.caption(
                        "가상 예시 준비 · 실검색 미연결"
                        if rows
                        else "검색 미연결 · 결과 없음과 다릅니다"
                    )
                    if not rows:
                        st.info(
                            "실제 검색은 연결 전입니다. 이 입력에 가상 분석을 붙이지 않았습니다."
                        )
                    for row in rows:
                        with st.container(border=True):
                            st.caption(
                                f"{row['id']} · {row['kind']} · 시연용 가상 자료"
                            )
                            st.markdown(f"#### {row['title']}")
                            st.write(row["quote"])
                            related = [
                                q["id"]
                                for q in s.questions
                                if row["id"]
                                in effective_links()
                                .get(q["id"], {})
                                .get("market_ids", [])
                                + effective_links()
                                .get(q["id"], {})
                                .get("patent_ids", [])
                                + effective_links()
                                .get(q["id"], {})
                                .get("counter_ids", [])
                            ]
                            st.caption(
                                "연결 검토 질문: "
                                + (", ".join(related) or "아직 미연결")
                            )
                            with st.expander("문헌 상세·원문 근거"):
                                st.caption(row["location"])
                                st.write(row["limit"])
                                st.caption(
                                    f"대상: {row['entity']} · 기준 시점: {row['period']} · 문헌 버전: {row['version']}"
                                )
                                st.caption(
                                    "구성별 대응: 미검토 · 실제 원문·출처·도면 미연결"
                                )
                            st.button(
                                (
                                    "선택 해제"
                                    if row["id"] in s.selected
                                    else "＋ 검토 자료에 추가"
                                ),
                                key=f"pick_{row['id']}",
                                on_click=select,
                                args=(row["id"],),
                                use_container_width=True,
                            )
    with right:
        with st.container(height=500, border=False):
            st.subheader("선택한 검토 자료")
            count = sum(r["kind"] == "특허" for r in chosen)
            st.caption(f"특허 {count}건 · 시장·기업 {len(chosen)-count}건")
            if not chosen:
                st.info("중앙 후보에서 보고서에 사용할 자료를 선택하세요.")
            for row in chosen:
                with st.container(border=True):
                    st.write(f"[{row['id']}] {row['title']}")
                    st.button(
                        "제외",
                        key=f"exclude_{row['id']}",
                        on_click=select,
                        args=(row["id"],),
                    )
            st.caption(
                "2건 선택은 보고서 열기 조건일 뿐입니다. 질문별 연결은 별도로 검토합니다."
            )
            if chosen and (count == 0 or count == len(chosen)):
                st.warning("한 영역만 선택됐어요. 다른 영역은 미확인으로 표시합니다.")
            st.markdown("**질문별 연결 상태**")
            for entry in review_rows(
                s.raw, s.parts, s.selected, s.questions, effective_links()
            ):
                st.write(entry["question"])
                st.caption(entry["status"])
            st.caption(
                "중앙 자동 연결 결과에서 기준별 판단 과정과 양쪽 근거를 확인하세요."
            )
    with connections:
        with st.expander("연결 검토 기준 6가지"):
            st.markdown(
                "- 사용 맥락: 고객·작업·환경이 같은가?\n- 해결 과제: 같은 문제를 다루는가?\n- 기술 구성: 입력·부품·방법·출력이 대응하는가?\n- 요구 성능: 시험 조건과 수치가 비교 가능한가?\n- 도입 제약: 가격·설치·운영·인증 조건이 맞는가?\n- 근거 범위: 기업·제품·기간·국가와 인용의 범위가 맞는가?"
            )
        st.info(
            "1단계에서 확정한 질문·조건으로 자동 결과를 구성했습니다. 현재는 사전 작성된 예시 규칙의 시연이며 실제 AI 분석이 아닙니다. 수정한 입력은 분석 미연결로 판단 보류합니다."
        )
        for q in s.questions:
            saved = effective_links().get(q["id"], {})
            with st.expander(f"{q['id']} · {q['question']}", expanded=False):
                st.caption(f"도입 조건: {q['condition'] or '미입력'}")
                if q["id"] in s.excluded_questions:
                    st.warning(
                        "보고서 연결 검토에서 제외한 질문입니다. 자료의 원문 목록은 유지됩니다."
                    )
                else:
                    entry = next(
                        e
                        for e in review_rows(
                            s.raw,
                            s.parts,
                            s.selected,
                            s.questions,
                            effective_links(),
                        )
                        if e["id"] == q["id"]
                    )
                    st.caption(entry["status"])
                    st.write(f"연결 유형: {entry['relation']}")
                    st.write(entry["reason"])
                    st.caption(f"다음 검증: {entry['next_check']}")
                    with st.expander("판단 과정·기준별 근거 보기"):
                        for criterion in entry["assessment"]:
                            st.markdown(
                                f"**{criterion['criterion']} · {criterion['result']}**"
                            )
                            st.write(criterion["reason"])
                            st.caption(
                                "근거: "
                                + (
                                    ", ".join(criterion["source_ids"])
                                    or "없음 · 추가 검증 필요"
                                )
                            )
                        if not entry["assessment"]:
                            st.caption(
                                "사용자 수정 내용입니다. 자동 기준 평가를 통과했다는 의미는 아닙니다."
                            )
                        st.write(f"한계: {entry['conditions']}")
                        st.write(f"반대·미조사: {entry['counter_reason']}")
                    st.button(
                        "이 연결 제외",
                        key=f"exclude_auto_{q['id']}",
                        on_click=drop_link,
                        args=(q["id"],),
                    )
                st.button(
                    "자동 결과로 되돌리기",
                    key=f"restore_{q['id']}",
                    on_click=restore_link,
                    args=(q["id"],),
                )
                with st.expander("필요할 때만 결과 수정"):
                    with st.form(f"link_form_{s.link_version}_{q['id']}"):
                        labels = {
                            f"C{i}": f"C{i} · {p}" for i, p in enumerate(s.parts, 1)
                        }
                        comps = st.multiselect(
                            "관련 구성",
                            key=f"link_{s.link_version}_{q['id']}_comps",
                            options=list(labels),
                            default=[
                                i for i in saved.get("component_ids", []) if i in labels
                            ],
                            format_func=lambda i: labels[i],
                        )
                        market_ids = [r["id"] for r in chosen if r["kind"] != "특허"]
                        patent_ids = [r["id"] for r in chosen if r["kind"] == "특허"]
                        markets = st.multiselect(
                            "시장 근거",
                            key=f"link_{s.link_version}_{q['id']}_markets",
                            options=market_ids,
                            default=[
                                i
                                for i in saved.get("market_ids", [])
                                if i in market_ids
                            ],
                        )
                        patents = st.multiselect(
                            "특허 근거",
                            key=f"link_{s.link_version}_{q['id']}_patents",
                            options=patent_ids,
                            default=[
                                i
                                for i in saved.get("patent_ids", [])
                                if i in patent_ids
                            ],
                        )
                        relation = st.selectbox(
                            "연결 유형",
                            key=f"link_{s.link_version}_{q['id']}_relation",
                            options=RELATIONS,
                            index=RELATIONS.index(saved.get("relation", RELATIONS[0])),
                        )
                        reason = st.text_area(
                            "연결 이유 (사용자 가설)",
                            key=f"link_{s.link_version}_{q['id']}_reason",
                            value=saved.get("reason", ""),
                        )
                        conditions = st.text_area(
                            "사용 환경·성능·기업·시점의 차이와 한계",
                            key=f"link_{s.link_version}_{q['id']}_conditions",
                            value=saved.get("conditions", ""),
                        )
                        counter_ids = st.multiselect(
                            "반대·충돌 근거",
                            key=f"link_{s.link_version}_{q['id']}_counter",
                            options=[r["id"] for r in chosen],
                            default=[
                                i
                                for i in saved.get("counter_ids", [])
                                if i in s.selected
                            ],
                        )
                        counter_reason = st.text_area(
                            "반대 근거 또는 미조사 사항",
                            key=f"link_{s.link_version}_{q['id']}_counter_reason",
                            value=saved.get("counter_reason", ""),
                        )
                        next_check = st.text_area(
                            "다음 검증 과제 *",
                            key=f"link_{s.link_version}_{q['id']}_next_check",
                            value=saved.get("next_check", ""),
                        )
                        submitted = st.form_submit_button(
                            "연결 검토 저장", key=f"save_{q['id']}"
                        )
                    if submitted:
                        link = dict(
                            question_id=q["id"],
                            component_ids=comps,
                            market_ids=markets,
                            patent_ids=patents,
                            relation=relation,
                            reason=reason,
                            conditions=conditions,
                            counter_ids=counter_ids,
                            counter_reason=counter_reason,
                            next_check=next_check,
                        )
                        error = validate_link(
                            link, s.raw, s.parts, s.selected, s.questions
                        )
                        if error:
                            st.error(error)
                        else:
                            link["origin"] = "user"
                            s.excluded_questions = [
                                i for i in s.excluded_questions if i != q["id"]
                            ]
                            s.links[q["id"]] = link
                            s.report_snapshot = None
                            st.rerun()
                    if q["id"] in s.links:
                        st.caption("저장된 사용자 검토 · 원문 검증 전")
                        st.button(
                            "이 연결 제외",
                            key=f"drop_link_{q['id']}",
                            on_click=lambda qid=q["id"]: drop_link(qid),
                        )
                ids = list(
                    dict.fromkeys(
                        saved.get("market_ids", [])
                        + saved.get("patent_ids", [])
                        + saved.get("counter_ids", [])
                    )
                )
                for row in chosen:
                    if row["id"] in ids:
                        st.markdown(f"**[{row['id']}] {row['title']}**")
                        st.write(row["quote"])
                        related = [
                            q["id"]
                            for q in s.questions
                            if row["id"]
                            in effective_links().get(q["id"], {}).get("market_ids", [])
                            + effective_links().get(q["id"], {}).get("patent_ids", [])
                            + effective_links().get(q["id"], {}).get("counter_ids", [])
                        ]
                        st.caption(
                            "연결 검토 질문: " + (", ".join(related) or "아직 미연결")
                        )
                        st.caption(f"{row['location']} · {row['limit']}")


from frontend.workspace_view import (
    render_live_review,
    render_report,
    render_history,
    report_payload,
)


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
    st.stop()
if s.page in ("about", "difference"):
    from frontend.introduction import render_introduction

    render_introduction(s.page)
    st.button("홈에서 살펴보기 ↗", on_click=open_page, args=("home",))
    st.stop()
if s.page == "history":
    render_history(s)
    st.stop()

step = 1 if s.stage <= 2 else s.stage - 1
with st.container(key="stepnav"):
    for number, label, col in zip(
        [1, 3, 4], ["아이디어 구체화", "특허·시장 검토", "종합 보고서"], st.columns(3)
    ):
        target = 2 if number == 1 and s.parts else number
        col.button(
            f"{1 if number == 1 else number - 1}  {label}",
            key=f"nav_{number}",
            type=(
                "primary"
                if (s.stage <= 2 if number == 1 else s.stage == number)
                else "secondary"
            ),
            disabled=not can_visit(target),
            on_click=navigate,
            args=(target,),
            use_container_width=True,
        )

previous = s.get("view_marker")
marker = f"{s.page}-{s.stage}"
with st.container(key=f"workspace_{step}"):
    st.html(f'<div class="page-folio">RESEARCH NOTE / 0{step} — 03</div>')
    if s.stage <= 2:
        left, right = st.columns(2)
        left.button(
            "아이디어 작성",
            on_click=navigate,
            args=(1,),
            use_container_width=True,
            type="primary" if s.stage == 1 else "secondary",
        )
        right.button(
            "구성·질문 확인",
            on_click=navigate,
            args=(2,),
            disabled=not can_visit(2),
            use_container_width=True,
            type="primary" if s.stage == 2 else "secondary",
        )
        if s.stage == 1:
            render_input()
        else:
            render_context()
    elif s.stage == 3:
        if s.real_mode:
            render_live_review(s, run_real_pipeline, current_analysis_key, navigate)
        else:
            render_demo_review()
    elif s.stage == 4:
        st.button("← 문헌 선정으로", on_click=navigate, args=(3,))
        payload = report_payload(s)
        if payload:
            render_report(s, payload)
        else:
            st.info("먼저 조사와 근거 검토를 완료해 주세요.")
    st.caption(
        "조사 결과는 근거 검토를 위한 초안입니다. 출처와 적용 조건을 확인해 주세요."
    )

s.view_marker = marker
if previous != marker:
    st.html(
        """<script>requestAnimationFrame(() => {
        const main = document.querySelector('[data-testid="stMain"]');
        if (main) main.scrollTo({top: 0, behavior: 'instant'});
    });</script>""",
        unsafe_allow_javascript=True,
    )
