"""아이디어 분석의 입력, 문서, 근거, 보고서 간 공유 데이터 계약을 정의한다.

수집 원문에서 만들어진 문서·청크부터 검색 근거와 최종 보고서까지 같은
식별자와 상태 의미를 유지하도록 Pydantic 모델과 검증 규칙을 모아 둔다.
"""

import math
import re
from typing import Literal
from pydantic import BaseModel, Field, field_validator, model_validator


# 1. 사용자 아이디어
class StructuredIdea(BaseModel):
    """사용자가 검토를 마친 특허·시장 분석용 아이디어."""

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
    """초안 작성 중인 값, 항목별 출처, 미확인 상태와 추가 질문."""

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
        """추가 질문·완료·거절 상태가 입력 필드와 맞는지 검사한다."""
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
    """선택 날짜 값이 유효한 YYYYMMDD 정수인지 검증한다."""
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
    """시장 자료 검색 질의와 아이디어·자료 범위."""

    idea: StructuredIdea
    dimensions: list[MarketDimension] = Field(
        default_factory=lambda: list(ALL_DIMENSIONS)
    )
    source_types: list[MarketSourceType] | None = None
    date_from: int | None = None
    top_k: int = Field(default=5, ge=1, le=5)

    @model_validator(mode="after")
    def validate_date(self):
        """시장 검색 시작일이 실제 달력 날짜인지 확인한다."""
        _check_yyyymmdd(self.date_from, "date_from")
        return self


# 9. 정제된 시장 자료 (출처 원장 1행)
class MarketDocument(BaseModel):
    """뉴스·공시 등 시장 자료의 원문 출처와 근거 성격."""

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
        """시장 문서의 날짜 순서와 출처별 근거 성격을 검증한다."""
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
    """시장 문서에서 분리한 검색 단위와 문서 위치."""

    chunk_id: str  # "{source_id}#{chunk_index}"
    source_id: str
    text: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)
    section: str | None = None


# 11. 시장 검색 근거
class MarketEvidence(BaseModel):
    """시장 분석에 인용할 수 있는 문구와 출처 정보."""

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
    """시장 분석의 주장과 이를 뒷받침하는 인용 ID."""

    statement: str = Field(min_length=1)
    claim_type: ClaimType
    citation_ids: list[int] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_claim(self):
        """주장의 인용 ID와 근거 성격 조합이 허용되는지 검사한다."""
        if self.claim_type == "fact" and not self.citation_ids:
            raise ValueError("fact claims require at least one citation")
        return self


# 13. 차원별 판정 결과
class MarketDimensionResult(BaseModel):
    """수요·경쟁 등 한 차원의 근거, 판정, 제한 사항."""

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
        """판정에 인용 주장과 미확인 시 다음 행동이 있는지 확인한다."""
        cited = [c for c in self.claims if c.citation_ids]
        if self.verdict in ("confirmed", "signal_only") and not cited:
            raise ValueError(
                f"{self.dimension}: verdict '{self.verdict}' requires cited claims"
            )
        if self.verdict == "unverified" and not self.next_check:
            raise ValueError(f"{self.dimension}: unverified result requires next_check")
        return self


class MarketValidationAction(BaseModel):
    """보고서가 제안하는 다음 고객·시장 검증 행동."""

    title: str
    target: str
    method: str
    success_signal: str
    citation_ids: list[int] = Field(default_factory=list)


class MarketOpportunityFinding(BaseModel):
    """시장 기회 검토에서 근거·가설과 검증 필요성을 묶은 항목."""

    topic: str
    statement: str
    citation_ids: list[int] = Field(default_factory=list)


class MarketOpportunityReview(BaseModel):
    """시장 기회 판단과 남아 있는 전제·한계."""

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
        """비용 수치에 근거·산식 또는 가정 설명을 요구한다."""
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
    """구현 비용 항목의 수량·단가·범위·출처."""

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
        """비용 범위에서 낮음 ≤ 기준 ≤ 높음 순서를 지키는지 검사한다."""
        if not self.low_unit_cost <= self.base_unit_cost <= self.high_unit_cost:
            raise ValueError("Cost range must be low <= base <= high")
        return self


