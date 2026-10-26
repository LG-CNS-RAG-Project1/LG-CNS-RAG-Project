"""큰 입력란 → 구성 확인 → 특허·시장 자료 선정 → 보고서의 단계형 UI."""

import sys
from copy import deepcopy
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
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
from frontend.workspace import EXAMPLE
from frontend.automatic import automatic_links
from frontend.presentation import hero

st.set_page_config(page_title="IdeaLens · 빠른 조사", page_icon="▤", layout="wide")
st.html(Path(__file__).with_name("styles.css").read_text(encoding="utf-8"))
for key, value in {
    "stage": 1,
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
}.items():
    if key not in st.session_state:
        st.session_state[key] = value
s = st.session_state


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
        s.saved_memo = ""
        item = {"text": text, "title": title}
        s.recent = [item] + [x for x in s.recent if x != item][:4]
    return True


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
    return number == 3 or len(selected_sources(s.raw, s.selected)) >= 2


def navigate(number):
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


with st.container(key="brandbar"):
    brand, section, status = st.columns([1, 2, 2])
    brand.button(
        "▤ IdeaLens", key="home", on_click=navigate, args=(1,), help="홈페이지로 이동"
    )
    section.caption("시장·특허 조사")
    status.caption("로컬 시연 · 실제 분석 미연결")
steps = ["아이디어 입력", "구성·검토 질문", "근거·연결 검토", "종합 보고서"]
with st.container(key="stepnav"):
    for i, column in enumerate(st.columns(4), 1):
        column.button(
            f"{i}  {steps[i-1]}",
            key=f"nav_{i}",
            type="primary" if s.stage == i else "secondary",
            disabled=not can_visit(i),
            on_click=navigate,
            args=(i,),
            use_container_width=True,
        )
if not s.confirmed_context and s.raw:
    st.caption(
        "입력·구성·질문을 바꾼 경우 2단계에서 다시 확정해야 조사와 보고서를 볼 수 있습니다."
    )

if s.stage == 1:
    st.html(hero())
previous_stage = s.get("displayed_stage", s.stage)
if previous_stage != s.stage:
    s.turn_direction = "forward" if s.stage > previous_stage else "backward"
