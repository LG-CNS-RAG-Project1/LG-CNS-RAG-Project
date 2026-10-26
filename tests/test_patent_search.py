from src.retrieval.schemas import PatentQueryPlan, PatentSearchQuery


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