class ImplementationCostEstimate(BaseModel):
    """근거와 가정을 구분해 기록하는 구현 비용 추정."""

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
    """비용 항목을 산식으로 합산한 시나리오별 결과."""

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
    """기준 검색어에 대한 월별 상대 검색 관심도."""

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
    # 검색량이 적어 상위 범주 주제어(keywords)로 다시 조회했을 때의 원래 주제어
    fallback_from: list[str] = Field(default_factory=list)
    reference_keywords: list[str] = Field(default_factory=list)
    points: list[MarketTrendPoint] = Field(default_factory=list)
    # 최근 N개월 평균 relative_index의 직전 N개월 대비 변화율(%)
    recent_change_pct: float | None = None
    direction: Literal["rising", "stable", "cooling", "unknown"] = "unknown"
    note: str = ""
    error_message: str | None = None


class MarketKeywordNode(BaseModel):
    """뉴스 동시 출현 네트워크에 표시할 키워드."""

    term: str
    document_count: int  # 이 명사가 나온 기사 수
    cluster: int  # 키워드 묶음 번호 (0부터, 큰 묶음 순)
    x: float  # 화면 배치 좌표 (-1~1)
    y: float


class MarketKeywordEdge(BaseModel):
    """같은 기사에서 함께 등장한 키워드 쌍."""

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


class DartFinancialYear(BaseModel):
    """사업연도 1개의 주요 재무 계정(원). 공시에 없는 계정은 None."""

    year: int
    revenue: int | None = None  # 매출액
    operating_income: int | None = None  # 영업이익
    net_income: int | None = None  # 당기순이익
    # 사업보고서 연구개발활동 표의 연구개발비용 합계 (정부보조금 차감 전 총액 우선)
    rnd_expense: int | None = None


class DartCompanyFinancials(BaseModel):
    """DART 사업보고서 주요 재무 계정으로 본 기업 1곳의 최근 3개 사업연도 실적."""

    company: str
    stock_code: str
    statement: Literal["연결", "별도"]  # 연결재무제표가 없으면 별도재무제표
    rcept_no: str  # 재무 계정을 가져온 사업보고서 접수번호
    years: list[DartFinancialYear] = Field(default_factory=list)  # 오래된 연도부터
    # 연구개발비용을 뽑은 표의 행 이름·단위. 찾지 못하면 그 사유
    rnd_basis: str = ""


class MarketCompanyFinancials(BaseModel):
    """아이디어와 같은 사업 범주로 검색한 DART 기업의 재무 현황 (시장 규모·구매 수요 근거가 아님)."""

    status: Literal["completed", "no_companies", "error"]
    companies: list[DartCompanyFinancials] = Field(default_factory=list)
    # 재무 계정을 찾지 못한 기업과 사유
    missing: list[str] = Field(default_factory=list)
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
    """시장 근거·차원별 결과·보조 자료의 통합 계약."""

    status: Literal["completed", "no_results", "error"]

    dimensions: list[MarketDimensionResult] = Field(default_factory=list)
    evidence: list[MarketEvidence] = Field(default_factory=list)
    opportunity_review: MarketOpportunityReview | None = None
    commercial_analysis: MarketCommercialAnalysis | None = None
    search_trend: MarketSearchTrend | None = None
    keyword_network: MarketKeywordNetwork | None = None
    company_financials: MarketCompanyFinancials | None = None
    procurement: MarketProcurement | None = None
    unknowns: list[str] = Field(default_factory=list)

    search_scope: str
    data_as_of: int | None = None  # 분석 기준일 YYYYMMDD
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_report(self):
        """시장 보고서의 인용과 하위 결과 간 참조 무결성을 확인한다."""
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
