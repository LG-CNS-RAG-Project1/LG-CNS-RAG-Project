"""현재 조사 코드에 근거한 읽기 전용 단계 안내. 분석이나 API를 실행하지 않는다."""

import streamlit as st

GUIDES = {
    "patent": {
        "title": "특허가 내 아이디어의 근거가 되기까지",
        "summary": "비슷한 제목을 찾는 데서 끝내지 않고, 기술 구성과 청구항을 대조합니다.",
        "preparation": "KIPRIS에서 확보한 문헌을 초록·청구항 단위로 나누고 문헌 ID·청구항 번호·상위항 관계를 보존해 Chroma 색인에 준비합니다.",
        "steps": [
            (
                "검색 질문 만들기",
                "확정한 아이디어와 기술 구성",
                "기술 요소별 한국어·영어 검색 질의",
                "아이디어의 핵심 구성을 나누고 관련 표현을 확장합니다. 분야를 정한 경우 해당 분야를 우선 검색합니다.",
                "하나의 표현만 검색해서 놓치는 문헌을 줄이기 위해서입니다.",
                "검색어 계획 · 구조화 입력",
                ["src/services/patent_service.py", "docs/patent_rag.md"],
            ),
            (
                "관련 문헌 찾기",
                "검색 질의와 준비된 특허 색인",
                "중복을 정리한 문헌 후보",
                "의미 기반 Dense 검색이 기본입니다. BM25·Hybrid(RRF)는 설정에 따라 비교할 수 있고, 재정렬도 선택 사항입니다. 청크를 문헌별로 합치고 분야 검색이 부족하면 전체 색인으로 보완합니다.",
                "같은 특허의 여러 청구항이 후보 목록을 독점하지 않게 하고, 용어와 의미의 관련성을 살펴보기 위해서입니다.",
                "Dense · BM25 · Hybrid · 선택적 재정렬",
                ["src/retrieval/patent_search.py", "src/services/patent_service.py"],
            ),
            (
                "원문 근거 확보",
                "비교할 문헌 후보",
                "초록·관련 청구항과 인용 ID",
                "후보가 부족하면 KIPRIS 검색으로 보충하고, 선택 문헌의 청구항을 조회합니다. 종속항은 상위항과 함께 문맥을 구성합니다. 확보하지 못한 청구항은 추정해서 채우지 않습니다.",
                "검색 점수만으로 비교하지 않고, 원문에서 무엇이 실제로 설명돼 있는지 확인하기 위해서입니다.",
                "KIPRIS 검색·상세 API · 문맥 예산",
                ["src/ingestion/kipris_client.py", "src/ingestion/patent_processor.py"],
            ),
            (
                "내 구성과 비교",
                "아이디어 구성과 인용 가능한 원문",
                "구성별 유사점·차이점·미확인 항목",
                "근거를 LLM에 제공해 아이디어와 문헌을 비교하고, 존재하지 않는 인용 ID나 누락된 비교를 검사합니다. 초록만 확보됐다면 청구항 비교로 표현하지 않습니다.",
                "어떤 점이 비슷하고 다른지 사용자의 아이디어를 기준으로 설명하기 위해서입니다.",
                "근거를 포함한 생성 · 인용 계약 검증",
                ["src/generation/patent_analysis.py", "src/schemas.py"],
            ),
            (
                "설계 대안 검토",
                "기술 구성과 문헌별 비교 결과",
                "변경 방향·제약·검증 계획",
                "기존 구성과 근거를 바탕으로 최대 3개 설계 대안을 제안하고 관련 구성·문헌·인용 ID를 검사합니다. 제안이 실패해도 확보된 원문과 비교 결과는 남깁니다.",
                "유사 문헌 목록에서 더 나아가 어떤 구성을 바꿔 검토할지 생각하는 데 쓰기 위해서입니다.",
                "설계 제안 생성 · 참조 ID 검사",
                ["src/generation/patent_design.py", "src/services/patent_service.py"],
            ),
            (
                "결과와 한계 전달",
                "검증한 비교와 실제 확보한 자료",
                "특허 보고서와 다음 확인 과제",
                "문헌별 비교·인용·검색 범위와 미확인을 보여줍니다. 통합 보고서는 시장 근거도 함께 살피지만, 특허 유사성을 고객 수요로 바꾸거나 등록 가능성을 확정하지 않습니다.",
                "확보한 근거의 범위 안에서 다음 기술 검토를 결정하기 위해서입니다.",
                "PatentReport · 통합 검토",
                ["src/pipeline.py", "src/generation/executive_review.py"],
            ),
        ],
        "limits": "특허 비교와 설계 제안은 기술 검토 자료입니다. 신규성·진보성·침해·실시 자유를 확정하는 법률 판단은 아닙니다. 후보를 더 찾았다는 것과 검색 품질이 좋아졌다는 것도 구분합니다.",
        "evaluation": "Dense·BM25·Hybrid와 선택적 재정렬은 같은 질의·색인·사람 라벨로 비교해야 합니다. 후보 Recall과 상위 순위 품질(Hit·Precision·MRR·nDCG)을 구분하며, 라벨·표본이 부족하면 성능을 단정하지 않습니다.",
        "evaluation_sources": ["evaluation/patent_labeling.md", "docs/patent_rag.md"],
    },
    "market": {
        "title": "시장 자료가 내 아이디어의 검토로 이어지기까지",
        "summary": "산업에서 일어나는 일과, 내 고객이 실제로 구매할지는 구분해서 살펴봅니다.",
        "preparation": "뉴스 제목·요약과 DART 사업 본문을 수집·정제합니다. 같은 URL과 유사 보도를 정리하고 출처·발행일을 보존해 검색 색인을 만듭니다. 검색 관심도·조달·재무 자료는 별도 보조 경로입니다.",
        "steps": [
            (
                "다섯 질문으로 나누기",
                "확정한 문제·기술·고객·차별점·수익모델",
                "수요·경쟁/대체재·가격·구매자·도입장벽 질문",
                "아이디어의 각 항목으로 차원별 검색 질문을 만듭니다. 모르는 고객이나 수익모델을 임의로 채우지 않고 해당 판단의 한계로 남깁니다.",
                "막연한 시장 질문 하나로는 가격이나 도입 조건에 답할 근거를 놓치기 쉽기 때문입니다.",
                "구조화 입력 · 차원별 질의",
                ["src/generation/idea_parser.py", "src/retrieval/market_search.py"],
            ),
            (
                "출처별 자료 찾기",
                "다섯 질문과 준비된 시장 색인",
                "뉴스·관련 기업 공시 후보와 출처",
                "Dense 검색이 기본이며 중복 그룹을 정리합니다. 뉴스와 DART는 구분해 검색하고, 아이디어와 가까운 기업의 사업 본문을 참고합니다. 보조 자료는 키·수집 상태에 따라 제공됩니다.",
                "여러 매체가 옮긴 같은 보도를 독립적인 근거 여러 건으로 세지 않고 출처의 성격을 유지하기 위해서입니다.",
                "Chroma 의미 검색 · 기업 선택 · 출처 필터",
                ["src/retrieval/market_search.py", "src/services/market_service.py"],
            ),
            (
                "질문에 답하는지 확인",
                "검색 후보와 차원별 질문",
                "관련 근거·자료 상태·근거 성격",
                "주제가 비슷하다는 것과 질문에 답한다는 것을 구분합니다. 관련성 판정 뒤 관련 자료 수를 확인하고 구매 신호·기업 주장·간접 수요 등으로 분류합니다.",
                "주가 상승, 계획 발표, MOU를 내 제품의 수요가 확인된 것처럼 쓰지 않기 위해서입니다.",
                "LLM 관련성 판정 · 코드 기반 성격 규칙",
                ["src/retrieval/market_relevance.py", "prompts/market_label_judge.md"],
            ),
            (
                "근거를 넣어 분석",
                "관련 판정된 자료와 아이디어",
                "출처 ID가 연결된 차원별 분석 문장",
                "관련 근거를 LLM 문맥에 넣고 사실·사용자 주장·가설을 구분해 분석합니다. 자료가 부족한 차원은 미확인과 다음 검증 과제로 남깁니다.",
                "모델의 일반 지식만으로 답하는 대신 이번에 확보한 자료와 아이디어를 연결하기 위해서입니다.",
                "RAG 생성 · 차원별 인용 요약",
                ["src/generation/market_analysis.py", "prompts/market_analysis.md"],
            ),
            (
                "주장과 인용 검사",
                "생성 문장과 원문 발췌",
                "검증을 통과한 문장과 확인·신호·미확인 상태",
                "인용 ID의 존재, 출처에 있는 숫자와 연도, 판정 범위를 검사합니다. 오류가 있으면 제한 횟수 안에서 다시 생성하고, 여전히 검증하지 못한 문장은 제외하거나 미확인으로 둡니다.",
                "수집 과정이 정확해도 마지막 문장에서 없는 시장 규모나 가격을 만들어내면 의미가 없기 때문입니다.",
                "인용·수치 검사 · 제한 재생성",
                ["src/generation/market_analysis.py", "src/schemas.py"],
            ),
            (
                "의미와 다음 행동 정리",
                "검증된 시장 결과와 보조 자료",
                "시장 검토·시각화·예비 SWOT와 사업 모델",
                "핵심 사실과 다음 확인을 먼저 보고 상세 자료를 펼쳐봅니다. 관심도·뉴스 연결망·조달 공고·기업 재무는 서로 다른 신호입니다. 예비 SWOT·캔버스에서도 근거와 가설을 구분합니다.",
                "자료를 나열하는 데 그치지 않고 내 아이디어의 고객·구매 조건·도입 장벽을 다음 행동으로 연결하기 위해서입니다.",
                "MarketReport · 시각화 · 예비 사업 검토",
                [
                    "frontend/report_reading.py",
                    "src/generation/swot.py",
                    "src/generation/business_canvas.py",
                ],
            ),
        ],
        "limits": "검색 관심도는 시장 규모가 아니고, 기업 매출은 내 제품의 매출 전망이 아닙니다. 뉴스·공시·공공 조달의 신호를 실제 고객의 구매 의사로 일반화하지 않습니다. 출처 연결 검사는 해석의 정확성까지 보장하지 않습니다.",
        "evaluation": "검색 품질, 관련성 판정, 답변 인용 정확도는 따로 평가합니다. 참고 지도의 실험 수치는 당시 모델·자료·라벨 표본에 대한 결과이므로 현재 서비스 성능이나 실제 수요로 표시하지 않습니다.",
        "evaluation_sources": ["docs/experiments.md", "evaluation/market_labeling.md"],
    },
}


