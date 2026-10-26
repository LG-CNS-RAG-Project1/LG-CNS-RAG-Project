from src.retrieval.schemas import PatentQueryPlan, PatentSearchQuery

from src.schemas import PatentSearchRequest, StructuredIdea
from src.retrieval.patent_search import build_patent_queries


def test_patent_query_plan():
    plan = PatentQueryPlan(
        queries=[
            PatentSearchQuery(
                technical_element="AI 비전 검사",
                korean_queries=[
                    "영상 기반 결함 검출",
                    "인공지능 품질 검사",
                ],
                english_queries=[
                    "visual defect detection",
                    "AI visual inspection",
                ],
            ),
            PatentSearchQuery(
                technical_element="협동로봇",
                korean_queries=["협동로봇 제어"],
                english_queries=["collaborative robot control"],
            ),
        ]
    )

    assert len(plan.queries) == 2
    assert plan.queries[0].technical_element == "AI 비전 검사"
    assert plan.queries[1].english_queries == ["collaborative robot control"]


def test_build_patent_queries():
    request = PatentSearchRequest(
        idea=StructuredIdea(
            title="AI 설비 예지보전",
            problem="제조 설비의 갑작스러운 고장",
            technology="진동 센서와 AI 이상 탐지",
            customers="중소 제조기업",
            difference="저비용 실시간 고장 예측",
            revenue="월 구독료",
        )
    )

    def fake_llm(system_prompt, user_text):
        assert "진동 센서와 AI 이상 탐지" in user_text

        return {
            "queries": [
                {
                    "technical_element": "진동 기반 이상 탐지",
                    "korean_queries": [
                        "진동 센서 이상 탐지",
                        "설비 진동 분석",
                    ],
                    "english_queries": [
                        "vibration anomaly detection",
                        "predictive maintenance",
                    ],
                }
            ]
        }

    result = build_patent_queries(request, llm_fn=fake_llm)

    assert isinstance(result, PatentQueryPlan)
    assert len(result.queries) == 1
    assert result.queries[0].technical_element == "진동 기반 이상 탐지"
    assert result.queries[0].korean_queries[0] == "진동 센서 이상 탐지"
