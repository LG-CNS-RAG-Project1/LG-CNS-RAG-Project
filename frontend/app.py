"""스마트팩토리 기업 비교와 인용 근거를 함께 살펴보는 시연 화면."""

import sys
from datetime import date
from html import escape
from pathlib import Path

import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frontend.demo import (
    SECTORS,
    build_demo,
    default_request,
    report_markdown,
    validate_request,
)

st.set_page_config(page_title="스마트팩토리 기업분석", page_icon="◈", layout="wide")
st.html(Path(__file__).with_name("styles.css").read_text(encoding="utf-8"))


def html(value):
    """사용자 입력과 근거를 HTML 텍스트로 안전하게 표시한다."""
    return escape(str(value), quote=True)


def load_example():
    for key in list(st.session_state):
        if key.startswith("next_step_"):
            del st.session_state[key]
    request = default_request()
    st.session_state.update(
        company_a=request["companies"][0],
        company_b=request["companies"][1],
        sector=request["sector"],
        role=request["role"],
        start_date=date.fromisoformat(request["start_date"]),
        end_date=date.fromisoformat(request["end_date"]),
        question=request["question"],
        scenario="기본 비교",
        result=build_demo(request),
        selected_citation="P-A",
        evidence_choice="P-A",
        form_errors=[],
    )


def submit_request():
    request = {
        "companies": [
            st.session_state.company_a.strip(),
            st.session_state.company_b.strip(),
        ],
        "sector": st.session_state.sector,
        "role": st.session_state.role,
        "start_date": st.session_state.start_date.isoformat(),
        "end_date": st.session_state.end_date.isoformat(),
        "question": st.session_state.question.strip(),
    }
    errors = validate_request(request)
    st.session_state.form_errors = errors
    if not errors:
        st.session_state.result = build_demo(request, st.session_state.scenario)
        st.session_state.selected_citation = "P-A"
        st.session_state.evidence_choice = "P-A"
        for key in list(st.session_state):
            if key.startswith("next_step_"):
                del st.session_state[key]


def select_evidence(citation_id):
    st.session_state.selected_citation = citation_id
    st.session_state.evidence_choice = citation_id


def sync_evidence():
    st.session_state.selected_citation = st.session_state.evidence_choice


if "result" not in st.session_state:
    load_example()

with st.sidebar:
    st.html(
        '<div class="sf-brand"><span class="sf-symbol">◈</span><div>스마트팩토리<span>기업분석 워크스페이스</span></div></div>'
    )
    st.html('<div class="sf-sidebar-label">ANALYSIS SCOPE<span>분석 범위</span></div>')
    with st.form("company_scope", border=False):
        st.text_input("비교 기업 A", key="company_a", max_chars=80)
        st.text_input("비교 기업 B", key="company_b", max_chars=80)
        st.selectbox("기술 분야", SECTORS, key="sector")
        st.selectbox(
            "기업 역할", ["솔루션 공급기업", "도입 제조기업", "복합 역할"], key="role"
        )
        st.date_input("자료 시작일", key="start_date", format="YYYY.MM.DD")
        st.date_input("분석 기준일", key="end_date", format="YYYY.MM.DD")
        st.text_area("비교 질문", key="question", height=104, max_chars=1500)
        with st.expander("시연 상태 설정"):
            st.selectbox(
                "화면 상태",
                ["기본 비교", "일부 자료 없음", "검색 결과 없음", "수집 오류"],
                key="scenario",
            )
            st.caption("가상 A·B사 기본 예시의 자료 상태를 바꿔봅니다.")
        st.form_submit_button(
            "비교 화면 보기", type="primary", on_click=submit_request, width="stretch"
        )
    for error in st.session_state.form_errors:
        st.error(error)
    st.button("예시 다시 불러오기", on_click=load_example, width="stretch")
    st.caption("화면 시연 · 입력은 외부로 전송되지 않습니다.")

