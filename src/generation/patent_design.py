"""특허 근거를 활용한 구체적 설계 대안 생성."""

import json
from pathlib import Path
from typing import Callable

from src.generation.patent_analysis import call_comparison_llm
from src.schemas import (
    PatentDesignAnalysis,
    PatentDesignProposal,
    PatentDocumentReview,
    PatentEvidence,
    PatentTechnicalComponent,
    PatentabilityPrecheck,
    StructuredIdea,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT_DIR / "prompts" / "patent_design_proposals.md"
DesignProposalLLMFn = Callable[[str, str], dict]


def _idea_components(idea: StructuredIdea) -> list[PatentTechnicalComponent]:
    """명시된 기술 요소를 우선 사용하고 없으면 기술 설명을 하나의 요소로 둔다."""
    names = [item.strip() for item in idea.technical_components if item.strip()]
    if not names and idea.technology.strip():
        names = [idea.technology.strip()]
    return [
        PatentTechnicalComponent(
            id=f"C{index}", name=name, description=name, source_type="user_stated"
        )
        for index, name in enumerate(names, 1)
    ]


def generate_patent_design_analysis(
    idea: StructuredIdea,
    evidence: list[PatentEvidence],
    reviews: list[PatentDocumentReview],
    precheck: PatentabilityPrecheck | None,
    *,
    llm_fn: DesignProposalLLMFn = call_comparison_llm,
) -> PatentDesignAnalysis:
    """기존 비교 결과와 원문 근거로 대안을 생성하고 참조 무결성을 확인한다."""
    components = _idea_components(idea)
    claims_present = any(item.section == "claims" for item in evidence)
    level = (
        "claims_and_abstract"
        if claims_present and any(item.section == "abstract" for item in evidence)
        else (
            "claims_only"
            if claims_present
            else "abstract_only" if evidence else "insufficient"
        )
    )
    if not evidence:
        return PatentDesignAnalysis(
            status="insufficient_evidence",
            evidence_level="insufficient",
            technical_components=components,
            missing_information=["검색된 특허 근거가 없습니다."],
            limitations=[
                "검색 결과가 없다는 사실은 관련 특허가 없음을 의미하지 않습니다."
            ],
        )

    payload = {
        "idea": idea.model_dump(),
        "technical_components": [item.model_dump() for item in components],
        "patent_comparisons": [item.model_dump() for item in reviews],
        "overall_precheck": precheck.model_dump() if precheck else None,
        "patent_evidence": [item.model_dump() for item in evidence],
        "allowed_component_ids": [item.id for item in components],
        "allowed_patent_ids": list(dict.fromkeys(item.patent_id for item in evidence)),
        "allowed_citation_ids": [item.citation_id for item in evidence],
    }
    raw = llm_fn(
        PROMPT_PATH.read_text(encoding="utf-8"), json.dumps(payload, ensure_ascii=False)
    )
    raw_proposals = raw.get("proposals")
    if not isinstance(raw_proposals, list):
        raise ValueError("Design proposal response must contain a proposals list")

    allowed_components = set(payload["allowed_component_ids"])
    evidence_by_citation = {item.citation_id: item for item in evidence}
    allowed_patents = set(payload["allowed_patent_ids"])
    proposals: list[PatentDesignProposal] = []
    fingerprints = set()
    for row in raw_proposals[:3]:
        proposal = PatentDesignProposal.model_validate(row)
        if not set(proposal.target_component_ids) <= allowed_components:
            raise ValueError("Design proposal references unknown component")
        if not set(proposal.related_patent_ids) <= allowed_patents:
            raise ValueError("Design proposal references unknown patent")
        if not set(proposal.citation_ids) <= set(evidence_by_citation):
            raise ValueError("Design proposal references unknown citation")
        cited_patents = {
            evidence_by_citation[cid].patent_id for cid in proposal.citation_ids
        }
        if not cited_patents <= set(proposal.related_patent_ids):
            raise ValueError("Cited patent must be listed as related")
        if proposal.evidence_status == "grounded" and not proposal.citation_ids:
            raise ValueError("Grounded proposal requires at least one citation")
        if (
            proposal.evidence_status == "insufficient_evidence"
            and proposal.citation_ids
        ):
            raise ValueError("Insufficient-evidence proposal cannot cite evidence")
        fingerprint = " ".join(proposal.proposed_change.lower().split())
        if fingerprint in fingerprints:
            continue
        fingerprints.add(fingerprint)
        proposals.append(proposal)

    missing = []
    if level == "abstract_only":
        missing.append("청구항 원문을 확보하지 못해 초록 수준에서만 비교했습니다.")
    if not components:
        missing.append("아이디어에서 명시적 기술 구성요소를 확인하지 못했습니다.")
    limitations = [
        "제안은 초기 기술 검토이며 특허 침해·등록 가능성·실시 자유에 대한 법률 판단이 아닙니다."
    ]
    if any(not proposal.citation_ids for proposal in proposals):
        limitations.append("일부 대안은 검색 근거가 부족한 검증 전 가설입니다.")
    return PatentDesignAnalysis(
        status=(
            "success"
            if proposals and not missing
            else "partial" if proposals else "insufficient_evidence"
        ),
        evidence_level=level,
        technical_components=components,
        proposals=proposals,
        missing_information=missing,
        limitations=limitations,
    )
