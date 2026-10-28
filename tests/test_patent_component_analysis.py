import json

from src.generation.patent_analysis import (
    PATENT_PRIORITY_LABELS,
    highlight_verbatim_excerpt,
    patent_review_priority,
    review_patents_by_component,
)
from src.schemas import (
    PatentComponentComparison,
    PatentDocumentReview,
    PatentEvidence,
    StructuredIdea,
)


def test_patent_review_groups_citations_and_maps_each_idea_component():
    idea = StructuredIdea(
        title="검사 자동화",
        problem="불량 검출",
        technology="비전 검사",
        technical_components=["라인 카메라", "결함 분류 모델"],
    )
    evidence = [
        PatentEvidence(
            citation_id=1,
            patent_id="P1",
            title="검사 장치",
            section="claims",
            quote="라인 카메라를 포함하는 검사 장치",
            claim_number=1,
            claim_type="independent",
        ),
        PatentEvidence(
            citation_id=2,
            patent_id="P1",
            title="검사 장치",
            section="claims",
            quote="제1항에 있어서 결함을 분류하는 처리부",
            claim_number=2,
            claim_type="dependent",
            depends_on=[1],
        ),
    ]
    captured = {}

    def fake_llm(_prompt, payload):
        captured.update(json.loads(payload))
        return {
            "patent_reviews": [
                {
                    "patent_id": "P1",
                    "title": "검사 장치",
                    "citation_ids": [1, 2],
                    "relevance": "high",
                    "relevance_reason": "구성 요소가 일부 대응함",
                    "component_comparisons": [
                        {
                            "component_id": "C1",
                            "idea_component": "LLM이 바꾼 텍스트",
                            "status": "overlap",
                            "citation_ids": [1],
                            "overlap": "카메라 사용",
                            "difference": "비교 범위 한정",
                            "uncertainty": "전체 청구항 미확인",
                        },
                        {
                            "component_id": "C2",
                            "idea_component": "다른 내용",
                            "status": "partial",
                            "citation_ids": [2],
                            "overlap": "분류 처리",
                            "difference": "모델 방식 미확인",
                            "uncertainty": "세부 모델 불명",
                        },
                    ],
                    "overall_summary": "일부 구성 대응",
                }
            ],
            "patentability_precheck": {
                "status": "overlap_concern",
                "summary": "유사 구성 검토 필요",
                "citation_ids": [1, 2],
                "expert_questions": ["독립항 범위 확인"],
                "limitations": ["검색 범위 한계"],
            },
        }

    reviews, precheck = review_patents_by_component(idea, evidence, fake_llm)
    assert captured["required_patent_ids"] == ["P1"]
    assert len(captured["patents"]) == 1
    assert reviews[0].citation_ids == [1, 2]
    assert [c.idea_component for c in reviews[0].component_comparisons] == [
        "라인 카메라",
        "결함 분류 모델",
    ]
    assert precheck.citation_ids == [1, 2]


def test_priority_orders_cited_overlap_before_partial_and_low_relevance():
    high_overlap = PatentDocumentReview(
        patent_id="1",
        title="A",
        relevance="high",
        component_comparisons=[
            PatentComponentComparison(
                component_id="C1",
                idea_component="x",
                status="overlap",
                citation_ids=[1],
            )
        ],
    )
    partial = PatentDocumentReview(
        patent_id="2",
        title="B",
        relevance="medium",
        component_comparisons=[
            PatentComponentComparison(
                component_id="C1",
                idea_component="x",
                status="partial",
                citation_ids=[2],
            )
        ],
    )
    low = PatentDocumentReview(patent_id="3", title="C", relevance="low")
    assert patent_review_priority(high_overlap) < patent_review_priority(partial)
    assert patent_review_priority(partial) < patent_review_priority(low)
    assert PATENT_PRIORITY_LABELS[0] == "우선 확인"


def test_patent_excerpt_highlights_only_verbatim_text_and_escapes_html():
    highlighted = highlight_verbatim_excerpt(
        "센서 <입력>을 분석하여 이상을 판별한다.", "이상을 판별"
    )
    assert "&lt;입력&gt;" in highlighted
    assert "<mark><u>이상을 판별</u></mark>" in highlighted
    assert "<script>" not in highlight_verbatim_excerpt("<script>alert(1)</script>")
    assert "<mark>" not in highlight_verbatim_excerpt("실제 인용", "없음")
