"""Patent search, evidence, comparison, and report data contracts."""

import math
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from src.idea_schemas import StructuredIdea


# 2. 특허 검색 요청
class PatentSearchRequest(BaseModel):
    idea: StructuredIdea
    top_k: int = Field(default=8, ge=1, le=8)
    technology_area_id: str | None = None


# 3. 특허 청구항
class PatentClaim(BaseModel):
    claim_number: int = Field(ge=1)
    text: str = Field(min_length=1)
    claim_type: Literal["independent", "dependent", "unclassified"] = "unclassified"
    depends_on: list[int] = Field(default_factory=list)
    version_id: str | None = None


# 4. 정제된 특허 문서
class PatentDocument(BaseModel):
    patent_id: str
    title: str
    abstract: str
    claims: str = ""
    claim_items: list[PatentClaim] = Field(default_factory=list)
    claim_version_id: str | None = None

    application_number: str | None = None
    publication_number: str | None = None
    registration_number: str | None = None

    applicant: str | None = None
    ipc_codes: list[str] = Field(default_factory=list)
    cpc_codes: list[str] = Field(default_factory=list)
    application_date: str | None = None
    publication_date: str | None = None
    public_date: str | None = None

    source: str = "KIPRIS Plus"
    source_url: str | None = None
    representative_drawing_url: str | None = None
    representative_thumbnail_url: str | None = None
    representative_drawing_caption: str | None = None
    collected_at: str | None = None
    technology_area_ids: list[str] = Field(default_factory=list)


# 5. 임베딩 대상 청크
class PatentChunk(BaseModel):
    chunk_id: str
    patent_id: str
    section: Literal["abstract", "claims"]
    text: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    claim_number: int | None = Field(default=None, ge=1)
    claim_type: Literal["independent", "dependent", "unclassified"] | None = None
    depends_on: list[int] = Field(default_factory=list)
    version_id: str | None = None
    char_start: int | None = Field(default=None, ge=0)
    char_end: int | None = Field(default=None, ge=0)


# 6. 검색 근거
class PatentEvidence(BaseModel):
    citation_id: int = Field(ge=1)
    patent_id: str
    title: str

    section: Literal["abstract", "claims"]
    quote: str = Field(min_length=1)

    similarity: float | None = Field(default=None, ge=0, le=1)
    semantic_similarity: float | None = Field(default=None, ge=0, le=1)
    source_url: str | None = None
    representative_drawing_url: str | None = None
    representative_thumbnail_url: str | None = None
    representative_drawing_caption: str | None = None
    application_number: str | None = None
    publication_number: str | None = None
    application_date: str | None = None
    publication_date: str | None = None
    registration_number: str | None = None
    ipc_codes: list[str] = Field(default_factory=list)
    cpc_codes: list[str] = Field(default_factory=list)
    collected_at: str | None = None
    claim_number: int | None = Field(default=None, ge=1)
    claim_type: Literal["independent", "dependent", "unclassified"] | None = None
    depends_on: list[int] = Field(default_factory=list)
    version_id: str | None = None
    matched_queries: list[str] = Field(default_factory=list)
    matched_technical_elements: list[str] = Field(default_factory=list)
    matched_sections: list[Literal["abstract", "claims", "unknown"]] = Field(
        default_factory=list
    )
    retrieval_scopes: list[
        Literal[
            "technology_area",
            "global_index",
            "global_fallback",
            "kipris_supplement",
        ]
    ] = Field(default_factory=list)

    @field_validator("similarity", mode="before")
    @classmethod
    def normalize_similarity(cls, value):
        """검색 점수가 숫자·유한값·0~1 범위일 때만 보존한다."""
        if value is None:
            return None
        try:
            score = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(score) or not 0 <= score <= 1:
            return None
        return score

    @field_validator("semantic_similarity", mode="before")
    @classmethod
    def normalize_semantic_similarity(cls, value):
        """임베딩 cosine 점수는 유한한 0~1 값만 보존한다."""
        if value is None:
            return None
        try:
            score = float(value)
        except (TypeError, ValueError):
            return None
        if not math.isfinite(score) or not 0 <= score <= 1:
            return None
        return score


# 7. 기술 비교 결과
class PatentComparison(BaseModel):
    citation_id: int = Field(ge=1)
    similarity: str
    difference: str
    uncertainty: str
    technical_element: str | None = None


class PatentComponentComparison(BaseModel):
    component_id: str
    idea_component: str
    status: Literal["overlap", "partial", "different", "not_found", "uncertain"]
    citation_ids: list[int] = Field(default_factory=list)
    overlap: str = ""
    difference: str = ""
    uncertainty: str = ""
    matched_text: str = ""


