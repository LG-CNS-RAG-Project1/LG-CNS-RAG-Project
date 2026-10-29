import re
from typing import Literal
from pydantic import BaseModel, Field, model_validator


# 1. 사용자 아이디어
class StructuredIdea(BaseModel):
    title: str
    problem: str
    technology: str
    customers: str = ""
    difference: str = ""
    revenue: str = ""
    technical_components: list[str] = Field(default_factory=list)
    current_alternative: str = ""
    target_segment: str = ""
    value_hypotheses: list[str] = Field(default_factory=list)
    field_sources: dict[str, str] = Field(default_factory=dict)


IdeaField = Literal["problem", "technology", "customers", "difference", "revenue"]
FieldSource = Literal[
    "extracted",  # 입력 문장에서 LLM이 추출
    "user_answer",  # 재질문에 사용자가 직접 답변
    "ai_hypothesis",  # AI가 분석용 가설로 제안
    "unknown",  # 사용자가 모름으로 답했거나 재질문 상한까지 비어 있음
]

IDEA_FIELDS: list[IdeaField] = [
    "problem",
    "technology",
    "customers",
    "difference",
    "revenue",
]


# 1-1. 구조화 중인 아이디어 (빈 항목 재질문 단계)
class IdeaDraft(BaseModel):
    original_text: str = Field(min_length=1)
    title: str = ""
    problem: str = ""
    technology: str = ""
    customers: str = ""
    difference: str = ""
    revenue: str = ""

    field_sources: dict[str, FieldSource] = Field(default_factory=dict)
    current_alternative: str = ""
    target_segment: str = ""
    technical_components: list[str] = Field(default_factory=list)
    value_hypotheses: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    status: Literal["needs_input", "complete", "rejected"] = "needs_input"
    missing_fields: list[IdeaField] = Field(default_factory=list)
    questions: dict[IdeaField, str] = Field(default_factory=dict)
    rounds: int = Field(default=0, ge=0)  # 재질문에 답한 횟수

    # 입력 검사 결과: off_topic(주제 이탈), unsafe(프롬프트 조작·유해 목적)이면 rejected
    input_status: Literal["ok", "off_topic", "unsafe"] = "ok"
    rejection_reason: str | None = None  # 사용자에게 보여 줄 거절 안내

    @model_validator(mode="after")
    def validate_draft(self):
        if self.status == "complete" and self.missing_fields:
            raise ValueError("complete draft must not have missing fields")
        if self.status == "needs_input" and not self.missing_fields:
            raise ValueError("needs_input draft requires missing fields")
        if (self.status == "rejected") != (self.input_status != "ok"):
            raise ValueError("rejected status must match a non-ok input_status")
        if self.status == "rejected" and not self.rejection_reason:
            raise ValueError("rejected draft requires rejection_reason")
        return self

    @property
    def unknown_fields(self) -> list[IdeaField]:
        """모름으로 확정된 항목. 해당 항목에 기대는 시장 차원은 미확인으로 판정한다."""
        return [f for f in IDEA_FIELDS if self.field_sources.get(f) == "unknown"]

    def to_structured_idea(self) -> StructuredIdea:
        """완성된 초안을 특허·시장 공통 입력으로 변환한다. 모름 항목은 빈 문자열로 남는다."""
        if self.status != "complete":
            raise ValueError(f"idea draft is incomplete: {self.missing_fields}")
        required = ["title", *IDEA_FIELDS]
        missing = [field for field in required if not str(getattr(self, field)).strip()]
        if missing:
            raise ValueError("분석 필수 항목이 비어 있습니다: " + ", ".join(missing))
        return StructuredIdea(
            title=self.title,
            **{field: getattr(self, field) for field in IDEA_FIELDS},
            current_alternative=self.current_alternative,
            target_segment=self.target_segment,
            technical_components=self.technical_components,
            value_hypotheses=self.value_hypotheses,
            field_sources=self.field_sources,
        )


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
    source_url: str | None = None
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
# 시장 근거 스키마
# ──────────────────────────────────────────────

