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


def _select_step(track, index):
    st.session_state[f"process_step_{track}"] = index


def render_process_guide(track):
    guide = GUIDES[track]
    st.caption(
        "분석 방식 안내 · 아래 단계를 눌러도 조사나 API 호출은 실행되지 않습니다."
    )
    st.title(guide["title"])
    st.write(guide["summary"])
    with st.expander("먼저 준비하는 자료와 실시간 조사는 어떻게 다른가요?"):
        st.write(guide["preparation"])
        st.caption(
            "수집·정제·임베딩·색인 준비와, 입력한 아이디어로 검색하는 요청은 별개입니다. 매번 모든 자료를 다시 수집하지 않습니다. 설명은 현재 코드의 경로이며 이 서버의 자료·키 준비 상태를 점검한 결과는 아닙니다."
        )
    st.html(
        """<div class="rag-explainer" aria-label="RAG의 세 단계"><span><b>찾기</b> 관련 자료 검색</span><i>→</i><span><b>근거 넣기</b> 출처와 문맥 구성</span><i>→</i><span><b>설명하기</b> 생성 후 인용 검증</span></div>"""
    )
    st.subheader("어떤 단계가 궁금한가요?")
    index = st.session_state.get(f"process_step_{track}", 0)
    if not isinstance(index, int) or not 0 <= index < len(guide["steps"]):
        index = 0
    for start in (0, 3):
        cols = st.columns(3)
        for i in range(start, start + 3):
            cols[i - start].button(
                f"{i + 1:02} {guide['steps'][i][0]}",
                key=f"process_{track}_{i}",
                type="primary" if i == index else "secondary",
                width="stretch",
                on_click=_select_step,
                args=(track, i),
            )
    title, incoming, outgoing, action, reason, tool, sources = guide["steps"][index]
    with st.container(border=True, key="process_detail"):
        st.caption(
            f"설명 단계 {index + 1} / {len(guide['steps'])} · 실행 진행률이 아닙니다"
        )
        st.subheader(title)
        left, right = st.columns(2)
        with left:
            st.markdown("**입력받는 것**")
            st.write(incoming)
        with right:
            st.markdown("**다음에 넘기는 것**")
            st.write(outgoing)
        st.divider()
        st.write(action)
        st.info("이렇게 하는 이유 · " + reason)
        with st.expander("사용 기술과 구현 근거"):
            st.write(tool)
            for source in sources:
                st.markdown(
                    f"[{source}](https://github.com/LG-CNS-RAG-Project1/LG-CNS-RAG-Project/blob/develop/{source})"
                )
    with st.expander("검색·분석 품질은 어떻게 확인하나요?"):
        st.write(guide["evaluation"])
        for source in guide["evaluation_sources"]:
            st.markdown(
                f"[{source}](https://github.com/LG-CNS-RAG-Project1/LG-CNS-RAG-Project/blob/develop/{source})"
            )
        st.caption(
            "안내 화면은 평가나 재학습을 실행하지 않습니다. 현재 운영 색인 건수나 성능 점수를 추정해 표시하지 않습니다."
        )
    if track == "patent":
        with st.expander("Dense·BM25·Hybrid와 재정렬은 무엇이 다른가요?"):
            cols = st.columns(3)
            for col, name, role in zip(
                cols,
                ("Dense", "BM25", "Hybrid · RRF"),
                (
                    "표현이 달라도 문맥상 가까운 기술을 찾습니다. 기본 검색 경로입니다.",
                    "기술명이나 구성 용어가 본문에 직접 등장하는 후보를 찾습니다.",
                    "Dense와 BM25의 후보 순위를 결합합니다. 서로 다른 점수 자체를 더하지 않습니다.",
                ),
            ):
                with col.container(border=True):
                    st.markdown(f"**{name}**")
                    st.write(role)
            st.write(
                "후보를 모은 뒤 문헌 단위로 집계하고, 선택적 재정렬로 상위 순서를 다시 정교화할 수 있습니다. 후보 생성과 재정렬 효과는 분리해서 평가합니다."
            )
            st.caption(
                "분야 필터 결과와 전체 색인 보충 경로도 구분합니다. 여러 청크가 한 문헌에서 나왔다면 독립적인 특허 여러 건으로 세지 않습니다."
            )
            st.link_button(
                "참고한 특허 조사 지도 ↗",
                "https://astounding-syrniki-4326f2.netlify.app/",
            )
    st.caption(guide["limits"])
    st.markdown("**두 조사는 마지막에 어떻게 만나나요?**")
    st.write(
        "같은 아이디어를 기준으로 특허의 기술적 관련성과 시장의 고객·도입 맥락을 함께 검토합니다. 서로 다른 점수를 단순 합산하지 않고, 확인된 근거·해석·가설·미확인과 다음 검증을 구분해 종합 보고서에 담습니다."
    )


def process_styles():
    return """<style>
    .st-key-introduction button[kind="primary"]{background:#176b60;border-color:#176b60;color:white;}
    .rag-explainer{display:flex;gap:14px;align-items:center;justify-content:space-between;margin:25px 0;padding:22px;background:#fffdf3;border:1px solid #dbe5d5;border-radius:16px;}
    .rag-explainer span{display:flex;flex-direction:column;gap:6px;color:#58746a;font-size:14px;}.rag-explainer b{font-size:19px;color:#1f4943;}.rag-explainer i{color:#86a295;font-style:normal;}
    .st-key-process_detail{background:#fffef8;border-radius:16px;padding:24px!important;margin:20px 0;}
    .st-key-intro_journey [data-testid="stVerticalBlockBorderWrapper"]{height:100%;}
    [class*="st-key-intro_card_"]{min-height:300px;background:#fffef8;border-radius:18px;padding:24px!important;}
    .st-key-intro_card_evidence .st-key-intro_open_patent button{background:#e6f1e7;color:#1d5c50;border-color:#bcd3c5;min-height:70px;}
    .st-key-intro_card_evidence .st-key-intro_open_market button{background:#f7f0d8;color:#65552b;border-color:#ded1a2;min-height:70px;}
    @media(max-width:700px){.rag-explainer{gap:8px;padding:15px;}.rag-explainer span{font-size:11px}.rag-explainer b{font-size:15px;}[class*="st-key-intro_card_"]{min-height:0;}.st-key-process_detail{padding:16px!important;}}
    </style>"""
