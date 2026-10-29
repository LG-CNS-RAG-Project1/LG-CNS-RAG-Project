"""최종 판단에서 실제 인용 문장과 원문까지 따라가는 읽기 전용 화면."""

import streamlit as st
from pydantic import BaseModel, Field


class TraceSource(BaseModel):
    ref: str
    title: str
    quote: str
    location: str = ""
    url: str = ""


class TraceFinding(BaseModel):
    title: str
    judgment: str
    implication: str = ""
    kind: str = "미확인"
    refs: list[str] = Field(default_factory=list)


class DecisionTrace(BaseModel):
    findings: list[TraceFinding] = Field(default_factory=list, max_length=30)
    sources: list[TraceSource] = Field(default_factory=list, max_length=1000)


def decision_trace(result):
    """기존 최종 분석의 판단과 인용을 보존하며 새 점수나 요약을 생성하지 않는다."""
    sources = [
        TraceSource(
            ref=f"P:{e.citation_id}",
            title=e.title,
            quote=e.quote,
            location=f"{e.section} · 청구항 {e.claim_number or '미제공'}",
            url=e.source_url or "",
        )
        for e in result.patent.evidence
    ] + [
        TraceSource(
            ref=f"M:{e.citation_id}",
            title=e.title,
            quote=e.quote,
            location=f"{e.publisher} · {e.published_at} · {e.evidence_nature}",
            url=e.url or "",
        )
        for e in result.market.evidence
    ]
    review = result.executive_review
    kinds = {
        "fact": "사실",
        "interpretation": "해석",
        "hypothesis": "가설",
        "unknown": "미확인",
    }
    findings = [
        TraceFinding(
            title=f.label,
            judgment=f.judgment,
            implication=f.business_implication,
            kind=kinds[f.kind],
            refs=f.evidence_ids,
        )
        for f in (review.integrated_findings if review else [])
    ]
    return DecisionTrace(findings=findings, sources=sources).model_dump()


def render_decision_trace(raw):
    """판단 선택 → 인용 선택 → 원문 확인 순서로 보여준다."""
    data = DecisionTrace.model_validate(raw)
    st.subheader("이 결론은 어떤 근거에서 나왔나요?")
    st.caption(
        "특허와 시장의 기존 분석을 연결한 결과입니다. 자료 개수나 검색 순위를 사업성 점수로 합산하지 않습니다."
    )
    with st.expander("판단할 때 확인하는 기준"):
        st.markdown(
            "- **기술·권리:** 아이디어 구성과 청구항의 대응·차이, 확보한 인용과 검색 한계\n"
            "- **고객·시장:** 산업·기업 신호와 실제 고객의 구매·지불 검증을 구분\n"
            "- **도입 조건:** 현재 대안, 설치·운영 장벽과 고객·수익모델의 미확인 항목\n"
            "- **다음 결정:** 핵심 근거가 비면 추가 확인, 겹침 우려가 있으면 차별 구성 검토, 고객 검증이 있어도 제한 범위의 파일럿 검토"
        )
    if not data.findings:
        st.info(
            "연결 판단이 제공되지 않았습니다. 원문을 확인하거나 분석을 완료해 주세요."
        )
        return
    index = st.selectbox(
        "확인할 판단",
        range(len(data.findings)),
        format_func=lambda i: data.findings[i].title,
        key="trace_finding",
    )
    finding = data.findings[index]
    st.caption(finding.kind)
    st.write(finding.judgment)
    st.info(finding.implication or "아이디어에 대한 추가 설명이 제공되지 않았습니다.")
    sources = {s.ref: s for s in data.sources}
    if not finding.refs:
        st.warning(
            "이 판단에 연결된 인용이 없습니다. 근거가 확인된 사실로 받아들이지 마세요."
        )
        return
    ref = st.selectbox(
        "연결된 근거",
        finding.refs,
        format_func=lambda r: f"{r} · {sources[r].title if r in sources else '원문 미제공'}",
        key=f"trace_source_{index}",
    )
    source = sources.get(ref)
    if source is None:
        st.warning(
            "이 인용의 원문이 현재 결과에 없습니다. 원문 확인 전 판단을 보류하세요."
        )
        return
    with st.container(border=True):
        st.markdown(f"**{source.title}**")
        st.caption(source.location)
        st.text(source.quote)
        if source.url.startswith(("https://", "http://")):
            st.link_button("출처 원문 열기 ↗", source.url)