MarketSourceType = Literal[
    "dart",  # DART 공시
    "news",  # 언론 기사
    "press_release",  # 기업 보도자료·IR
    "public_stats",  # 공공 통계·정부 자료
    "procurement",  # 조달·지원사업 공고
    "research_report",  # 산업·연구기관 보고서
    "customer_validation",  # 고객 검증 자료(인터뷰·설문·파일럿·LOI)
]
MarketDimension = Literal["demand", "competition", "price", "buyer", "adoption_barrier"]
EvidenceNature = Literal[
    "direct_demand",  # 고객의 구매·지불 의사를 직접 보여줌
    "purchase_signal",  # 조달·구매 요건 등 구매 신호
    "indirect_demand",  # 보급 현황 등 간접 수요 신호
    "business_signal",  # 기업 투자·출시·제휴·정책 등 사업 신호
    "estimate",  # 시장 규모 등 추정치
    "company_claim",  # 기업 자체 주장
]
Grade = Literal["high", "medium", "low"]
MarketVerdict = Literal["confirmed", "signal_only", "unverified"]
ClaimType = Literal["fact", "user_claim", "ai_hypothesis"]

ALL_DIMENSIONS: list[MarketDimension] = [
    "demand",
    "competition",
    "price",
    "buyer",
    "adoption_barrier",
]


def _check_yyyymmdd(value: int | None, field_name: str) -> None:
    """YYYYMMDD 정수 형식의 날짜인지 확인한다."""
    if value is None:
        return
    from datetime import datetime

    try:
        datetime.strptime(str(value), "%Y%m%d")
    except ValueError:
        raise ValueError(f"{field_name} must be YYYYMMDD integer")


# 8. 시장 근거 검색 요청
class MarketSearchRequest(BaseModel):
    idea: StructuredIdea
    dimensions: list[MarketDimension] = Field(
        default_factory=lambda: list(ALL_DIMENSIONS)
    )
    source_types: list[MarketSourceType] | None = None
    date_from: int | None = None
    top_k: int = Field(default=5, ge=1, le=5)

    @model_validator(mode="after")
    def validate_date(self):
        _check_yyyymmdd(self.date_from, "date_from")
        return self


# 9. 정제된 시장 자료 (출처 원장 1행)
class MarketDocument(BaseModel):
    source_id: str = Field(min_length=1)
    source_type: MarketSourceType
    title: str
    publisher: str
    text: str = Field(min_length=1)

    url: str | None = None
    published_at: int  # 발행일 YYYYMMDD
    period: str | None = None  # 회계기간·조사 기준연도 (예: FY2025)
    collected_at: int  # 수집일 YYYYMMDD
    region: Literal["domestic", "overseas", "global"] = "domestic"
    lang: str = "ko"
    section: str | None = None  # 원문 위치 (페이지·섹션·문단)

    reliability: Grade
    evidence_nature: EvidenceNature
    dup_group: str | None = None  # 같은 사건을 다룬 기사 묶음
    license: str | None = None  # 저장·가공·공유 조건
    idea_ids: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_document(self):
        _check_yyyymmdd(self.published_at, "published_at")
        _check_yyyymmdd(self.collected_at, "collected_at")
        if self.collected_at < self.published_at:
            raise ValueError("collected_at is earlier than published_at")
        if (
            self.evidence_nature == "direct_demand"
            and self.source_type != "customer_validation"
        ):
            raise ValueError(
                "direct_demand is only allowed for customer_validation sources"
            )
        return self

    def to_chroma_metadata(self) -> dict:
        """Chroma 메타데이터 형식(str·int·float·bool)으로 변환한다. text와 None 값은 제외한다."""
        data = self.model_dump(exclude={"text"})
        data["idea_ids"] = ",".join(self.idea_ids)
        return {k: v for k, v in data.items() if v is not None and v != ""}


# 10. 임베딩 대상 시장 청크
class MarketChunk(BaseModel):
    chunk_id: str  # "{source_id}#{chunk_index}"
    source_id: str
    text: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    section: str | None = None


