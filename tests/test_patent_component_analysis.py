import json
import pytest

from src.generation.patent_analysis import (
    PATENT_PRIORITY_LABELS,
    compare_patent_evidence,
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


@pytest.mark.parametrize("reason", [None, "", "  ", float("nan"), "NaN", "nan", "null"])
def test_llm_review_normalizes_missing_relevance_reason(reason):
    idea = StructuredIdea(
        title="검사 자동화",
        problem="불량 검출",
        technology="비전 검사",
    )
    evidence = [
        PatentEvidence(
            citation_id=1,
            patent_id="P1",
            title="검사 장치",
            section="abstract",
            quote="영상으로 검사를 수행한다",
        )
    ]

    def fake_llm(_prompt, _payload):
        return {
            "patent_reviews": [
                {
                    "patent_id": "P1",
                    "title": "검사 장치",
                    "relevance_reason": reason,
                    "component_comparisons": [
                        {
                            "component_id": "C1",
                            "idea_component": "비전 검사",
                            "status": "uncertain",
                            "citation_ids": [],
                            "overlap": "",
                            "difference": "",
                            "uncertainty": "근거 부족",
                        }
                    ],
                }
            ],
            "patentability_precheck": {
                "status": "insufficient_evidence",
                "summary": "근거 부족",
            },
        }

    reviews, _ = review_patents_by_component(idea, evidence, fake_llm)
    assert reviews[0].relevance_reason == ""


def test_component_review_bounds_total_evidence_and_reports_omitted_citations():
    idea = StructuredIdea(
        title="영상 검사",
        problem="결함 검사",
        technology="영상 기반 검사",
        technical_components=["영상 분석"],
    )
    evidence = [
        PatentEvidence(
            citation_id=1,
            patent_id="P1",
            title="검사 특허",
            section="abstract",
            quote="초록 " + "가" * 18000,
        ),
        PatentEvidence(
            citation_id=2,
            patent_id="P1",
            title="검사 특허",
            section="claims",
            quote="독립 청구항 " + "나" * 15000,
            claim_number=1,
            claim_type="independent",
        ),
    ]
    captured = {}

    def fake_llm(_prompt, user_text):
        captured.update(json.loads(user_text))
        return {
            "patent_reviews": [
                {
                    "patent_id": "P1",
                    "title": "검사 특허",
                    "citation_ids": [2],
                    "relevance": "medium",
                    "relevance_reason": "청구항 근거로 검토",
                    "component_comparisons": [
                        {
                            "component_id": "C1",
                            "idea_component": "영상 분석",
                            "status": "uncertain",
                            "citation_ids": [2],
                            "uncertainty": "구성 범위 추가 확인",
                        }
                    ],
                    "overall_summary": "청구항 원문 검토 필요",
                }
            ],
            "patentability_precheck": {
                "status": "insufficient_evidence",
                "summary": "예비 검토",
                "citation_ids": [2],
            },
        }

    reviews, _ = review_patents_by_component(idea, evidence, fake_llm)
    request_citations = captured["required_citation_ids"]
    assert request_citations == [2]
    assert len(reviews[0].unknowns) == 1
    assert "1" in reviews[0].unknowns[0]


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


def test_component_review_aligns_whitespace_variant_to_exact_source_text():
    idea = StructuredIdea(
        title="검사 자동화",
        problem="불량 검출",
        technology="비전 검사",
        technical_components=["라인 카메라"],
    )
    evidence = [
        PatentEvidence(
            citation_id=1,
            patent_id="P1",
            title="검사 장치",
            section="claims",
            quote="라인 카메라를\n포함하는 검사 장치",
        )
    ]

    def fake_llm(_prompt, _payload):
        return {
            "patent_reviews": [
                {
                    "patent_id": "P1",
                    "title": "검사 장치",
                    "citation_ids": [1],
                    "component_comparisons": [
                        {
                            "component_id": "C1",
                            "idea_component": "라인 카메라",
                            "status": "partial",
                            "citation_ids": [1],
                            "matched_text": "라인 카메라를 포함하는 검사 장치",
                        }
                    ],
                }
            ],
            "patentability_precheck": {
                "status": "insufficient_evidence",
                "summary": "추가 확인 필요",
                "citation_ids": [1],
            },
        }

    reviews, _ = review_patents_by_component(idea, evidence, fake_llm)
    assert reviews[0].component_comparisons[0].matched_text == evidence[0].quote


def test_component_review_keeps_report_when_highlight_is_not_verbatim_after_retry():
    idea = StructuredIdea(
        title="검사 자동화",
        problem="불량 검출",
        technology="비전 검사",
        technical_components=["라인 카메라"],
    )
    evidence = [
        PatentEvidence(
            citation_id=1,
            patent_id="P1",
            title="검사 장치",
            section="claims",
            quote="라인 카메라를 포함하는 검사 장치",
        )
    ]
    calls = []

    def fake_llm(_prompt, _payload):
        calls.append(1)
        return {
            "patent_reviews": [
                {
                    "patent_id": "P1",
                    "title": "검사 장치",
                    "citation_ids": [1],
                    "component_comparisons": [
                        {
                            "component_id": "C1",
                            "idea_component": "라인 카메라",
                            "status": "overlap",
                            "citation_ids": [1],
                            "matched_text": "원문에 없는 강조 구절",
                        }
                    ],
                }
            ],
            "patentability_precheck": {
                "status": "insufficient_evidence",
                "summary": "추가 확인 필요",
                "citation_ids": [1],
            },
        }

    reviews, _ = review_patents_by_component(idea, evidence, fake_llm)
    comparison = reviews[0].component_comparisons[0]
    assert len(calls) == 2
    assert comparison.status == "uncertain"
    assert comparison.matched_text == ""
    assert any("강조를 생략" in item for item in reviews[0].unknowns)


def test_component_review_retries_transient_llm_error_once():
    idea = StructuredIdea(
        title="검사 자동화",
        problem="불량 검출",
        technology="비전 검사",
        technical_components=["라인 카메라"],
    )
    evidence = [
        PatentEvidence(
            citation_id=1,
            patent_id="P1",
            title="검사 장치",
            section="claims",
            quote="라인 카메라를 포함하는 검사 장치",
        )
    ]
    calls = []

    def flaky_llm(_prompt, _payload):
        calls.append(1)
        if len(calls) == 1:
            raise TimeoutError("temporary API timeout")
        return {
            "patent_reviews": [
                {
                    "patent_id": "P1",
                    "title": "검사 장치",
                    "citation_ids": [1],
                    "relevance": "high",
                    "component_comparisons": [
                        {
                            "component_id": "C1",
                            "idea_component": "ignore caller component",
                            "status": "partial",
                            "citation_ids": [1],
                            "matched_text": "라인 카메라를 포함",
                        }
                    ],
                }
            ],
            "patentability_precheck": {
                "status": "insufficient_evidence",
                "summary": "추가 검토 필요",
                "citation_ids": [1],
            },
        }

    reviews, precheck = review_patents_by_component(idea, evidence, flaky_llm)
    assert len(calls) == 2
    assert reviews[0].component_comparisons[0].idea_component == "라인 카메라"
    assert precheck.status == "insufficient_evidence"


def test_component_review_does_not_retry_nontransient_api_error():
    idea = StructuredIdea(
        title="검사 자동화",
        problem="불량 검출",
        technology="비전 검사",
        technical_components=["라인 카메라"],
    )
    evidence = [
        PatentEvidence(
            citation_id=1,
            patent_id="P1",
            title="검사 장치",
            section="claims",
            quote="라인 카메라를 포함하는 검사 장치",
        )
    ]
    calls = []

    def unauthorized(_prompt, _payload):
        calls.append(1)
        raise RuntimeError("invalid API configuration")

    try:
        review_patents_by_component(idea, evidence, unauthorized)
    except RuntimeError as exc:
        assert "invalid API configuration" in str(exc)
    else:
        raise AssertionError("non-transient errors should be returned immediately")
    assert len(calls) == 1


def test_component_review_retry_identifies_missing_patent_ids():
    idea = StructuredIdea(
        title="검사 자동화",
        problem="불량 검출",
        technology="비전 검사",
        technical_components=["라인 카메라"],
    )
    evidence = [
        PatentEvidence(
            citation_id=1,
            patent_id="P1",
            title="검사 장치 1",
            section="claims",
            quote="라인 카메라로 검사하는 장치",
        ),
        PatentEvidence(
            citation_id=2,
            patent_id="P2",
            title="검사 장치 2",
            section="claims",
            quote="카메라를 사용해 검사하는 장치",
        ),
    ]
    requests = []

    def response_for(patent_id, citation_id):
        return {
            "patent_id": patent_id,
            "title": f"검사 장치 {patent_id}",
            "citation_ids": [citation_id],
            "relevance": "medium",
            "component_comparisons": [
                {
                    "component_id": "C1",
                    "idea_component": "라인 카메라",
                    "status": "partial",
                    "citation_ids": [citation_id],
                    "matched_text": evidence[citation_id - 1].quote,
                }
            ],
        }

    def fake_llm(_prompt, user_text):
        requests.append(user_text)
        reviews = (
            [response_for("P1", 1), response_for("P1", 1)]
            if len(requests) == 1
            else [response_for("P1", 1), response_for("P2", 2)]
        )
        return {
            "patent_reviews": reviews,
            "patentability_precheck": {
                "status": "insufficient_evidence",
                "summary": "추가 확인 필요",
                "citation_ids": [1, 2],
            },
        }

    reviews, _ = review_patents_by_component(idea, evidence, fake_llm)
    assert [item.patent_id for item in reviews] == ["P1", "P2"]
    assert len(requests) == 2
    assert '"missing_patent_ids": ["P2"]' in requests[1]
    assert '"duplicated_patent_ids": ["P1"]' in requests[1]


def test_component_review_retries_unknown_citation_id():
    idea = StructuredIdea(
        title="검사 자동화",
        problem="불량 검출",
        technology="비전 검사",
        technical_components=["라인 카메라"],
    )
    evidence = [
        PatentEvidence(
            citation_id=1,
            patent_id="P1",
            title="검사 장치",
            section="claims",
            quote="라인 카메라를 포함하는 검사 장치",
        )
    ]
    calls = []

    def fake_llm(_prompt, _payload):
        calls.append(1)
        citation_id = 99 if len(calls) == 1 else 1
        return {
            "patent_reviews": [
                {
                    "patent_id": "P1",
                    "title": "검사 장치",
                    "citation_ids": [citation_id],
                    "relevance": "high",
                    "component_comparisons": [
                        {
                            "component_id": "C1",
                            "idea_component": "라인 카메라",
                            "status": "partial",
                            "citation_ids": [citation_id],
                        }
                    ],
                }
            ],
            "patentability_precheck": {
                "status": "insufficient_evidence",
                "summary": "추가 확인 필요",
                "citation_ids": [citation_id],
            },
        }

    reviews, precheck = review_patents_by_component(idea, evidence, fake_llm)
    assert len(calls) == 2
    assert reviews[0].citation_ids == [1]
    assert precheck.citation_ids == [1]


def test_legacy_comparison_retries_duplicate_citation_response_once():
    idea = StructuredIdea(
        title="검사 자동화",
        problem="불량 검출",
        technology="비전 검사",
    )
    evidence = [
        PatentEvidence(
            citation_id=1,
            patent_id="P1",
            title="검사 장치",
            section="abstract",
            quote="비전 검사 장치",
        ),
        PatentEvidence(
            citation_id=2,
            patent_id="P2",
            title="검사 장치 2",
            section="abstract",
            quote="비전 검사 설비",
        ),
    ]
    calls = []
    requests = []

    def flaky_llm(_prompt, user_text):
        calls.append(1)
        requests.append(user_text)
        return {
            "comparisons": [
                {
                    "citation_id": 1,
                    "similarity": "비전 검사",
                    "difference": "전체 범위 미확인",
                    "uncertainty": "초록만 확인",
                },
                {
                    "citation_id": 1 if len(calls) == 1 else 2,
                    "similarity": "검사 관련",
                    "difference": "구성은 추가 확인",
                    "uncertainty": "초록만 확인",
                },
            ]
        }

    comparisons = compare_patent_evidence(idea, evidence, flaky_llm)
    assert len(calls) == 2
    assert [item.citation_id for item in comparisons] == [1, 2]
    assert '"missing_citation_ids": [2]' in requests[1]
    assert '"duplicated_citation_ids": [1]' in requests[1]


def test_orbit_category_uses_claim_evidence_and_comparison_not_similarity():
    from src.generation.patent_analysis import patent_orbit_category

    claim = PatentEvidence(
        citation_id=1,
        patent_id="P1",
        title="문헌",
        section="claims",
        quote="청구항",
        similarity=0.99,
    )
    abstract = PatentEvidence(
        citation_id=2,
        patent_id="P2",
        title="문헌",
        section="abstract",
        quote="요약",
        similarity=0.99,
    )
    direct = PatentDocumentReview(
        patent_id="P1",
        title="문헌",
        component_comparisons=[
            PatentComponentComparison(
                component_id="1",
                idea_component="요소",
                status="overlap",
                citation_ids=[1],
            )
        ],
    )
    partial = PatentDocumentReview(
        patent_id="P1",
        title="문헌",
        component_comparisons=[
            PatentComponentComparison(
                component_id="1",
                idea_component="요소",
                status="partial",
                citation_ids=[1],
            )
        ],
    )
    only_similarity = PatentDocumentReview(
        patent_id="P2", title="문헌", relevance="low"
    )
    assert patent_orbit_category(direct, {1: claim}) == "red"
    assert patent_orbit_category(partial, {1: claim}) == "yellow"
    assert patent_orbit_category(only_similarity, {2: abstract}) == "blue"


def test_kipris_application_search_url_accepts_only_application_numbers():
    from src.generation.patent_analysis import kipris_application_search_url

    assert kipris_application_search_url("10-2020-0000001") == (
        "https://www.kipris.or.kr/khome/search/searchResult.do?queryText=1020200000001"
    )
    assert kipris_application_search_url("https://evil.example/?q=123456") is None
    assert kipris_application_search_url(None) is None


def test_patent_report_validates_common_synthesis_citations():
    from pydantic import ValidationError
    from src.schemas import (
        PatentReport,
        PatentabilityPrecheck,
        PatentEvidence,
        PatentWatchout,
    )

    evidence = PatentEvidence(
        citation_id=1,
        patent_id="P1",
        title="문헌",
        section="claims",
        quote="청구항 원문",
    )
    with pytest.raises(
        ValidationError, match="Common patent watchout references unknown citation"
    ):
        PatentReport(
            status="completed",
            search_scope="test",
            evidence=[evidence],
            patentability_precheck=PatentabilityPrecheck(
                status="insufficient_evidence",
                summary="근거 제한",
                common_watchouts=[
                    PatentWatchout(
                        issue="주의",
                        why_it_matters="영향",
                        citation_ids=[9],
                        next_check="확인",
                    )
                ],
            ),
        )


def test_conflicting_recommendation_citations_are_downgraded_not_report_fatal():
    idea = StructuredIdea(
        title="검사 자동화",
        problem="불량 검출",
        technology="비전 검사",
        technical_components=["라인 카메라"],
    )
    evidence = [
        PatentEvidence(
            citation_id=1,
            patent_id="P1",
            title="검사 장치",
            section="claims",
            quote="라인 카메라를 포함하는 검사 장치",
        )
    ]
    calls = []

    def malformed_recommendation(_prompt, _payload):
        calls.append(1)
        return {
            "patent_reviews": [
                {
                    "patent_id": "P1",
                    "title": "검사 장치",
                    "citation_ids": [1],
                    "relevance": "high",
                    "component_comparisons": [
                        {
                            "component_id": "C1",
                            "idea_component": "라인 카메라",
                            "status": "partial",
                            "citation_ids": [1],
                            "matched_text": "라인 카메라를 포함",
                        }
                    ],
                    "design_recommendations": [
                        {
                            "recommendation": "다른 센서 방식 검토",
                            "rationale": "제품 설계 가설",
                            "basis": "hypothesis",
                            "citation_ids": [1],
                        },
                        {
                            "recommendation": "실시간 보정 검토",
                            "rationale": "근거 인용이 잘못된 응답",
                            "basis": "evidence_based",
                            "citation_ids": [99],
                        },
                    ],
                }
            ],
            "patentability_precheck": {
                "status": "insufficient_evidence",
                "summary": "추가 확인 필요",
                "citation_ids": [1],
            },
        }

    reviews, _ = review_patents_by_component(idea, evidence, malformed_recommendation)
    assert len(calls) == 1
    assert all(item.basis == "hypothesis" for item in reviews[0].design_recommendations)
    assert all(item.citation_ids == [] for item in reviews[0].design_recommendations)
    assert all(item.validation_needed for item in reviews[0].design_recommendations)
    assert any("citation ID가 일치하지 않아" in note for note in reviews[0].unknowns)
