"""Patent search, evidence, comparison, and report data contracts."""

import math
from typing import Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from src.idea_schemas import StructuredIdea


# 2. 특허 검색 요청
class PatentSearchRequest(BaseModel):
    """특허 검색에 사용할 아이디어와 결과 수·분야 범위."""

    idea: StructuredIdea
    top_k: int = Field(default=8, ge=1, le=8)
    technology_area_id: str | None = None


# 3. 특허 청구항
class PatentClaim(BaseModel):
    """청구항 번호·문구·종속 관계를 보존한 데이터."""

    claim_number: int = Field(ge=1)
    text: str = Field(min_length=1)
    claim_type: Literal["independent", "dependent", "unclassified"] = "unclassified"
    depends_on: list[int] = Field(default_factory=list)
    version_id: str | None = None


# 4. 정제된 특허 문서
class PatentDocument(BaseModel):
    """출처와 분류 메타데이터를 포함한 정제 특허 문헌."""

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
    """색인할 특허 청크와 원문·청구항 내 위치 정보."""

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
    """특허 보고서에서 추적할 수 있는 인용 발췌와 검색 정보."""

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
    """아이디어와 특허 문헌의 기술 구성을 비교한 결과."""

    citation_id: int = Field(ge=1)
    similarity: str
    difference: str
    uncertainty: str
    technical_element: str | None = None


class PatentComponentComparison(BaseModel):
    """아이디어의 한 기술 요소와 문헌 근거·차이를 연결한 비교."""

    component_id: str
    idea_component: str
    status: Literal["overlap", "partial", "different", "not_found", "uncertain"]
    citation_ids: list[int] = Field(default_factory=list)
    overlap: str = ""
    difference: str = ""
    uncertainty: str = ""
    matched_text: str = ""


class PatentWatchout(BaseModel):
    """특허 문헌을 검토할 때 확인할 쟁점과 다음 확인 방법."""

    issue: str
    why_it_matters: str
    citation_ids: list[int] = Field(default_factory=list)
    next_check: str


class PatentDesignRecommendation(BaseModel):
    """기술 설계 대안과 근거 성격·후속 검증 항목."""

    recommendation: str
    rationale: str
    citation_ids: list[int] = Field(default_factory=list)
    validation_needed: str = ""
    basis: Literal["evidence_based", "hypothesis"] = "hypothesis"

    @model_validator(mode="after")
    def validate_basis(self):
        """근거 기반 설계 제안이 인용 근거를 갖는지 확인한다."""
        if self.basis == "evidence_based" and not self.citation_ids:
            raise ValueError("Evidence-based design recommendations require citations")
        if self.basis == "hypothesis" and self.citation_ids:
            raise ValueError("Hypothesis recommendations must not claim citations")
        return self


class PatentDocumentReview(BaseModel):
    """문헌별 관련성, 구성 비교, 주의점의 종합 검토."""

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
    """법률 판단이 아닌 특허 선행조사의 예비 검토와 한계."""

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
    """아이디어에서 추출한 검색 대상 기술 구성요소."""

    id: str
    name: str
    description: str
    source_type: Literal["user_stated", "derived"] = "user_stated"


class ProposalVerificationPlan(BaseModel):
    """설계 대안을 실험·현장 확인으로 검증하는 계획."""

    method: str
    metrics: list[str] = Field(default_factory=list)
    success_criteria: str


class PatentDesignProposal(BaseModel):
    """기존 문헌과의 차이를 검토하기 위한 구체적 설계 제안."""

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
        """설계 제안의 근거 상태와 인용 ID 사용이 일치하는지 검사한다."""
        if self.evidence_status == "grounded" and not self.citation_ids:
            raise ValueError("Grounded design proposals require citations")
        if self.evidence_status == "insufficient_evidence" and self.citation_ids:
            raise ValueError("Insufficient-evidence proposals cannot cite evidence")
        return self


class PatentDesignAnalysis(BaseModel):
    """특허 비교에서 파생된 설계 제안과 검증 계획."""

    status: Literal["success", "partial", "insufficient_evidence", "failed"]
    evidence_level: Literal[
        "claims_and_abstract", "claims_only", "abstract_only", "insufficient"
    ]
    technical_components: list[PatentTechnicalComponent] = Field(default_factory=list)
    proposals: list[PatentDesignProposal] = Field(default_factory=list, max_length=3)
    missing_information: list[str] = Field(default_factory=list)
    limitations: list[str] = Field(default_factory=list)


class PatentStatisticItem(BaseModel):
    """특허 통계의 한 분류 항목과 집계 값."""

    label: str
    count: int = Field(ge=0)


class PatentTrendStatistics(BaseModel):
    """보유 색인 범위에 한정된 특허 연도·분류 통계."""

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
    """특허 검색 결과와 인용·검토·부분 실행 상태를 담는 보고서."""

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
        """특허 보고서 내부의 모든 인용 ID가 실제 근거를 가리키는지 확인한다."""
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
