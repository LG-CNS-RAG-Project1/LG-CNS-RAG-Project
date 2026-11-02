"""Market search, evidence, validation, and report data contracts."""

import re
from typing import Literal

from pydantic import BaseModel, Field, model_validator

from src.idea_schemas import IDEA_FIELDS, IdeaField, StructuredIdea

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