# 11. 시장 검색 근거
class MarketEvidence(BaseModel):
    citation_id: int = Field(ge=1)
    source_id: str
    source_type: MarketSourceType
    title: str
    publisher: str

    quote: str = Field(min_length=1)
    section: str | None = None
    url: str | None = None
    published_at: int
    period: str | None = None

    reliability: Grade
    recency: Grade
    directness: Grade
    evidence_nature: EvidenceNature

    similarity: float | None = Field(default=None, ge=0, le=1)


# 12. 차원별 시장 주장
class MarketClaim(BaseModel):
    statement: str = Field(min_length=1)
    claim_type: ClaimType
    citation_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_claim(self):
        if self.claim_type == "fact" and not self.citation_ids:
            raise ValueError("fact claims require at least one citation")
        return self


# 13. 차원별 판정 결과
class MarketDimensionResult(BaseModel):
    dimension: MarketDimension
    verdict: MarketVerdict
    claims: list[MarketClaim] = Field(default_factory=list, max_length=3)
    next_check: str | None = None  # 미확인일 때 다음 검증 과제
    # 검색·관련성 판정 결과: sufficient·limited·insufficient·no_results·error
    evidence_status: (
        Literal["sufficient", "limited", "insufficient", "no_results", "error"] | None
    ) = None
    relevant_count: int | None = None  # 관련 판정된 검색 결과 수
    limitation: str | None = (
        None  # 확인됨이 아닌 이유 (자료 없음·판정 실패·사업 신호만 등)
    )

    @model_validator(mode="after")
    def validate_verdict(self):
        cited = [c for c in self.claims if c.citation_ids]
        if self.verdict in ("confirmed", "signal_only") and not cited:
            raise ValueError(
                f"{self.dimension}: verdict '{self.verdict}' requires cited claims"
            )
        if self.verdict == "unverified" and not self.next_check:
            raise ValueError(f"{self.dimension}: unverified result requires next_check")
        return self


class MarketValidationAction(BaseModel):
    title: str
    target: str
    method: str
    success_signal: str
    citation_ids: list[int] = Field(default_factory=list)


class MarketOpportunityFinding(BaseModel):
    topic: str
    statement: str
    citation_ids: list[int] = Field(default_factory=list)


class MarketOpportunityReview(BaseModel):
    status: Literal[
        "validated_demand", "buyer_signals", "indirect_signals", "insufficient_evidence"
    ]
    target_segment: str = ""
    value_hypotheses: list[str] = Field(default_factory=list)
    reasons: list[MarketOpportunityFinding] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    validation_actions: list[MarketValidationAction] = Field(default_factory=list)


class MarketAnalyticalHypothesis(BaseModel):
    """검색 사실과 구분해 검증할 시장 가설을 기록한다."""

    question: str
    hypothesis: str
    basis: str
    assumptions: list[str] = Field(default_factory=list)
    citation_ids: list[int] = Field(default_factory=list)
    validation_target: str
    validation_method: str
    success_criterion: str
    numeric_value: float | None = None
    numeric_unit: str = ""
    numeric_basis: str = ""

    @model_validator(mode="after")
    def require_basis_for_numeric_estimate(self):
        if self.numeric_value is not None and not self.numeric_basis.strip():
            raise ValueError("Numeric market hypotheses require a stated basis")
        return self


class MarketCommercialAnalysis(BaseModel):
    """사업 승인 관점의 고객·구매 구조 분석. 문장은 근거 또는 가설로 구분한다."""

    user: str = "미확인"
    buyer: str = "미확인"
    budget_owner: str = "미확인"
    use_case: str = "미확인"
    current_alternative: str = "미확인"
    switching_trigger: str = "미확인"
    purchase_process: str = "미확인"
    adoption_requirements: list[str] = Field(default_factory=list)
    pricing_hypothesis: str = "미확인"
    critical_assumptions: list[str] = Field(default_factory=list)
    citation_ids: list[int] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    hypotheses: list[MarketAnalyticalHypothesis] = Field(default_factory=list)