def render_process_guide(track):
    from html import escape

    guide = GUIDES[track]
    label = "특허 조사" if track == "patent" else "시장 조사"
    with st.container(key="info_hero"):
        words, picture = st.columns([1.35, 1], gap="large", vertical_alignment="center")
        with words:
            st.html(f'<div class="info-kicker">HOW IT WORKS / {label}</div>')
            st.title(
                "기술의 근거를 찾고, 구성으로 비교합니다."
                if track == "patent"
                else "시장의 신호를 찾고, 내 고객의 맥락으로 읽습니다."
            )
            st.write(guide["summary"])
        with picture:
            st.html(_flow_diagram(track))
    st.html(
        '<div class="info-route"><span>01 질문 설계</span><span>02 근거 검색</span><span>03 분석·검증</span><span>04 검토 노트</span></div>'
    )
    st.subheader("조사는 이렇게 진행됩니다")
    st.caption("자료 준비부터 결과까지 · 각 항목을 펼쳐 자세히 볼 수 있습니다.")
    with st.expander("00  자료 수집과 색인 준비"):
        st.write(guide["preparation"])
        st.caption(
            "자료를 미리 준비하는 과정입니다. 아이디어를 입력할 때마다 전체 자료를 다시 수집하지 않습니다."
        )
    for index, step in enumerate(guide["steps"]):
        title, incoming, outgoing, action, reason, tool, sources = step
        with st.expander(f"{index + 1:02}  {title}", expanded=index == 0):
            st.write(action)
            st.html(
                f'<div class="process-transfer"><div><small>입력</small><p>{escape(incoming)}</p></div><span aria-hidden="true">→</span><div><small>결과</small><p>{escape(outgoing)}</p></div></div>'
            )
            st.markdown("**이 단계의 역할**")
            st.write(reason)
            st.caption(tool)
            st.markdown(
                " · ".join(
                    f"[구현 근거 {i + 1}](https://github.com/LG-CNS-RAG-Project1/LG-CNS-RAG-Project/blob/develop/{source})"
                    for i, source in enumerate(sources)
                )
            )
    st.divider()
    st.html('<div class="info-kicker">METHOD</div>')
    st.subheader("어떤 방식으로 근거를 찾나요?")
    methods = (
        [
            (
                "Dense",
                "표현이 달라도 의미가 가까운 기술을 찾습니다. 기본 검색 방식입니다.",
            ),
            ("BM25", "기술명과 구성 용어가 직접 등장하는 문헌을 찾습니다."),
            (
                "Hybrid",
                "두 검색의 순위를 결합합니다. 설정에 따라 선택하며 재정렬은 별도 단계입니다.",
            ),
        ]
        if track == "patent"
        else [
            (
                "출처별 검색",
                "뉴스와 기업 공시를 구분하고 같은 보도는 중복 근거로 세지 않습니다.",
            ),
            (
                "관련성 확인",
                "주제가 비슷한지보다 내 질문에 답하는 근거인지를 확인합니다.",
            ),
            (
                "인용 검증",
                "분석 문장이 원문에 연결되는지 살피고 근거가 없는 내용은 미확인으로 남깁니다.",
            ),
        ]
    )
    st.html(
        '<div class="info-methods">'
        + "".join(
            f"<article><small>0{i + 1}</small><h3>{escape(name)}</h3><p>{escape(body)}</p></article>"
            for i, (name, body) in enumerate(methods)
        )
        + "</div>"
    )
    st.divider()
    st.html('<div class="info-kicker">EVALUATION</div>')
    st.subheader("검색과 답변, 따로 검증합니다")
    st.write("같은 질문과 자료 범위에서 검색 품질과 인용의 정확성을 나눠 확인합니다.")
    measures = (
        [
            ("후보 탐색", "관련 문헌을 후보로 찾았는가"),
            ("상위 순위", "관련 문헌이 앞에 놓였는가"),
            ("답변 근거", "비교 문장이 실제 인용으로 뒷받침되는가"),
        ]
        if track == "patent"
        else [
            ("검색 품질", "질문에 답하는 자료를 찾았는가"),
            ("관련성 판정", "관련·비관련 판단이 사람 검토와 맞는가"),
            ("인용 정확도", "답변의 사실과 수치가 출처에 있는가"),
        ]
    )
    st.html(
        '<div class="info-evaluation"><div>'
        + "".join(
            f'<div class="evaluation-row"><b>{escape(name)}</b><span>{escape(body)}</span></div>'
            for name, body in measures
        )
        + "</div><aside><small>COMPARISON CONDITIONS</small><h3>같은 조건에서 비교합니다.</h3><p>자료 범위·모델·실행 시점·사람 검토 여부를 함께 확인합니다. 표본과 라벨이 준비되지 않은 성능 점수는 표시하지 않습니다.</p></aside></div>"
    )
    with st.expander("평가 기준과 구현 자료"):
        st.write(guide["evaluation"])
        for source in guide["evaluation_sources"]:
            st.markdown(
                f"[{source}](https://github.com/LG-CNS-RAG-Project1/LG-CNS-RAG-Project/blob/develop/{source})"
            )
        st.caption(
            "이 안내는 분석이나 평가를 실행하지 않습니다. 운영 자료 수와 성능 점수는 추정하지 않습니다."
        )
    st.html(
        f'<aside class="info-footnote"><b>해석의 범위</b><p>{escape(guide["limits"])}</p></aside>'
    )
    st.markdown("**특허와 시장은 같은 아이디어에서 만납니다.**")
    st.write(
        "기술의 관련성과 고객·도입 조건을 함께 검토합니다. 점수를 단순 합산하지 않고, 확인한 근거와 다음에 확인할 것을 종합 보고서에 남깁니다."
    )