class PatentWatchout(BaseModel):
    issue: str
    why_it_matters: str
    citation_ids: list[int] = Field(default_factory=list)
    next_check: str


class PatentDesignRecommendation(BaseModel):
    recommendation: str
    rationale: str
    citation_ids: list[int] = Field(default_factory=list)
    validation_needed: str = ""
    basis: Literal["evidence_based", "hypothesis"] = "hypothesis"

    @model_validator(mode="after")
    def validate_basis(self):
        if self.basis == "evidence_based" and not self.citation_ids:
            raise ValueError("Evidence-based design recommendations require citations")
        if self.basis == "hypothesis" and self.citation_ids:
            raise ValueError("Hypothesis recommendations must not claim citations")
        return self


class PatentDocumentReview(BaseModel):
    patent_id: str
    title: str
    citation_ids: list[int] = Field(default_factory=list)
    relevance: Literal["high", "medium", "low", "insufficient"] = "insufficient"
    relevance_reason: str = ""
    component_comparisons: list[PatentComponentComparison] = Field(default_factory=list)
    overall_summary: str = ""
    watchouts: list[str] = Field(default_factory=list)
    watchout_findings: list[PatentWatchout] = Field(default_factory=list)
    design_recommendations: list[PatentDesignRecommendation] = Field(
        default_factory=list
    )
    unknowns: list[str] = Field(default_factory=list)

    @field_validator("relevance_reason", mode="before")
    @classmethod
    def normalize_relevance_reason(cls, value):
        """모델·저장 데이터의 결측 및 비유한 관련성 이유를 빈 값으로 정규화한다."""
        if value is None:
            return ""
        if isinstance(value, (int, float)):
            if not math.isfinite(float(value)):
                return ""
            value = str(value)
        if not isinstance(value, str):
            return ""
        cleaned = value.strip()
        if cleaned.casefold() in {"", "nan", "none", "null"}:
            return ""
        return cleaned


class PatentabilityPrecheck(BaseModel):
    status: Literal["overlap_concern", "potentially_distinct", "insufficient_evidence"]
    summary: str
    citation_ids: list[int] = Field(default_factory=list)
    distinction_hypotheses: list[str] = Field(default_factory=list)
    expert_questions: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    common_watchouts: list[PatentWatchout] = Field(default_factory=list)
    common_design_recommendations: list[PatentDesignRecommendation] = Field(
        default_factory=list
    )


class PatentTechnicalComponent(BaseModel):
    id: str
    name: str
    description: str
    source_type: Literal["user_stated", "derived"] = "user_stated"


class ProposalVerificationPlan(BaseModel):
    method: str
    metrics: list[str] = Field(default_factory=list)
    success_criteria: str


class PatentDesignProposal(BaseModel):
    proposal_id: str
    title: str
    target_component_ids: list[str] = Field(min_length=1)
    problem: str
    proposed_change: str
    implementation_approach: list[str] = Field(min_length=1)
    technical_difference: str
    expected_benefits: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)
    feasibility: Literal["low", "medium", "high", "unknown"] = "unknown"
    related_patent_ids: list[str] = Field(default_factory=list)
    citation_ids: list[int] = Field(default_factory=list)
    evidence_status: Literal["grounded", "insufficient_evidence"] = "grounded"
    verification_plan: ProposalVerificationPlan
    patent_verification_required: bool = True

    @model_validator(mode="after")
    def validate_evidence_status(self):
        if self.evidence_status == "grounded" and not self.citation_ids:
            raise ValueError("Grounded design proposals require citations")
        if self.evidence_status == "insufficient_evidence" and self.citation_ids:
            raise ValueError("Insufficient-evidence proposals cannot cite evidence")
        return self


class PatentDesignAnalysis(BaseModel):
    status: Literal["success", "partial", "insufficient_evidence", "failed"]
    evidence_level: Literal[
        "claims_and_abstract", "claims_only", "abstract_only", "insufficient"
    ]
    technical_components: list[PatentTechnicalComponent] = Field(default_factory=list)
    proposals: list[PatentDesignProposal] = Field(default_factory=list, max_length=3)
    missing_information: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class PatentStatisticItem(BaseModel):
    label: str
    count: int = Field(ge=0)