class ImplementationCostItem(BaseModel):
    name: str
    quantity: float = Field(ge=0)
    unit: str
    low_unit_cost: float = Field(ge=0)
    base_unit_cost: float = Field(ge=0)
    high_unit_cost: float = Field(ge=0)
    basis: str
    citation_ids: list[int] = Field(default_factory=list)
    cost_type: Literal["one_time", "monthly", "annual"] = "one_time"

    @model_validator(mode="after")
    def validate_range(self):
        if not self.low_unit_cost <= self.base_unit_cost <= self.high_unit_cost:
            raise ValueError("Cost range must be low <= base <= high")
        return self


class ImplementationCostEstimate(BaseModel):
    status: Literal["estimated", "insufficient_data", "error"] = "insufficient_data"
    region: str = "대한민국"
    currency: str = "KRW"
    unit: str = "원"
    as_of: str = "미확인"
    items: list[ImplementationCostItem] = Field(default_factory=list)
    omissions: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    revenue_unit_price: float | None = Field(default=None, ge=0)
    variable_cost_per_unit: float | None = Field(default=None, ge=0)
    revenue_basis: str = ""
    unknowns: list[str] = Field(default_factory=list)


class CostScenarioTotals(BaseModel):
    initial_low: float = 0
    initial_base: float = 0
    initial_high: float = 0
    recurring_monthly_low: float = 0
    recurring_monthly_base: float = 0
    recurring_monthly_high: float = 0
    break_even_units_low: int | None = None
    break_even_units_base: int | None = None
    break_even_units_high: int | None = None
    calculation_note: str = ""


class MarketTrendPoint(BaseModel):
    period: str  # YYYY-MM
    theme_ratio: float  # 같은 요청 안 최댓값을 100으로 둔 아이디어 주제어 검색량
    reference_ratio: float  # 같은 요청 안 기준 주제어(스마트공장) 검색량
    relative_index: float | None = (
        None  # theme_ratio / reference_ratio × 100, 기준이 0이면 None
    )


class MarketSearchTrend(BaseModel):
    """네이버 검색어 트렌드로 본 아이디어 주제어의 월별 관심도 (시장 규모·수요 근거가 아님)."""

    status: Literal["completed", "insufficient_volume", "error"]
    keywords: list[str] = Field(default_factory=list)
    reference_keywords: list[str] = Field(default_factory=list)
    points: list[MarketTrendPoint] = Field(default_factory=list)
    # 최근 N개월 평균 relative_index의 직전 N개월 대비 변화율(%)
    recent_change_pct: float | None = None
    direction: Literal["rising", "stable", "cooling", "unknown"] = "unknown"
    note: str = ""
    error_message: str | None = None


class MarketKeywordNode(BaseModel):
    term: str
    document_count: int  # 이 명사가 나온 기사 수
    cluster: int  # 키워드 묶음 번호 (0부터, 큰 묶음 순)
    x: float  # 화면 배치 좌표 (-1~1)
    y: float


class MarketKeywordEdge(BaseModel):
    source: str
    target: str
    weight: int  # 두 명사가 함께 나온 기사 수


class MarketKeywordNetwork(BaseModel):
    """아이디어와 가까운 뉴스 제목·요약에서 함께 나온 명사의 연결망 (시장 수요·인과 근거가 아님)."""

    status: Literal["completed", "insufficient", "error"]
    document_count: int = 0  # 분석한 기사 수
    nodes: list[MarketKeywordNode] = Field(default_factory=list)
    edges: list[MarketKeywordEdge] = Field(default_factory=list)
    # 묶음별 대표 명사 (자주 나온 순, 묶음 번호 순)
    clusters: list[list[str]] = Field(default_factory=list)
    note: str = ""
    error_message: str | None = None


class ProcurementNotice(BaseModel):
    """나라장터 입찰공고 1건 (담당자 개인정보는 담지 않는다)."""

    notice_no: str  # 공고번호-차수
    title: str
    buyer: str  # 수요기관
    buyer_type: str  # 민간 기업·대학·학교·연구기관·공공기관
    kind: Literal["물품", "용역"]
    notice_date: int  # 공고일 YYYYMMDD
    budget: int | None = None  # 배정예산(원), 없으면 추정가격
    product: str = ""  # 세부품명
    contract_method: str = ""  # 계약체결방법·낙찰방법
    url: str = ""


