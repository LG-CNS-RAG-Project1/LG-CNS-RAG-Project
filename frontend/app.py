"""큰 입력란 → 구성 확인 → 특허·시장 자료 선정 → 보고서의 단계형 UI."""

import sys
from pathlib import Path
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from frontend.quick import (
    DEMO_TEXT,
    DEMO_PARTS,
    candidates,
    validate_parts,
    selected_sources,
    report,
)
from frontend.workspace import EXAMPLE

st.set_page_config(page_title="IdeaLens · 빠른 조사", page_icon="▤", layout="wide")
st.html(Path(__file__).with_name("styles.css").read_text(encoding="utf-8"))
for key, value in {
    "stage": 1,
    "raw": "",
    "research_title": "",
    "parts": [],
    "selected": [],
    "recent": [],
    "memo": "",
    "report_snapshot": None,
    "version": 0,
}.items():
    if key not in st.session_state:
        st.session_state[key] = value
s = st.session_state


def navigate(number):
    s.stage = number


def load(text, title=""):
    s.raw_input = text
    s.title_input = title
    s.stage = 1


def edit_part(index, direction):
    values = [s.get(f"part_{s.version}_{i}", p) for i, p in enumerate(s.parts)]
    if direction == 0:
        values.pop(index)
    else:
        target = index + direction
        values[index], values[target] = values[target], values[index]
    s.parts = values
    s.version += 1
    s.selected = []
    s.report_snapshot = None


def add_part():
    s.parts = [s.get(f"part_{s.version}_{i}", p) for i, p in enumerate(s.parts)] + [""]
    s.version += 1
    s.selected = []
    s.report_snapshot = None


def select(source_id):
    s.selected = (
        [i for i in s.selected if i != source_id]
        if source_id in s.selected
        else s.selected + [source_id]
    )
    s.report_snapshot = None


st.html(
    '<div class="appbar"><strong>▤ IdeaLens</strong><span>시장·특허 조사</span><small>로컬 시연 · 외부 분석 미연결</small></div>'
)
steps = ["아이디어 입력", "핵심 구성 확인", "문헌 선정·근거 검토", "종합 보고서"]
st.html(
    '<div class="stepper">'
    + "".join(
        f'<div class="step {"active" if s.stage==i else "done" if s.stage>i else ""}"><b>{i}</b><span>{label}</span></div>'
        for i, label in enumerate(steps, 1)
    )
    + "</div>"
)

if s.stage == 1:
    st.title("어떤 아이디어를 조사할까요?")
    st.caption("내용을 입력하고 구성을 확인한 뒤, 특허와 시장 근거를 함께 살펴보세요.")
    main, recent = st.columns([2.4, 1], gap="large")
    with main:
        with st.container(border=True):
            st.text_input("아이디어 명칭 (선택)", max_chars=100, key="title_input")
            raw = st.text_area(
                "아이디어 내용",
                height=300,
                max_chars=20000,
                key="raw_input",
                placeholder="해결하려는 문제, 핵심 기술과 동작 방식, 예상 효과를 자유롭게 적어 주세요.",
            )
            st.caption(f"{len(raw):,} / 20,000자 · 최소 10자")
            a, b = st.columns(2)
            a.button(
                "입력 템플릿",
                on_click=load,
                args=("해결할 문제:\n\n핵심 아이디어와 동작 방식:\n\n예상 효과:",),
            )
            b.button("예시 불러오기", on_click=load, args=(DEMO_TEXT, EXAMPLE["idea"]))
            if st.button(
                "핵심 구성 확인하기 →", type="primary", use_container_width=True
            ):
                if len(raw.strip()) < 10:
                    st.error("아이디어 내용을 10자 이상 입력해 주세요.")
                else:
                    s.raw = raw.strip()
                    s.research_title = s.title_input.strip()
                    s.parts = list(DEMO_PARTS) if s.raw == DEMO_TEXT else [""]
                    s.version += 1
                    s.selected = []
                    s.memo = ""
                    s.report_snapshot = None
                    item = {"text": s.raw, "title": s.research_title}
                    s.recent = [item] + [x for x in s.recent if x != item][:4]
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
    st.caption("핵심 구성이 두 조사의 공통 기준이 됩니다. 직접 수정한 후 시작하세요.")
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
                    f"구성 {i+1}", value=part, key=f"part_{s.version}_{i}", height=85
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
        if st.button(
            f"{len(s.parts)}개 구성으로 조사 시작하기 →",
            type="primary",
            use_container_width=True,
        ):
            parts = [
                s.get(f"part_{s.version}_{i}", p).strip() for i, p in enumerate(s.parts)
            ]
            error = validate_parts(parts)
            if error:
                st.error(error)
            else:
                s.parts = parts
                s.selected = []
                s.report_snapshot = None
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
            s.report_snapshot = {
                "raw": s.raw,
                "title": s.research_title,
                "parts": list(s.parts),
                "ids": list(s.selected),
            }
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
        patent, market = st.tabs(["특허·기술 조사", "시장·기업 조사"])
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
                        st.caption(f"{row['id']} · {row['kind']} · 시연용 가상 자료")
                        st.markdown(f"#### {row['title']}")
                        st.write(row["quote"])
                        with st.expander("문헌 상세·원문 근거"):
                            st.caption(row["location"])
                            st.write(row["limit"])
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
            "최소 2건 선택 시 생성 가능. 특허와 시장 양쪽을 선택하면 함께 검토할 수 있어요."
        )
        if chosen and (count == 0 or count == len(chosen)):
            st.warning("한 영역만 선택됐어요. 다른 영역은 미확인으로 표시합니다.")
        st.markdown(
            "**연결할 질문**\n\n구매·도입 조건과 기술 구성이 맞는가? 어떤 원문과 추가 검증이 필요한가?"
        )
elif s.stage == 4 and s.report_snapshot:
    snap = s.report_snapshot
    chosen = selected_sources(snap["raw"], snap["ids"])
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
        st.subheader("시장 요구와 기술을 연결해서 보기")
        st.info(
            "검증할 가설: 구매·설치 조건과 기술 구성이 양립하는지 선택한 원문을 대조합니다."
        )
        st.caption("자료 선택만으로 수요·기술 우위·제품 적용을 확인한 것은 아닙니다.")
        with st.expander("다음 검증 · 구현 비용"):
            st.write(
                "고객 구매 조건, 특허 청구항, 설치·장비·운영 견적을 추가 확인하세요."
            )
            st.caption("가격 수집·사업비 계산은 빠른 조사 흐름에 연결되지 않았습니다.")
        st.text_area("검토 메모", key="memo")
        st.download_button(
            "보고서 다운로드 (.md)",
            report(snap["raw"], snap["title"], snap["parts"], snap["ids"], s.memo),
            file_name="idealens-research.md",
            mime="text/markdown",
        )
st.caption("입력은 현재 세션에서만 유지됩니다. 실제 특허·시장·가격 API는 미연결입니다.")
