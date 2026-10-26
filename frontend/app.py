"""시장·특허·구현 비용을 함께 검토하는 로컬 아이디어 작업실."""

import sys
from copy import deepcopy
from html import escape
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frontend.workspace import (
    EXAMPLE,
    FIELDS,
    MARKET,
    PATENTS,
    SOURCES,
    TASKS,
    cost_summary,
    empty_costs,
    example_costs,
    export_report,
    is_example,
)

st.set_page_config(page_title="아이디어 검토실", page_icon="▤", layout="wide")
st.html(Path(__file__).with_name("styles.css").read_text(encoding="utf-8"))
PAGES = ["시작하기", "분석 브리프", "조사 노트", "구현 비용", "종합 보고서"]


def navigate(page):
    st.session_state.page = page


def select_source(source_id):
    st.session_state.source = source_id


def source_buttons(ids):
    columns = st.columns(len(ids))
    for column, source_id in zip(columns, ids):
        column.button(
            f"{source_id} 근거 읽기", on_click=select_source, args=(source_id,)
        )


def reset_project(brief, sample=False):
    st.session_state.draft = deepcopy(brief)
    st.session_state.confirmed = None
    st.session_state.costs = example_costs() if sample else empty_costs()
    st.session_state.note = ""
    st.session_state.done = []
    st.session_state.page = "분석 브리프"
    st.session_state.editor_version += 1
    for key in list(st.session_state):
        if key.startswith(("field_", "task_")) or key in ("note_input", "source"):
            del st.session_state[key]


def title(kicker, heading, subtitle):
    st.html(
        f'<div class="eyebrow">{escape(kicker)}</div><h1>{escape(heading)}</h1><p class="lede">{escape(subtitle)}</p>'
    )


def table(headers, rows):
    head = "".join(f"<th>{escape(str(h))}</th>" for h in headers)
    body = "".join(
        "<tr>" + "".join(f"<td>{escape(str(c))}</td>" for c in row) + "</tr>"
        for row in rows
    )
    st.html(
        f'<div class="table-scroll"><table class="research-table"><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table></div>'
    )


for key, value in {
    "page": "시작하기",
    "draft": {"idea": "", **{key: "" for key in FIELDS}},
    "confirmed": None,
    "costs": empty_costs(),
    "editor_version": 0,
    "note": "",
    "done": [],
}.items():
    if key not in st.session_state:
        st.session_state[key] = deepcopy(value)

with st.sidebar:
    st.html(
        '<div class="brand"><span class="brand-symbol">▤</span> 아이디어 검토실</div><div class="brand-sub">RESEARCH WORKSPACE</div>'
    )
    st.caption("내 작업 공간")
    st.session_state.nav_page = st.session_state.page
    st.radio(
        "작업 단계",
        PAGES,
        key="nav_page",
        label_visibility="collapsed",
        on_change=lambda: navigate(st.session_state.nav_page),
    )
    st.divider()
    st.caption("검토 중인 아이디어")
    st.write(st.session_state.draft["idea"] or "아직 등록된 아이디어가 없습니다.")
    st.button(
        "예시 불러오기",
        on_click=reset_project,
        args=(EXAMPLE, True),
        use_container_width=True,
    )
    st.caption(
        "로컬 시연 · 외부 분석 API 미연결\n\n입력은 현재 세션에 유지됩니다. 보관하려면 보고서를 내려받으세요."
    )

page = st.session_state.page
st.html(
    f'<div class="topline"><span>WORKSPACE / {escape(page)}</span><span>시장 · 기술 · 사업 검토</span></div>'
)