class MarketProcurement(BaseModel):
    """아이디어 주제어로 찾은 공공 조달 입찰공고 (공공 구매 사례이며 민간 고객 수요의 근거가 아님)."""

    status: Literal["completed", "no_keywords", "error"]
    keywords: list[str] = Field(default_factory=list)
    period: str = ""  # 조회 기간 'YYYY-MM ~ YYYY-MM'
    searched_count: int = 0  # 주제어로 찾은 공고 수 (중복 제외, 관련성 판정 전)
    notices: list[ProcurementNotice] = Field(default_factory=list)  # 관련 판정 공고
    note: str = ""
    error_message: str | None = None


# 14. 최종 시장 근거 결과
class MarketReport(BaseModel):
    status: Literal["completed", "no_results", "error"]

    dimensions: list[MarketDimensionResult] = Field(default_factory=list)
    evidence: list[MarketEvidence] = Field(default_factory=list)
    opportunity_review: MarketOpportunityReview | None = None
    commercial_analysis: MarketCommercialAnalysis | None = None
    search_trend: MarketSearchTrend | None = None
    keyword_network: MarketKeywordNetwork | None = None
    procurement: MarketProcurement | None = None
    unknowns: list[str] = Field(default_factory=list)

    search_scope: str
    data_as_of: int | None = None  # 분석 기준일 YYYYMMDD
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_report(self):
        _check_yyyymmdd(self.data_as_of, "data_as_of")

        ids = [e.citation_id for e in self.evidence]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate citation IDs")

        dims = [d.dimension for d in self.dimensions]
        if len(dims) != len(set(dims)):
            raise ValueError("Duplicate market dimensions")

        by_id = {e.citation_id: e for e in self.evidence}
        for d in self.dimensions:
            for claim in d.claims:
                for cid in claim.citation_ids:
                    if cid not in by_id:
                        raise ValueError("Claim references unknown citation")

            # 수요 '확인'은 직접 수요 근거(고객 검증 자료)가 있어야 한다
            if d.dimension == "demand" and d.verdict == "confirmed":
                cited = {cid for c in d.claims for cid in c.citation_ids}
                if not any(
                    by_id[cid].evidence_nature == "direct_demand" for cid in cited
                ):
                    raise ValueError(
                        "demand 'confirmed' requires direct_demand evidence"
                    )

        if self.opportunity_review:
            for finding in self.opportunity_review.reasons:
                if not set(finding.citation_ids) <= set(ids):
                    raise ValueError(
                        "Market opportunity finding references unknown citation"
                    )
            for action in self.opportunity_review.validation_actions:
                if not set(action.citation_ids) <= set(ids):
                    raise ValueError(
                        "Market validation action references unknown citation"
                    )

        if self.commercial_analysis and not set(
            self.commercial_analysis.citation_ids
        ) <= set(ids):
            raise ValueError("Commercial analysis references unknown citation")
        if self.commercial_analysis:
            for hypothesis in self.commercial_analysis.hypotheses:
                if not set(hypothesis.citation_ids) <= set(ids):
                    raise ValueError("Market hypothesis references unknown citation")
                if hypothesis.numeric_value is not None:
                    if not hypothesis.citation_ids:
                        raise ValueError(
                            "Numeric market hypotheses require cited source data"
                        )
                    numeric_token = f"{hypothesis.numeric_value:g}"
                    normalized_value = numeric_token.replace(",", "")
                    cited_quotes = [
                        by_id[cid].quote
                        for cid in hypothesis.citation_ids
                        if cid in by_id
                    ]
                    if not any(
                        re.search(
                            rf"(?<!\d){re.escape(normalized_value)}(?!\d)",
                            re.sub(r"(?<=\d),(?=\d)", "", quote).replace(" ", ""),
                        )
                        for quote in cited_quotes
                    ):
                        raise ValueError(
                            "Numeric market hypotheses must match a cited source value"
                        )

        if self.status == "no_results" and self.evidence:
            raise ValueError("no_results report must not contain evidence")
        if self.status == "error" and not self.error_message:
            raise ValueError("error report requires error_message")

        return self
