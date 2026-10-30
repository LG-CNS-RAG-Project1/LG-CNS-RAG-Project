"""IdeaLens 시장 조사·평가 흐름과 측정 결과를 안내한다."""

import streamlit as st

_STEPS = (
    (
        "01 · 아이디어 입력",
        "한 문장을 문제·기술·고객·차별점·수익모델로 구조화한다. 비어 있는 항목은 최대 2회 다시 묻고, 모르는 정보는 추측하지 않고 미확인으로 둔다.",
        (
            (
                "아이디어 구조화",
                "gpt-4o-mini · Pydantic `IdeaDraft`",
                "공통 검색 질의의 맥락을 만들기 위해서다.",
            ),
            (
                "입력 가드레일",
                "길이·프롬프트 조작 규칙 + 구조화 LLM 판정",
                "별도 LLM 호출을 더하지 않고 주제 이탈·조작 입력을 막는다.",
            ),
        ),
        "`src/generation/idea_parser.py` · `src/generation/input_guard.py` · `prompts/idea_parser.md`",
    ),
    (
        "02 · 시장 자료 수집",
        "차원별 뉴스와 기업·공공 자료를 모으되, 자료의 성격을 시장 수요로 과장하지 않도록 출처 유형을 구분한다.",
        (
            (
                "뉴스 기사",
                "NAVER 뉴스 API · 설정 키워드 28개, 키워드별 최대 100건",
                "국내 산업 동향의 제목·요약·링크·발행일을 수집한다.",
            ),
            (
                "DART 사업보고서",
                "OpenDART · 설정 기업 14곳의 최신 보고서",
                "기업이 공시한 사업 설명을 뉴스와 구분해 확인한다.",
            ),
            (
                "검색 관심도",
                "NAVER Search Trend · 기준 주제어 대비 상대 지수",
                "시장 규모를 추정하지 않고 관심 흐름만 본다.",
            ),
            (
                "공공 조달",
                "공공데이터포털 나라장터",
                "공공 부문의 입찰 공고와 예산을 민간 수요와 구별한다.",
            ),
            (
                "기업 재무",
                "OpenDART 재무 계정 API",
                "기업 실적을 시장 규모나 구매 의사의 증거로 혼동하지 않는다.",
            ),
        ),
        "`src/ingestion/news_client.py` · `src/ingestion/dart_client.py` · `src/ingestion/trend_client.py` · `src/ingestion/procurement_client.py`",
    ),
    (
        "03 · 정제와 색인",
        "출처를 추적할 수 있는 문서 원장을 만들고, 검색 중복과 인용 위치를 관리한다. 저장된 설계 기준에서는 뉴스는 기사당 1청크, DART 사업 본문은 800자 이하·150자 겹침으로 나눈다.",
        (
            (
                "중복 제거",
                "같은 URL 병합 · 제목 유사도 0.8 초과 · 3일 이내 그룹화",
                "여러 매체가 옮긴 같은 보도를 독립적인 자료 여러 건으로 세지 않기 위해서다.",
            ),
            (
                "청킹",
                "뉴스는 기사당 1청크 · DART 본문은 최대 800자, 150자 겹침",
                "짧은 뉴스 요약과 긴 공시 본문에 맞는 검색·인용 단위를 쓴다.",
            ),
            (
                "출처 메타데이터",
                "`source_id` · 발행일 · 출처 유형 · 신뢰도",
                "인용과 최신성·자료 종류를 문서까지 거슬러 확인한다.",
            ),
            (
                "벡터 저장소",
                "`text-embedding-3-small` · ChromaDB cosine",
                "같은 입력은 고정 ID로 갱신해 재색인 결과를 관리한다.",
            ),
            (
                "기록된 코퍼스 스냅샷",
                "뉴스 1,976건 · DART 348청크",
                "당시 실험 규모를 설명하는 값이며 현재 색인 건수로 간주하지 않는다.",
            ),
        ),
        "`src/ingestion/market_processor.py` · `src/retrieval/engine.py` · `configs/technology_areas.yaml`",
    ),
    (
        "04 · 다섯 차원 검색",
        "넓은 질문 하나 대신 수요·경쟁/대체재·가격·구매자·도입장벽 질문을 각각 만들고, 아이디어와 출처 조건에 맞춰 후보를 찾는다.",
        (
            (
                "기본 후보 검색",
                "Dense 벡터 검색 · 차원별 Top-20에서 중복 그룹 정리 후 상위 5건",
                "관련 표현의 문맥 유사도를 찾는다.",
            ),
            (
                "방식 비교",
                "Dense · BM25 · Hybrid(RRF)",
                "저장된 최신 비교에서 Dense Hit@5 0.95, Hybrid 0.80, BM25 0.60이었다.",
            ),
            (
                "DART 기업 선택",
                "gpt-4o-mini · 실패 시 임베딩 유사도 fallback",
                "아이디어의 제품·공정 범주와 가까운 기업을 최대 3곳 고른다.",
            ),
        ),
        "`src/retrieval/market_search.py` · `src/services/market_service.py` · `docs/experiments.md`",
    ),
    (
        "05 · 관련성과 근거 성격 판정",
        "검색 주제가 비슷한지와 질문에 실제 답하는지를 구분한다. 관련 문헌 수와 구매 근거의 성격으로 충분성·판정 범위를 제한한다.",
        (
            (
                "거리 임계값은 사용하지 않음",
                "거리 기반 분류 AUC 0.52",
                "거리만으로 충분성을 판단하는 방식은 기준선보다 낫지 않았다.",
            ),
            (
                "관련성 판정",
                "gpt-4o-mini · 관련 2건 이상 충분, 1건 제한, 0건 부족",
                "현재 mini + 근거 성격 판정은 사람 라벨 91행에서 정밀도 0.72, 재현율 0.78, kappa 0.42였다.",
            ),
            (
                "근거 성격",
                "구매 신호 · 간접 수요 · 추정치 · 기업 주장 · 사업 신호",
                "실제 도입·구매와 계획·MOU·기업 주장을 구분한다.",
            ),
        ),
        "`src/retrieval/market_relevance.py` · `prompts/market_label_judge.md` · `docs/market_research.md`",
    ),
    (
        "06 · 시장 분석 생성과 검증",
        "관련 판정된 근거를 바탕으로 차원별 최대 3문장을 만들고, 인용 연결·수치·판정 상태를 코드로 확인한다.",
        (
            (
                "근거 연결",
                "모든 사실 문장에 citation ID",
                "사용자가 원문 또는 출처 요약을 따라가게 한다.",
            ),
            (
                "주장 검증",
                "인용 존재 · 숫자·연도 출처 · 근거 상태 검사",
                "문서에 없는 사실·수치가 보고서에 남지 않게 한다.",
            ),
            (
                "제한 재생성",
                "검증 실패 시 최대 2회 재생성 후 미확인 처리",
                "근거가 약한 차원에 확정적 결론을 강요하지 않는다.",
            ),
        ),
        "`src/generation/market_analysis.py` · `prompts/market_analysis.md` · `src/schemas.py`",
    ),
    (
        "07 · 인사이트와 사업 검토 화면",
        "검색 관심도·뉴스 연결망·조달 공고·기업 재무를 별도 신호로 보여주고 예비 SWOT과 비즈니스 모델 캔버스로 다음 검토 항목을 정리한다.",
        (
            (
                "시장 지표",
                "검색 관심도 · 키워드 동시 출현",
                "상대 관심 흐름과 같은 기사에서 함께 언급된 주제를 관찰하며 시장 수요로 해석하지 않는다.",
            ),
            (
                "구매·기업 신호",
                "나라장터 공고 · DART 재무",
                "공공 구매와 기업 실적을 구분하고 민간 고객의 구매 확인으로 일반화하지 않는다.",
            ),
            (
                "예비 SWOT·캔버스",
                "gpt-4o-mini · 코드 기반 근거 검사",
                "출처 근거·사용자 주장·AI 가설을 분리하며 빈 사업 모델 칸은 가설로 남긴다.",
            ),
            (
                "미사용 프레임워크",
                "BCG · GE–McKinsey · EFE/IFE",
                "점유율·가중치 등 출처로 뒷받침할 자료가 없어 점수화하지 않는다.",
            ),
        ),
        "`frontend/market_trend_view.py` · `frontend/market_network_view.py` · `frontend/market_procurement_view.py` · `frontend/market_financials_view.py` · `src/generation/swot.py` · `src/generation/business_canvas.py`",
    ),
    (
        "08 · 평가와 개선",
        "검색 방식·근거 판정·최종 답변을 별도 평가한다. 사람 검토 라벨과 실험 당시 조건을 함께 읽는다.",
        (
            (
                "검색 방식 비교",
                "SF-01~04 20문항 · 세 방식 후보 423건",
                "423행 중 블라인드 사람 라벨 72행, LLM 초안 228행과 방식 비교용 LLM 초안 123행이다. 낮은 확신 표본만 추가 검토했으므로 423행 전체를 사람 라벨로 보면 안 된다.",
            ),
            (
                "관련성 검증",
                "사람 블라인드 라벨 91행",
                "사람·LLM 판정 불일치와 표본 크기를 함께 고려한다.",
            ),
            (
                "답변 비교",
                "LLM 단독 · 단순 RAG · IdeaLens · 사람 검토 30문장",
                "사람 검토 보정 Citation Accuracy는 0.43 · 0.87로 기록됐다.",
            ),
        ),
        "`evaluation/market_labeling.md` · `evaluation/results/` · `docs/experiments.md`",
    ),
)