if page == "시작하기":
    left, right = st.columns([1.35, 1], gap="large")
    with left:
        title(
            "FROM IDEA TO EVIDENCE",
            "만들기 전에,\n함께 살펴볼 것들.",
            "아이디어의 시장 수요와 관련 특허, 구현 비용을 한 흐름으로 검토합니다.",
        )
        with st.form("start"):
            idea = st.text_area(
                "어떤 아이디어를 검토하시나요?",
                key="idea_input",
                height=135,
                placeholder="예: 소규모 제조라인에 붙여 쓰는 카메라 기반 불량 검사 장치",
            )
            submitted = st.form_submit_button(
                "아이디어 정리하기 →", type="primary", use_container_width=True
            )
        if submitted:
            if not idea.strip():
                st.error("검토할 아이디어를 한 줄 이상 입력해 주세요.")
            else:
                reset_project({"idea": idea.strip(), **{key: "" for key in FIELDS}})
                st.rerun()
        st.caption(
            "현재는 직접 작성하는 브리프입니다. AI 구조화와 실제 자료 검색은 연결 전입니다."
        )
    with right:
        st.html(
            """<div class="intro-note"><div class="eyebrow">하나의 아이디어, 세 가지 질문</div><div class="question"><span>01</span><div><h3>누가, 왜 필요로 할까?</h3><p>고객의 문제 · 경쟁 기업 · 구매 조건</p></div></div><div class="question"><span>02</span><div><h3>기술적으로 무엇이 다를까?</h3><p>관련 특허 · 구성요소 비교 · 원문 근거</p></div></div><div class="question"><span>03</span><div><h3>구현하려면 무엇이 필요할까?</h3><p>장비와 부품 · 비용 가정 · 남은 검증</p></div></div><div class="note-footer">조사 결과를 묶어, 다음에 확인할 일을 정합니다.</div></div>"""
        )
    st.divider()
    st.html(
        '<div class="process"><span>01 아이디어 정리</span><b>→</b><span>02 시장·특허 조사</span><b>→</b><span>03 비용 검토</span><b>→</b><span>04 종합 보고서</span></div>'
    )
    st.caption("신제품·사업 아이디어를 검토하는 기획자와 개발팀을 위한 작업 공간")

elif page == "분석 브리프":
    title(
        "01 / BRIEF",
        "무엇을 조사할지 먼저 맞춥니다.",
        "문제와 기술, 고객을 구체화하면 시장 자료와 특허를 같은 기준으로 비교할 수 있습니다.",
    )
    if is_example(st.session_state.draft):
        st.caption(
            "예시 브리프 · 실제 고객 조사나 AI 분석 결과가 아닙니다. 수정하면 별도의 사용자 브리프로 전환됩니다."
        )
    with st.form("brief"):
        idea = st.text_input(
            "아이디어 이름", value=st.session_state.draft["idea"], key="field_idea"
        )
        values = {}
        cols = st.columns(2, gap="large")
        for index, (key, label) in enumerate(FIELDS.items()):
            with cols[index % 2]:
                values[key] = st.text_area(
                    label,
                    value=st.session_state.draft[key],
                    key=f"field_{key}",
                    height=100,
                )
        st.caption(
            "문제·기술·사용자는 필수입니다. 차별점과 수익 방식은 모르면 비워두세요."
        )
        st.caption(
            "범위를 바꾸어 확정하면 이전 비용·검토 메모를 초기화합니다. 필요한 내용은 먼저 보고서를 내려받으세요."
        )
        submitted = st.form_submit_button(
            "브리프 확정하고 조사 노트 열기 →", type="primary"
        )
    if submitted:
        brief = {
            "idea": idea.strip(),
            **{key: value.strip() for key, value in values.items()},
        }
        st.session_state.draft = brief
        if not all(
            brief[key] for key in ("idea", "problem", "technology", "customers")
        ):
            st.session_state.confirmed = None
            st.error("아이디어 이름, 해결할 문제, 구현할 기술, 사용자를 입력해 주세요.")
        else:
            if not is_example(brief) and st.session_state.confirmed != brief:
                st.session_state.costs = empty_costs()
                st.session_state.editor_version += 1
                st.session_state.done = []
                st.session_state.note = ""
                for key in list(st.session_state):
                    if key.startswith("task_") or key == "note_input":
                        del st.session_state[key]
            st.session_state.confirmed = deepcopy(brief)
            navigate("조사 노트")
            st.rerun()