s.displayed_stage = s.stage
direction = s.get("turn_direction", "still")
with st.container(key=f"sheet_{s.stage}_{direction}"):
    st.html(f'<div class="page-folio">{s.stage:02d} / 04 · {steps[s.stage - 1]}</div>')
    if s.stage == 1:
        st.html('<div id="idea-input" class="sheet-label">01 / 아이디어 노트</div>')
        s.setdefault("raw_input", s.raw)
        s.setdefault("title_input", s.research_title)
        st.title("어떤 아이디어를 조사할까요?")
        st.caption(
            "내용을 입력하고 구성을 확인한 뒤, 특허와 시장 근거를 함께 살펴보세요."
        )
        main, recent = st.columns([2.4, 1], gap="large")
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
                    height=300,
                    max_chars=20000,
                    key="raw_input",
                    on_change=input_changed,
                    placeholder="해결하려는 문제, 핵심 기술과 동작 방식, 예상 효과를 자유롭게 적어 주세요.",
                )
                st.caption(f"{len(raw):,} / 20,000자 · 최소 10자")
                a, b = st.columns(2)
                a.button(
                    "입력 템플릿",
                    on_click=load,
                    args=("해결할 문제:\n\n핵심 아이디어와 동작 방식:\n\n예상 효과:",),
                )
                b.button(
                    "예시 불러오기", on_click=load, args=(DEMO_TEXT, EXAMPLE["idea"])
                )
                if st.button(
                    "핵심 구성 확인하기 →", type="primary", use_container_width=True
                ):
                    if len(raw.strip()) < 10:
                        st.error("아이디어 내용을 10자 이상 입력해 주세요.")
                    else:
                        prepare_input()
                        s.stage = 2
                        st.rerun()
            st.caption(
                "AI 특징 추출은 미연결입니다. 다음 단계에서 직접 구성을 작성·확인합니다."
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
    elif s.stage == 2:
        st.title("조사할 내용을 확인해 주세요")
        st.caption(
            "핵심 구성이 두 조사의 공통 기준이 됩니다. 직접 수정한 후 시작하세요."
        )
        editor, original = st.columns([1.7, 1], gap="large")
        with editor:
            st.subheader("핵심 구성")
            st.info(
                "예시는 미리 작성된 구성입니다. AI 추출 결과가 아닙니다."
                if s.raw == DEMO_TEXT
                else "특징 추출 미연결 · 핵심 구성을 직접 작성해 주세요."
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
                "＋ 질문 추가", disabled=len(s.questions) >= 5, on_click=add_question
            )
            if st.button(
                f"{len(s.parts)}개 구성으로 조사 시작하기 →",
                type="primary",
                use_container_width=True,
            ):
                parts = [
                    s.get(f"part_{s.version}_{i}", p).strip()
                    for i, p in enumerate(s.parts)
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
                    s.selected = [source["id"] for source in candidates(s.raw)]
                    s.stage = 3
                    st.rerun()
        with original:
            with st.container(border=True):
                st.subheader("입력한 아이디어")
                st.write(s.research_title)
                st.text(s.raw)
            st.warning(
                "구성은 검색 기준입니다. 시장 수요나 특허성을 확인한 결과가 아닙니다."
            )
        st.button("← 입력 수정", on_click=navigate, args=(1,))
    elif s.stage == 3:
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
            st.subheader("아이디어의 구성")
            for i, part in enumerate(s.parts, 1):
                with st.container(border=True):
                    st.caption(f"구성 {i}")
                    st.write(part)
            st.button("구성 수정", on_click=navigate, args=(2,))
        with middle:
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
                "2단계에서 확정한 질문·조건으로 자동 결과를 구성했습니다. 현재는 사전 작성된 예시 규칙의 시연이며 실제 AI 분석이 아닙니다. 수정한 입력은 분석 미연결로 판단 보류합니다."
            )
            for q in s.questions:
                saved = effective_links().get(q["id"], {})
                with st.expander(f"{q['id']} · {q['question']}", expanded=True):
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
                                    i
                                    for i in saved.get("component_ids", [])
                                    if i in labels
                                ],
                                format_func=lambda i: labels[i],
                            )
                            market_ids = [
                                r["id"] for r in chosen if r["kind"] != "특허"
                            ]
                            patent_ids = [
                                r["id"] for r in chosen if r["kind"] == "특허"
                            ]
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
                                index=RELATIONS.index(
                                    saved.get("relation", RELATIONS[0])
                                ),
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
                            st.caption(f"{row['location']} · {row['limit']}")
    elif s.stage == 4 and s.report_snapshot:
        snap = s.report_snapshot
        chosen = snap["sources"]
        left, main = st.columns([1, 3], gap="large")
        with left:
            st.subheader("선택한 문헌")
            for row in chosen:
                with st.container(border=True):
                    st.caption(row["kind"])
                    st.write(f"[{row['id']}] {row['title']}")
            st.button("← 문헌 선정으로", on_click=navigate, args=(3,))
            st.caption("선택을 바꾸면 보고서를 다시 생성합니다.")
        with main:
            st.title("시장·특허 종합 보고서")
            st.warning("시연용 초안 · 실제 분석·사업성 판단은 하지 않습니다.")
            st.subheader("아이디어 요약")
            st.write(snap["title"] or "이름 없는 아이디어")
            st.text(snap["raw"])
            st.markdown("**확정한 핵심 구성**")
            for i, part in enumerate(snap["parts"], 1):
                st.write(f"{i}. {part}")
            st.divider()
            for heading, kinds in [
                ("특허·기술 검토", {"특허"}),
                ("시장·기업 검토", {"시장", "기업"}),
            ]:
                st.subheader(heading)
                rows = [r for r in chosen if r["kind"] in kinds]
                if not rows:
                    st.info("선택 근거 없음 · 해당 영역 판단 보류")
                for row in rows:
                    st.markdown(f"**[{row['id']}] {row['title']}**")
                    st.write(row["quote"])
                    st.caption(f"{row['location']} · {row['limit']}")
            st.subheader("질문별 시장·특허 연결표")
            reviews = review_rows(
                snap["raw"],
                snap["parts"],
                snap["ids"],
                snap["questions"],
                snap["links"],
            )
            st.dataframe(
                [
                    {
                        "검토 질문": e["question"],
                        "시장 근거": ", ".join(e["market_ids"]) or "없음",
                        "관련 구성": ", ".join(e["component_ids"]) or "없음",
                        "특허 근거": ", ".join(e["patent_ids"]) or "없음",
                        "판단 상태": e["status"],
                    }
                    for e in reviews
                ],
                hide_index=True,
                use_container_width=True,
            )
            for e in reviews:
                with st.expander(e["question"], expanded=True):
                    st.caption(e["status"])
                    st.write(f"연결 유형: {e['relation']}")
                    st.write(f"연결 이유: {e['reason'] or '미작성'}")
                    st.caption(f"판단 출처: {ORIGIN_LABELS.get(e['origin'], '미확인')}")
                    for criterion in e["assessment"]:
                        st.write(
                            f"{criterion['criterion']} · {criterion['result']} — {criterion['reason']}"
                        )
                    st.write(f"도입 조건: {e['condition'] or '미입력'}")
                    st.write(f"조건 차이·한계: {e['conditions'] or '미확인'}")
                    st.write(
                        f"반대·충돌: {e['counter_reason'] or '반대 근거를 조사하지 않음'}"
                    )
                    st.write(
                        f"다음 검증: {e['next_check'] or '양쪽 근거와 적용 조건 확인'}"
                    )
                    for row in chosen:
                        if (
                            row["id"]
                            in e["market_ids"] + e["patent_ids"] + e["counter_ids"]
                        ):
                            st.markdown(f"**[{row['id']}] {row['kind']} 원문**")
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
                            st.caption(
                                f"{row['location']} · 대상: {row['entity']} · 시점: {row['period']} · {row['limit']}"
                            )
            st.caption(
                "관계의 종류와 확인 수준은 별개입니다. 기술 관련성만으로 시장 수요·성능·실제 제품 적용·특허성을 확인할 수 없습니다."
            )
            with st.expander("다음 검증 · 구현 비용"):
                st.write(
                    "고객 구매 조건, 특허 청구항, 설치·장비·운영 견적을 추가 확인하세요."
                )
                st.caption(
                    "가격 수집·사업비 계산은 빠른 조사 흐름에 연결되지 않았습니다."
                )
            s.memo = s.saved_memo
            st.text_area("검토 메모", key="memo", on_change=save_memo)
            st.download_button(
                "보고서 다운로드 (.md)",
                report(
                    snap["raw"],
                    snap["title"],
                    snap["parts"],
                    snap["ids"],
                    s.memo,
                    snap["questions"],
                    snap["links"],
                ),
                file_name="idealens-research.md",
                mime="text/markdown",
            )
    st.caption(
        "입력은 현재 세션에서만 유지됩니다. 실제 특허·시장·가격 API는 미연결입니다."
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