def _render_step(title, description, details, source):
    with st.container(border=True):
        st.markdown(f"#### {title}")
        st.write(description)
        columns = st.columns(2)
        for index, (name, tool, reason) in enumerate(details):
            with columns[index % 2]:
                st.markdown(f"**{name}** · {tool}")
                st.caption(f"선택 이유: {reason}")
        st.caption(f"코드·자료: {source}")


def render_market_process_page():
    """시장 조사 파이프라인과 실험 결과·해석 한계를 보여준다."""
    with st.container(key="market_process_page"):
        st.caption("IDEALENS · 스마트팩토리 · 시장 조사 흐름")
        st.title("아이디어 한 문장에서 근거가 붙은 시장 검토까지")
        st.write(
            "시장 파트의 입력·자료 수집·검색·분석·평가를 따라가며, 어떤 도구를 왜 쓰는지와 결과를 어디까지 해석할 수 있는지 살펴봅니다."
        )

        st.markdown(
            "**입력:** 아이디어 한 문장　　**출력:** 출처가 연결된 시장 `MarketReport`와 예비 사업 검토"
        )
        metric_columns = st.columns(3)
        metric_columns[0].metric("검색 차원", "5개")
        metric_columns[0].caption("수요 · 경쟁 · 가격 · 구매자 · 장벽")
        metric_columns[1].metric("방식 비교", "20문항")
        metric_columns[1].caption("SF-01~04 · 동일 평가 풀")
        metric_columns[2].metric("답변 검토", "30문장")
        metric_columns[2].caption("사람 검토 표본")

        for title, description, details, source in _STEPS:
            _render_step(title, description, details, source)

        st.subheader("검색 방식 비교 · 저장된 평가 결과")
        st.caption(
            "20개 문항(SF-01~04)의 저장 결과다. 이번 화면 작업에서 다시 실행한 수치가 아니다."
        )
        st.table(
            {
                "방식": ["Dense (기본)", "Hybrid (RRF)", "BM25"],
                "Hit@5": ["0.95", "0.80", "0.60"],
                "Recall@5": ["0.38", "0.29", "0.18"],
                "Precision@5": ["0.46", "0.45", "0.32"],
                "MRR": ["0.60", "0.58", "0.41"],
                "nDCG@5": ["0.47", "0.46", "0.32"],
                "검색 시간": ["411 ms", "346 ms", "107 ms"],
            }
        )

        st.subheader("사람 검토 보정 Citation Accuracy · 과거 실험")
        st.table(
            {
                "비교 방식": ["단순 RAG", "IdeaLens"],
                "사실 문장": ["37", "30"],
                "사람 보정 Citation Accuracy": ["0.43", "0.87"],
                "인용 기사 관련 비율": ["0.73", "0.83"],
            }
        )
        st.warning(
            "이 답변 실험 당시에는 gpt-4o와 뉴스 자료만 사용했습니다. 현재 서비스는 gpt-4o-mini, DART 자료, 기업 선택·근거 성격 규칙을 포함하므로 위 수치를 현재 구성의 성능으로 간주하면 안 됩니다. 평가 표본도 방식별 사람 검토 15문장입니다."
        )

        st.subheader("모든 단계에 적용하는 해석 원칙")
        left, right = st.columns(2)
        with left:
            st.markdown(
                "**사업 신호는 고객 수요가 아닙니다.** 뉴스·공시·검색 관심도·공공 조달은 서로 다른 자료이며, 고객의 실제 구매 의사는 고객 검증 자료로 확인합니다."
            )
            st.markdown(
                "**근거가 부족하면 미확인으로 둡니다.** 관련 기사 한 건이나 계획·MOU만으로 시장을 확인했다고 표현하지 않습니다."
            )
        with right:
            st.markdown(
                "**평가 라벨과 표본의 출처를 확인합니다.** LLM 초안은 정답 라벨이 아니며, 불일치 판정과 작은 사람 검토 표본은 결과 해석의 한계입니다."
            )
            st.markdown(
                "**실험 조건이 다르면 수치를 직접 비교하지 않습니다.** SF-05의 평가 문항도 이전 아이디어 기준이라 최신 검색 비교에서 제외되어 있습니다."
            )

        st.info(
            "이 화면의 수치는 저장된 과거 실험 기록입니다. 시장 규모·사업 성공·고객 구매를 확정하지 않으며, 실행 시점의 자료와 모델 설정에 따라 결과는 달라질 수 있습니다."
        )
        st.caption(
            "코퍼스 스냅샷도 실험 시점 기준입니다. 저장소 기준선 문서에는 현재 로컬 처리 데이터와 색인이 비어 있는 것으로 기록되어 있어, 배포 앱의 공용 색인 상태를 이 수치가 대변하지 않습니다."
        )
        st.caption(
            "측정 근거: `docs/experiments.md`, `docs/market_research.md`, `evaluation/results/`, `evaluation/market_labeling.md`"
        )