else:
    brief = st.session_state.confirmed
    if brief is None:
        title(
            "검토 준비",
            "먼저 분석 브리프를 확정해 주세요.",
            "조사와 비용 검토에 사용할 아이디어의 범위를 정합니다.",
        )
        st.button(
            "브리프 작성하기", on_click=navigate, args=("분석 브리프",), type="primary"
        )
        st.stop()
    sample = is_example(brief)
    st.caption(
        "가상 예시 · 문헌과 가격은 시연용입니다. 실제 검색은 실행되지 않았습니다."
        if sample
        else "사용자 브리프 · 자료 수집 전 / 외부 검색·분석 API 미연결"
    )
    if page == "조사 노트":
        title(
            "02 / RESEARCH",
            brief["idea"],
            "시장에서는 구매 조건을, 특허에서는 기술 구성을 확인합니다.",
        )
        main, evidence = st.columns([2.05, 1], gap="large")
        with main:
            tabs = st.tabs(["시장·기업", "특허·기술", "연결해서 보기"])
            with tabs[0]:
                st.subheader("누구의 어떤 문제를 해결하나요?")
                if sample:
                    table(
                        ["조사 관점", "내용 · 근거", "다음 확인"],
                        [(a, f"{b}\n[{c}] {d}", e) for a, b, c, d, e in MARKET],
                    )
                    source_buttons(["M1", "M2"])
                else:
                    st.info("아직 수집된 시장·기업 자료가 없습니다.")
                    table(
                        ["조사 관점", "확보할 자료"],
                        [
                            ("수요", "고객 인터뷰 · 공공 통계"),
                            ("경쟁 기업", "국내·해외 기업 공시 · 제품 자료"),
                            ("가격·도입", "견적 · 구매 절차 · 설치 조건"),
                        ],
                    )
                st.caption(
                    "사업보고서의 제품·매출 정보와 고객의 구매 의사는 별개로 검증합니다."
                )
            with tabs[1]:
                st.subheader("기술을 구성요소별로 비교합니다.")
                if sample:
                    table(["기술 구성", "대응 상태", "근거", "남은 확인"], PATENTS)
                    source_buttons(["P1", "P2"])
                else:
                    st.info(
                        "아직 수집된 특허 원문이 없습니다. 브리프의 기술 설명부터 검색 대상으로 삼습니다."
                    )
                    st.write(brief["technology"])
                with st.expander("검색 범위와 방식"):
                    st.write(
                        "현재 검토한 실제 문헌: 0건. 예시에서는 가상 문헌 2건의 요약만 표시합니다."
                        if sample
                        else "현재 검토한 실제 문헌: 0건."
                    )
                    st.write(
                        "연결 예정: 키워드 검색 + 의미 검색 → 중복 제거·재정렬 → 관련 문단·청구항 대조. 국가·기간·분류와 검색식은 실제 검색 연결 시 확정합니다."
                    )
                    st.caption(
                        "검색 결과가 없다는 사실만으로 새로운 기술이라고 판단하지 않습니다."
                    )
            with tabs[2]:
                st.subheader("자료를 모은 다음, 판단할 질문")
                table(
                    ["시장 조건", "기술 검토", "비용·검증"],
                    (
                        [
                            (
                                "설치 중단을 줄여야 한다는 가설",
                                "기존 라인에 추가 설치하는 구조",
                                "장착·연동 견적과 설치 시간 확인",
                            ),
                            (
                                "소량 다품종 검사 수요 가설",
                                "제품 변경 시 모델 조정 방식",
                                "학습 데이터·유지보수 비용 확인",
                            ),
                        ]
                        if sample
                        else [
                            (
                                "고객의 구매 조건 확인",
                                "그 조건을 충족할 기술 구성 확인",
                                "필요한 장비·개발·운영 비용 확인",
                            )
                        ]
                    ),
                )
                st.caption(
                    "연결 관계는 검증할 가설입니다. 특허 보유가 시장 수요나 구현 가능성을 입증하지는 않습니다."
                )
                st.button(
                    "구현 비용 검토하기 →",
                    on_click=navigate,
                    args=("구현 비용",),
                    type="primary",
                )
        with evidence:
            with st.container(border=True):
                st.subheader("근거 읽기")
                if sample:
                    selected = st.selectbox(
                        "확인할 자료",
                        [s["id"] for s in SOURCES],
                        format_func=lambda value: next(
                            f"{s['id']} · {s['title']}"
                            for s in SOURCES
                            if s["id"] == value
                        ),
                        key="source",
                    )
                    source = next(s for s in SOURCES if s["id"] == selected)
                    st.caption(f"{source['kind']} / {source['location']}")
                    st.write(source["quote"])
                    st.divider()
                    st.caption(source["limit"])
                    st.caption("출처: 로컬 시연 자료 / 발행일·원문 링크 없음")
                else:
                    st.write(
                        "자료를 확보하면 인용 문장과 원문 위치가 여기에 표시됩니다."
                    )
                    st.caption("현재 표시할 근거 없음")

    elif page == "구현 비용":
        title(
            "03 / COST WORKSHEET",
            "구현 비용의 빈칸을 찾습니다.",
            "장비와 부품의 수량·가격·납기를 적고, 아직 견적이 없는 항목을 남겨두세요.",
        )
        st.caption(
            "단위: 만원 · 빈 단가는 미확인으로 처리합니다. 실제 가격을 자동 수집하는 기능은 아직 연결 전입니다."
        )
        with st.form("cost_form"):
            rows = st.data_editor(
                st.session_state.costs,
                num_rows="dynamic",
                hide_index=True,
                use_container_width=True,
                key=f"cost_editor_{st.session_state.editor_version}",
                column_config={
                    "수량": st.column_config.NumberColumn(
                        min_value=1, step=1, required=True
                    ),
                    "단가(만원)": st.column_config.NumberColumn(
                        min_value=0, step=0.1, format="%.1f"
                    ),
                    "항목": st.column_config.TextColumn(required=True),
                    "근거 / 가정": st.column_config.TextColumn(width="large"),
                },
            )
            apply = st.form_submit_button("비용 반영하기", type="primary")
        if apply:
            result = cost_summary(rows)
            if result["errors"]:
                st.error("수량은 양의 정수, 단가는 0 이상의 숫자로 입력해 주세요.")
            else:
                st.session_state.costs = deepcopy(rows)
                st.session_state.editor_version += 1
                st.session_state.cost_saved = True
                st.rerun()
        if st.session_state.pop("cost_saved", False):
            st.success("비용표를 보고서에 반영했습니다.")
        result = cost_summary(st.session_state.costs)
        a, b, c = st.columns(3)
        a.metric("입력 금액 소계", f"{result['total']:,.1f} 만원")
        b.metric("금액 미확인", f"{len(result['missing'])} 항목")
        c.metric(
            "납기 미확인",
            f"{sum(not r.get('납기') or r['납기'] == '미확인' for r in st.session_state.costs)} 항목",
        )
        if result["missing"]:
            st.warning("견적 필요: " + ", ".join(result["missing"]))
        st.caption(
            "소계는 총사업비가 아닙니다. 세금·배송·설치·개발·운영비는 표에 입력한 항목만 반영하며, 수익성이나 회수기간은 산출하지 않습니다."
        )
        st.button("종합 보고서로 이동 →", on_click=navigate, args=("종합 보고서",))

    elif page == "종합 보고서":
        title("04 / REVIEW", "다음 판단을 위한 검토 노트", brief["idea"])
        main, side = st.columns([1.8, 1], gap="large")
        with main:
            st.subheader("세 줄 요약")
            if sample:
                st.write(
                    "1. **시장** — 소규모 제조사의 검사 부담을 해결한다는 가설. 구매 의사는 확인 전입니다."
                )
                st.write(
                    "2. **기술** — 영상 검사·조명 제어를 구성별로 비교. 실제 특허 원문과 차별성은 확인 전입니다."
                )
                st.write(
                    "3. **사업** — 장비 소계와 미확인 비용을 나눠 검토. 설치·운영비와 판매 조건이 더 필요합니다."
                )
            else:
                st.write(
                    "1. **시장** — 고객과 문제를 브리프에 정리했습니다. 수요 근거는 수집 전입니다."
                )
                st.write(
                    "2. **기술** — 기술 설명을 확보했습니다. 관련 특허 비교는 수집 전입니다."
                )
                st.write(
                    "3. **사업** — 입력한 비용만 반영합니다. 사업성 판단에는 견적·매출 가정이 더 필요합니다."
                )
            st.divider()
            st.subheader("브리프")
            table(
                ["항목", "작성 내용"],
                [(label, brief[key] or "미입력") for key, label in FIELDS.items()],
            )
            with st.form("review"):
                note = st.text_area(
                    "팀 검토 메모",
                    value=st.session_state.note,
                    key="note_input",
                    height=130,
                    placeholder="동의하는 가정, 반대 의견, 다음에 확인할 내용을 남기세요.",
                )
                done = [
                    task
                    for index, task in enumerate(TASKS)
                    if st.checkbox(
                        task, value=task in st.session_state.done, key=f"task_{index}"
                    )
                ]
                save = st.form_submit_button("메모와 확인 항목 저장")
            if save:
                st.session_state.note, st.session_state.done = note, done
                st.success("현재 세션의 보고서에 반영했습니다.")
        with side:
            with st.container(border=True):
                st.subheader("검토 상태")
                st.write("**추가 조사 필요**")
                st.caption("수요 검증 · 청구항 대조 · 현장 견적 확보 전")
                result = cost_summary(st.session_state.costs)
                st.metric("입력 금액 소계", f"{result['total']:,.1f} 만원")
                st.caption(
                    f"금액 미확인 {len(result['missing'])}개 항목 · 총사업비 아님"
                )
                st.download_button(
                    "검토 보고서 내려받기",
                    data=export_report(
                        brief,
                        st.session_state.costs,
                        st.session_state.note,
                        st.session_state.done,
                    ),
                    file_name="idea-review.md",
                    mime="text/markdown",
                    use_container_width=True,
                    type="primary",
                )
                st.caption(
                    "브리프·조사 예시·근거·비용·저장한 메모를 포함한 Markdown 문서"
                )