result = st.session_state.result
request = result["request"]
status = result["status"]
st.html(
    '<div class="sf-topline"><span>RESEARCH WORKSPACE</span><span class="sf-demo-tag">시연 모드 · 실제 분석 미연결</span></div>'
    '<div class="sf-heading"><span class="sf-eyebrow">사업 · 시장 · 기술</span><h1>기업의 차이를, 근거와 함께.</h1>'
    "<p>같은 질문으로 비교하고, 원문에서 판단의 실마리를 확인하세요.</p></div>"
)
st.html(
    '<div class="sf-scope"><span>표시 중인 범위</span>'
    f'<strong>{html(request["sector"])}</strong><span>{html(request["role"])}</span>'
    f'<span>{html(request["start_date"])} — {html(request["end_date"])}</span></div>'
)
st.caption("왼쪽 조건을 바꾼 뒤 ‘비교 화면 보기’를 누르면 표시 범위에 반영됩니다.")

if status in {"demo", "partial"}:
    st.html(
        '<div class="sf-notice">가상 기업·문헌으로 만든 디자인 예시입니다. 실제 기업의 사업·특허·시장 분석 결과가 아닙니다.</div>'
    )
else:
    messages = {
        "unconnected": (
            "분석할 범위가 준비되었습니다",
            "실제 검색 기능이 연결되면 이 영역에 기업 비교와 근거가 표시됩니다. 입력한 기업에 가상 분석을 적용하지 않았습니다.",
        ),
        "no_results": (
            "조건에 맞는 자료를 찾지 못했습니다",
            "검색 결과 없음 상태의 시연입니다. 분야나 기간을 넓혀 다시 확인하는 흐름을 보여줍니다.",
        ),
        "error": (
            "자료를 불러오지 못했습니다",
            "수집 오류 상태의 시연입니다. 자료가 없다는 뜻과 구분해 다시 시도할 수 있습니다.",
        ),
    }
    title, description = messages.get(status, messages["unconnected"])
    st.html(
        '<div class="sf-empty"><span class="sf-eyebrow">분석 상태</span>'
        f'<h2>{html(title)}</h2><p>{html(description)}</p><div class="sf-question">{html(request["question"])}</div></div>'
    )
    st.download_button(
        "분석 범위 내려받기",
        report_markdown(result),
        file_name="smart-factory-analysis-scope.md",
        mime="text/markdown",
    )
    st.stop()

if status == "partial":
    st.warning("시장 자료 미확보 · 확보된 사업·특허 예시만 비교합니다.")

with st.container(key="analysis_columns"):
    main, sources = st.columns([2.15, 1], gap="medium")