class PatentTrendStatistics(BaseModel):
    scope: str
    total_patents: int = Field(ge=0)
    ipc_coverage: int = Field(default=0, ge=0)
    cpc_coverage: int = Field(default=0, ge=0)
    application_date_coverage: int = Field(default=0, ge=0)
    applicant_coverage: int = Field(default=0, ge=0)
    ipc_distribution: list[PatentStatisticItem] = Field(default_factory=list)
    cpc_distribution: list[PatentStatisticItem] = Field(default_factory=list)
    yearly_applications: list[PatentStatisticItem] = Field(default_factory=list)
    top_applicants: list[PatentStatisticItem] = Field(default_factory=list)
    data_as_of: str | None = None


# 8. 최종 특허 RAG 결과
class PatentReport(BaseModel):
    status: Literal["completed", "partial", "no_results", "error"]

    evidence: list[PatentEvidence] = Field(default_factory=list)
    comparisons: list[PatentComparison] = Field(default_factory=list)
    patent_reviews: list[PatentDocumentReview] = Field(default_factory=list)
    patentability_precheck: PatentabilityPrecheck | None = None
    design_analysis: PatentDesignAnalysis | None = None
    indexed_statistics: PatentTrendStatistics | None = None
    related_statistics: PatentTrendStatistics | None = None
    unknowns: list[str] = Field(default_factory=list)

    search_scope: str
    error_message: str | None = None
    semantic_similarity_model: str | None = None

    @model_validator(mode="after")
    def validate_citations(self):
        ids = [e.citation_id for e in self.evidence]

        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate citation IDs")

        for comparison in self.comparisons:
            if comparison.citation_id not in ids:
                raise ValueError("Comparison references unknown citation")

        evidence_by_patent = {}
        for item in self.evidence:
            evidence_by_patent.setdefault(item.patent_id, set()).add(item.citation_id)
        reviewed = set()
        for review in self.patent_reviews:
            if review.patent_id in reviewed:
                raise ValueError("Duplicate patent reviews")
            reviewed.add(review.patent_id)
            allowed = evidence_by_patent.get(review.patent_id, set())
            if not set(review.citation_ids) <= allowed:
                raise ValueError("Patent review references unknown citation")
            for comparison in review.component_comparisons:
                if not set(comparison.citation_ids) <= allowed:
                    raise ValueError("Component comparison references unknown citation")
                if comparison.matched_text and not any(
                    comparison.matched_text in item.quote
                    for item in self.evidence
                    if item.citation_id in comparison.citation_ids
                ):
                    raise ValueError(
                        "Matched patent text must be verbatim cited evidence"
                    )
            for recommendation in review.design_recommendations:
                if not set(recommendation.citation_ids) <= allowed:
                    raise ValueError(
                        "Design recommendation references unknown citation"
                    )
            for watchout in review.watchout_findings:
                if not set(watchout.citation_ids) <= allowed:
                    raise ValueError("Patent watchout references unknown citation")
        if self.patentability_precheck and not set(
            self.patentability_precheck.citation_ids
        ) <= set(ids):
            raise ValueError("Patentability precheck references unknown citation")
        if self.patentability_precheck:
            for watchout in self.patentability_precheck.common_watchouts:
                if not set(watchout.citation_ids) <= set(ids):
                    raise ValueError(
                        "Common patent watchout references unknown citation"
                    )
            for (
                recommendation
            ) in self.patentability_precheck.common_design_recommendations:
                if not set(recommendation.citation_ids) <= set(ids):
                    raise ValueError(
                        "Common patent recommendation references unknown citation"
                    )

        if self.design_analysis:
            component_ids = {
                item.id for item in self.design_analysis.technical_components
            }
            patent_ids = {item.patent_id for item in self.evidence}
            for proposal in self.design_analysis.proposals:
                if not set(proposal.target_component_ids) <= component_ids:
                    raise ValueError("Design proposal references unknown component")
                if not set(proposal.related_patent_ids) <= patent_ids:
                    raise ValueError("Design proposal references unknown patent")
                if not set(proposal.citation_ids) <= set(ids):
                    raise ValueError("Design proposal references unknown citation")
                if proposal.evidence_status == "grounded" and not proposal.citation_ids:
                    raise ValueError("Grounded design proposals require citations")
                citation_patents = {
                    item.patent_id
                    for item in self.evidence
                    if item.citation_id in proposal.citation_ids
                }
                if not citation_patents <= set(proposal.related_patent_ids):
                    raise ValueError("Cited patents must be listed as related patents")

        if len({e.patent_id for e in self.evidence}) > 8:
            raise ValueError("Maximum 8 unique patents")

        return self


# ──────────────────────────────────────────────
