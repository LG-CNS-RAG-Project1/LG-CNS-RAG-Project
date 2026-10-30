"""교체 가능한 예시 이미지와 검증 자료를 보여주는 읽기 전용 소개 화면."""

import json
from pathlib import Path

import streamlit as st

ASSETS = Path(__file__).with_name("assets") / "showcase"


def load_showcase():
    return json.loads((ASSETS / "manifest.json").read_text(encoding="utf-8"))


def asset_file(relative):
    if not relative:
        return None
    path = (ASSETS / relative).resolve()
    if not path.is_relative_to(ASSETS.resolve()):
        return None
    return path if path.is_file() else None


def render_showcase():
    data = load_showcase()
    st.caption("IDEALENS · 결과를 읽는 방법")
    st.title("어떤 결과를 보고, 무엇을 확인하나요?")
    st.write(
        "화면과 함께 결과를 읽는 순서를 살펴보세요. 분석 방식의 설명은 ‘서비스 소개’에서 볼 수 있습니다."
    )
    examples = data["examples"]
    chosen = st.selectbox(
        "살펴볼 화면",
        range(len(examples)),
        format_func=lambda i: examples[i]["title"],
        key="showcase_example",
    )
    item = examples[chosen]
    with st.container(border=True):
        st.subheader(item["title"])
        if item["kind"] == "layout_sample":
            st.caption(
                "화면 구성 예시입니다. 실제 조사 결과·대표도면·성능 측정 화면이 아닙니다."
            )
        else:
            st.caption(
                item.get("context", "제공된 캡처의 시점·분석 조건을 확인하세요.")
            )
        image = asset_file(item.get("image"))
        if image:
            st.image(str(image), caption=item["caption"], width="stretch")
        else:
            st.caption("이 화면의 캡처는 준비 중입니다.")
    left, right = st.columns(2)
    with left:
        st.subheader("여기서 볼 것")
        for point in item["look_for"]:
            st.write("• " + point)
    with right:
        st.subheader("아이디어 검토에 쓰는 법")
        st.write(item["meaning"])
        st.caption(item["limit"])
    st.divider()
    st.subheader("LLM·RAG·IdeaLens 검증 자료")
    st.write(
        "같은 질문을 어떤 자료와 검증 절차로 답했는지 비교하는 자리입니다. 팀원의 실험 결과가 확정되면 실험 조건과 캡처를 함께 제공합니다."
    )
    st.table(
        {
            "비교 대상": ["LLM 단독", "단순 RAG", "IdeaLens"],
            "함께 확인할 조건": [
                "검색 근거를 제공했는지, 모델·프롬프트",
                "같은 질문과 자료 범위, 검색·생성 설정",
                "검색 외에 적용한 관련성·인용 검증과 미확인 처리",
            ],
        }
    )
    for experiment in data["experiments"]:
        with st.expander(experiment["title"]):
            st.caption(experiment["context"])
            image = asset_file(experiment.get("image"))
            if image:
                st.image(str(image), caption=experiment["caption"], width="stretch")
            else:
                st.caption(
                    "확정된 비교 캡처 준비 중 · 측정 수치는 아직 표시하지 않습니다."
                )
            st.write(experiment["reading"])
    st.caption(
        "비교에는 동일 질문·자료 범위·모델·실행 시점·평가 방법·사람 검토 여부가 필요합니다. 화면 구성 예시는 성능 개선의 증거가 아닙니다."
    )