def process_styles():
    from pathlib import Path

    return (
        "<style>"
        + Path(__file__).with_name("information.css").read_text(encoding="utf-8")
        + "</style>"
    )


def _flow_diagram(track):
    labels = (
        ("기술 질의", "특허 문헌", "청구항 비교")
        if track == "patent"
        else ("검토 질문", "뉴스 · 공시", "인용 검증")
    )
    markup = f"""<figure class="info-diagram" aria-label="{' → '.join(labels)}">
    <figcaption>{'PATENT' if track == 'patent' else 'MARKET'} / EVIDENCE FLOW</figcaption>
    <svg viewBox="0 0 420 205" role="img" aria-label="질문에서 근거를 찾아 검증하는 흐름">
    <defs><marker id="{track}-arrow" viewBox="0 0 10 10" refX="9" refY="5" markerWidth="5" markerHeight="5" orient="auto-start-reverse"><path d="M0 0 L10 5 L0 10" fill="none" stroke="#799487" stroke-width="1.4"/></marker></defs>
    <g stroke="#a9bdb1" fill="none" stroke-width="1.2"><path d="M85 90 H168 M234 90 H317" marker-end="url(#{track}-arrow)"/><path d="M85 90 H168" marker-end="url(#{track}-arrow)"/><circle cx="53" cy="90" r="31"/><rect x="169" y="57" width="64" height="66" rx="4"/><circle cx="349" cy="90" r="31"/></g>
    <g stroke="#2c6654" fill="none" stroke-width="2"><circle cx="50" cy="86" r="10"/><path d="M57 94 L65 103 M185 75 H218 M185 87 H218 M185 99 H207 M336 90 L346 100 L363 79"/></g>
    <g fill="#375f4f" font-size="13" text-anchor="middle" font-family="sans-serif"><text x="53" y="155">{labels[0]}</text><text x="201" y="155">{labels[1]}</text><text x="349" y="155">{labels[2]}</text></g>
    </svg><p>검색 경로와 원문 근거를 함께 확인합니다.</p></figure>"""

    import base64

    start = markup.index("<svg")
    end = markup.index("</svg>") + len("</svg>")
    svg = markup[start:end].replace(
        "<svg ", '<svg xmlns="http://www.w3.org/2000/svg" ', 1
    )
    encoded = base64.b64encode(svg.encode("utf-8")).decode("ascii")
    return (
        markup[:start]
        + f'<img src="data:image/svg+xml;base64,{encoded}" alt="{' → '.join(labels)}" />'
        + markup[end:]
    )
