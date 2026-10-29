import json

import pytest

from src.generation.patent_design import generate_patent_design_analysis
from src.schemas import (
    PatentDesignAnalysis,
    PatentDocumentReview,
    PatentEvidence,
    StructuredIdea,
)


def idea():
    return StructuredIdea(
        title="설비 이상 탐지",
        problem="설비 이상을 조기에 찾기 어렵다",
        technology="센서 데이터 기반 이상 탐지",
        technical_components=["센서 데이터 수집", "이상 탐지 모델"],
    )


def evidence(section="claims"):
    return [
        PatentEvidence(
            citation_id=1,
            patent_id="P-1",
            title="설비 진단 장치",
            section=section,
            quote="복수 센서의 데이터를 수집하여 이상 상태를 판정하는 장치",
            claim_number=1 if section == "claims" else None,
        )
    ]


def proposal(proposal_id, change, **overrides):
    row = {
        "proposal_id": proposal_id,
        "title": proposal_id,
        "target_component_ids": ["C2"],
        "problem": "단일 센서 기반 여부가 불명확함",
        "proposed_change": change,
        "implementation_approach": ["센서별 특징을 추출하고 융합한다"],
        "technical_difference": "복수 센서 융합을 적용한다",
        "expected_benefits": ["센서 단독 오탐을 줄일 가능성"],
        "limitations": ["센서 동기화가 필요함"],
        "feasibility": "medium",
        "related_patent_ids": ["P-1"],
        "citation_ids": [1],
        "evidence_status": "grounded",
        "verification_plan": {
            "method": "단일 센서 기준 모델과 동일 데이터에서 비교",
            "metrics": ["F1", "오탐률"],
            "success_criteria": "실험 전에 기준 모델 대비 목표를 설정",
        },
        "patent_verification_required": True,
    }
    row.update(overrides)
    return row


def test_generates_structured_grounded_proposals_and_passes_context_to_fake_llm():
    captured = {}

    def fake_llm(prompt, user_text):
        captured["prompt"] = prompt
        captured["payload"] = json.loads(user_text)
        return {
            "proposals": [
                proposal("DP-01", "복수 센서 융합"),
                proposal("DP-02", "설비별 엣지 추론"),
            ]
        }

    result = generate_patent_design_analysis(
        idea(),
        evidence(),
        [PatentDocumentReview(patent_id="P-1", title="설비 진단 장치")],
        None,
        llm_fn=fake_llm,
    )
    assert result.status == "success"
    assert result.evidence_level == "claims_only"
    assert [item.id for item in result.technical_components] == ["C1", "C2"]
    assert len(result.proposals) == 2
    assert captured["payload"]["allowed_citation_ids"] == [1]
    assert "Do not determine infringement" in captured["prompt"]


def test_abstract_only_is_marked_partial_and_no_results_does_not_call_llm():
    output = generate_patent_design_analysis(
        idea(),
        evidence("abstract"),
        [],
        None,
        llm_fn=lambda *_: {"proposals": [proposal("DP-01", "구조 변경")]},
    )
    assert output.status == "partial"
    assert output.evidence_level == "abstract_only"
    assert output.missing_information

    empty = generate_patent_design_analysis(
        idea(), [], [], None, llm_fn=lambda *_: pytest.fail("must not call LLM")
    )
    assert empty.status == "insufficient_evidence"
    assert empty.proposals == []


@pytest.mark.parametrize(
    "row",
    [
        proposal("DP-01", "변경", target_component_ids=["C99"]),
        proposal("DP-01", "변경", related_patent_ids=["P-99"]),
        proposal("DP-01", "변경", citation_ids=[99]),
        proposal("DP-01", "변경", related_patent_ids=[], citation_ids=[1]),
    ],
)
def test_rejects_invalid_component_patent_and_citation_references(row):
    with pytest.raises(ValueError):
        generate_patent_design_analysis(
            idea(), evidence(), [], None, llm_fn=lambda *_: {"proposals": [row]}
        )


def test_deduplicates_same_design_change():
    output = generate_patent_design_analysis(
        idea(),
        evidence(),
        [],
        None,
        llm_fn=lambda *_: {
            "proposals": [
                proposal("DP-01", "복수 센서 융합"),
                proposal("DP-02", "  복수   센서 융합 "),
            ]
        },
    )
    assert len(output.proposals) == 1


def test_report_rejects_unknown_proposal_citation():
    from src.schemas import PatentReport

    with pytest.raises(ValueError, match="unknown citation"):
        PatentReport(
            status="completed",
            evidence=evidence(),
            search_scope="test",
            design_analysis=PatentDesignAnalysis(
                status="success",
                evidence_level="claims_and_abstract",
                technical_components=[{"id": "C1", "name": "x", "description": "x"}],
                proposals=[
                    proposal(
                        "DP-01", "change", target_component_ids=["C1"], citation_ids=[2]
                    )
                ],
            ),
        )