with main:
    comparison, executive, research = st.tabs(["기업 비교", "경영진 요약", "R&D 상세"])
    with comparison:
        st.html(
            '<div class="sf-section-title"><h2>한눈에 보는 기업 비교</h2><span>가상 사례</span></div>'
            f'<div class="sf-question">{html(request["question"])}</div>'
        )
        for index, column in enumerate(st.columns(2, gap="small")):
            with column:
                letter = "A" if index == 0 else "B"
                st.html(
                    '<div class="sf-company">'
                    f'<span class="sf-avatar sf-avatar-{letter}">{letter}</span>'
                    f'<div><h3>{html(request["companies"][index])}</h3>'
                    "<p>설비 관리 · 솔루션 공급기업</p></div></div>"
                )
        for row in result["rows"]:
            with st.container(border=True, key=f"comparison_{row['label']}"):
                st.html(f'<div class="sf-row-label">{html(row["label"])}</div>')
                for side, cell in zip(["a", "b"], st.columns(2, gap="medium")):
                    with cell:
                        st.html(f'<div class="sf-cell">{html(row[side])}</div>')
                        for cid in row["citations"]:
                            if cid.endswith(f"-{side.upper()}"):
                                st.button(
                                    f"근거 {cid} ↗",
                                    key=f"cite_{row['label']}_{cid}",
                                    on_click=select_evidence,
                                    args=(cid,),
                                    help="오른쪽 패널에서 해당 원문 예시를 확인합니다.",
                                )
        st.html(
            '<div class="sf-inference"><span>연결 가설</span>사업의 초점과 특허의 접근 방식은 함께 검토할 수 있습니다. 특정 제품에 적용됐는지는 별도 근거가 필요합니다.</div>'
        )
    with executive:
        st.subheader("결정 전에 확인할 핵심")
        st.caption("가상 자료를 읽는 순서를 보여주는 요약 예시입니다.")
        for index, finding in enumerate(result["findings"], start=1):
            with st.container(border=True):
                st.markdown(f"**{index:02d} · {finding}**")
        st.markdown("#### 다음 조사")
        for index, unknown in enumerate(result["unknowns"]):
            st.checkbox(unknown, key=f"next_step_{index}")
        st.caption("체크는 이 세션의 검토 메모이며 사실 확인 판정을 바꾸지 않습니다.")
    with research:
        st.subheader("기술의 구성과 적용 조건")
        st.caption("가상 특허 초록에서 확인할 항목을 같은 순서로 비교합니다.")
        st.dataframe(
            [
                {
                    "비교 항목": "입력",
                    "가상 A사": "진동 신호",
                    "가상 B사": "전류·운전 이력",
                },
                {
                    "비교 항목": "처리",
                    "가상 A사": "기준 상태와 차이 비교",
                    "가상 B사": "상태 변화 추이 분석",
                },
                {
                    "비교 항목": "출력",
                    "가상 A사": "설정 범위 이탈 시 알림",
                    "가상 B사": "점검 순서 제안",
                },
                {
                    "비교 항목": "미확인",
                    "가상 A사": "청구항·실측 성능",
                    "가상 B사": "청구항·실측 성능",
                },
            ],
            hide_index=True,
            width="stretch",
        )
        st.button("A사 기술 근거 P-A ↗", on_click=select_evidence, args=("P-A",))
        st.button("B사 기술 근거 P-B ↗", on_click=select_evidence, args=("P-B",))
        st.info(
            "이 예시는 초록의 기술 구성을 비교합니다. 기술력 순위나 제품 적용을 판정하지 않습니다."
        )

with sources:
    with st.container(border=True, key="evidence_panel"):
        st.html(
            '<div class="sf-evidence-heading"><span>TRACE THE SOURCE</span><h2>문장 뒤의 근거</h2><p>비교표의 근거 버튼으로 연결됩니다.</p></div>'
        )
        evidence_by_id = {item["id"]: item for item in result["evidence"]}
        ids = list(evidence_by_id)
        if st.session_state.evidence_choice not in ids:
            st.session_state.evidence_choice = ids[0]
            st.session_state.selected_citation = ids[0]
        chosen = st.selectbox(
            "확인할 근거",
            ids,
            key="evidence_choice",
            on_change=sync_evidence,
            format_func=lambda cid: f"{cid} · {evidence_by_id[cid]['kind']}",
        )
        evidence = evidence_by_id[chosen]
        st.html(
            f'<div class="sf-source-badge">가상 문헌 · {html(evidence["company"])}</div>'
            f'<h3 class="sf-source-title">{html(evidence["title"])}</h3>'
            f'<div class="sf-source-meta">{html(evidence["date"])} · {html(evidence["section"])}</div>'
            f'<blockquote class="sf-quote">{html(evidence["quote"])}</blockquote>'
            '<div class="sf-evidence-limit"><span>이 근거로 확인할 수 없는 것</span>'
            f'<p>{html(evidence["limitation"])}</p></div>'
        )
        st.caption("시연용 원문입니다. 실제 문헌 링크는 API 연결 후 제공됩니다.")
    st.html(
        '<div class="sf-source-types"><span>연결할 자료</span><div>기업 공시 <b>DART</b></div><div>특허 원문 <b>KIPRIS</b></div><div>시장·산업 자료 <b>공식 보고서</b></div></div>'
    )
    st.download_button(
        "비교 보고서 내려받기 ↓",
        report_markdown(result),
        file_name="smart-factory-demo-report.md",
        mime="text/markdown",
        width="stretch",
    )
    st.caption("범위 · 비교표 · 근거 · 미확인 사항 포함")
