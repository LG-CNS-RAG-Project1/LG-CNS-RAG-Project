"""사업기획 근거 자료집의 데이터 계약.

자료(기사·본문)·추출 후보·규칙 판정·도표 데이터를 구분해 저장하고, 화면과 텍스트 보고서가
같은 구조화 결과(SemanticResult)를 읽게 한다. 금액은 Decimal을 문자열로 보관한다.
"""

from typing import Literal

from pydantic import BaseModel, Field

EvidenceLayer = Literal["stored_snippet", "reviewed_body", "user_input", "scenario"]
TextLayerName = Literal["title", "stored_snippet", "reviewed_body"]
CellStatus = Literal["explicit", "partial", "unknown", "conflicting"]
ReviewStatus = Literal["candidate", "approved", "unknown"]
StatementKind = Literal[
    "reported_event",  # 매체가 보도한 사건
    "supplier_claim",  # 공급사가 자사 제품·효과를 설명한 주장
    "analyst_interpretation",  # 규칙 템플릿이 만든 제한된 해석
    "user_input",  # 사용자가 입력한 아이디어·가정값
    "scenario",  # 설명용 예시 가정
]
BodyStatus = Literal[
    "not_attempted",
    "disabled",
    "ok",
    "http_403",
    "http_4xx",
    "http_5xx",
    "robots_disallowed",
    "robots_unavailable",
    "timeout",
    "network_error",
    "too_large",
    "non_html",
    "parse_empty",
    "snippet_mismatch",
    "skipped_portal",
    "skipped_denylist",
    "cap_reached",
    "cancelled",
]
ExtractionStatus = Literal[
    "ok", "failed", "not_extracted_no_lexicon_hit", "not_extracted_cap_reached"
]


class Sentence(BaseModel):
    """LLM 입력과 구절 검증에 쓰는 원문 문장. 위치는 해당 층 텍스트 기준이다."""

    sentence_id: str
    layer: TextLayerName
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str
    truncated: bool = False


class TextLayer(BaseModel):
    """기사 한 건의 텍스트 층. 본문 텍스트는 실행 폴더의 bodies/에 따로 둔다."""

    layer: TextLayerName
    origin: Literal["naver_search", "auto_fetch"]
    content_hash: str = ""
    chars: int = 0
    truncated: bool = False
    status: BodyStatus | Literal["ok"] = "ok"


class SourceRecord(BaseModel):
    """자료집에 채택한 기사 한 건의 출처·층·수집 경위."""

    source_id: str
    url: str
    naver_link: str = ""
    publisher: str
    title: str
    snippet: str
    published_at: str = ""  # 원 pubDate의 ISO 8601(+09:00), 없으면 빈 값
    published_date: int | None = None  # YYYYMMDD
    collected_at: str  # ISO 8601(+09:00)
    query_id: str
    question_id: str
    round: int = Field(ge=0)
    dup_group: str
    industry_scope: Literal["direct", "adjacent", "unknown"] = "unknown"
    layers: list[TextLayer] = Field(default_factory=list)
    body_status: BodyStatus = "not_attempted"


class Span(BaseModel):
    """원문에서 코드가 위치를 확인한 연속 구절."""

    source_id: str
    sentence_id: str
    layer: TextLayerName
    start: int = Field(ge=0)
    end: int = Field(ge=0)
    text: str
    occurrences: int = Field(default=1, ge=1)


class Anchor(BaseModel):
    """refresh 시점에 원문으로 계산한 후보의 특징. replay는 원문 없이 이것만 읽는다."""

    anchor_id: str
    source_id: str
    kind: Literal["mention", "claim", "relation", "metric"]
    span: Span
    candidate_role: str = "unknown"
    entity_text: str = ""
    entity_id: str = ""
    owner_entity_id: str = ""
    owner_basis: str = ""
    product: str = ""
    counterpart_text: str = ""
    counterpart_id: str = ""
    counterpart_kind: Literal["", "named", "anonymous", "channel"] = ""
    relation_type: str = ""
    relation_hint: str = ""
    criteria: dict[str, Literal["strong", "weak"]] = Field(default_factory=dict)
    features: list[str] = Field(default_factory=list)
    markers: list[str] = Field(default_factory=list)
    metric_value: str = ""
    unit: str = ""
    measurement_conditions: str = "unknown"
    event_at: str = ""
    event_at_text: str = ""


class ExtractionRecord(BaseModel):
    """기사 한 건의 추출 결과 상태와 LLM 응답 위치."""

    source_id: str
    status: ExtractionStatus
    cache_key: str = ""
    llm_input_hash: str = ""
    input_sentence_ids: list[str] = Field(default_factory=list)
    error: str = ""
    attempts: int = 0
    from_cache: bool = False
    candidates: dict = Field(default_factory=dict)
    rejected: list[dict] = Field(default_factory=list)


class Evidence(BaseModel):
    """규칙 판정을 거친 근거 한 건. 승인되지 않은 후보도 사유와 함께 남긴다."""

    evidence_id: str
    anchor_id: str
    source_id: str
    kind: Literal["supplier", "claim", "relation", "metric"]
    span: Span
    evidence_layer: EvidenceLayer
    statement_kind: StatementKind
    review_status: ReviewStatus
    reasons: list[str] = Field(default_factory=list)
    supplier_id: str = ""
    product: str = ""
    criteria: dict[str, Literal["strong", "weak"]] = Field(default_factory=dict)
    markers: list[str] = Field(default_factory=list)
    dup_group: str = ""
    published_at: str = ""
    industry_scope: str = "unknown"
    reviewer_note: str = ""


class Entity(BaseModel):
    entity_id: str
    name: str
    role: str
    approved: bool
    source_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)


class MatrixCell(BaseModel):
    row_id: str
    criterion_id: str
    status: CellStatus
    evidence_layer: EvidenceLayer | Literal[""] = ""
    evidence_ids: list[str] = Field(default_factory=list)
    supporting_source_ids: list[str] = Field(default_factory=list)
    conflicting_source_ids: list[str] = Field(default_factory=list)
    candidate_evidence_ids: list[str] = Field(default_factory=list)
    reasons: list[str] = Field(default_factory=list)
    unknown_reason: str = ""
    scope_note: str = ""
    article_count: int | None = None
    dup_group_count: int | None = None
    decision_id: str
    next_question_id: str


class MatrixRow(BaseModel):
    row_id: str
    label: str
    kind: Literal["our_claim", "supplier"]
    supplier_id: str = ""
    product: str = ""
    level: Literal["product", "company", "idea"]
    input_origin: str = ""


class Insight(BaseModel):
    insight_id: str
    statement_kind: StatementKind = "analyst_interpretation"
    text: str
    criterion_id: str = ""
    evidence_ids: list[str] = Field(default_factory=list)
    decision_id: str
    next_question_ids: list[str] = Field(default_factory=list)
    limits: str = ""


class Edge(BaseModel):
    edge_id: str
    supplier_id: str
    product: str = ""
    counterpart_id: str
    counterpart_kind: Literal["named", "anonymous", "channel"]
    relation_type: str
    affiliate: bool = False
    status: Literal["approved", "candidate"]
    reasons: list[str] = Field(default_factory=list)
    evidence_ids: list[str] = Field(default_factory=list)
    source_ids: list[str] = Field(default_factory=list)
    dup_groups: list[str] = Field(default_factory=list)
    event_at: str = ""
    event_at_text: str = ""


class Node(BaseModel):
    node_id: str
    label: str
    kind: Literal["supplier", "product", "adopter", "anonymous_adopter", "channel"]


class AssumptionLink(BaseModel):
    assumption_id: str
    label: str
    statement: str
    statement_kind: StatementKind = "user_input"
    status: Literal[
        "counter_evidence",
        "supporting_evidence",
        "mixed",
        "no_evidence",
        "needs_company_input",
        "needs_customer_validation",
    ]
    supporting_ids: list[str] = Field(default_factory=list)
    counter_ids: list[str] = Field(default_factory=list)
    note: str = ""
    affected_choice: str
    options: list[str] = Field(default_factory=list)
    next_question_ids: list[str] = Field(default_factory=list)


class QuestionPick(BaseModel):
    question_id: str
    question: str
    decision: str
    status: Literal[
        "answer_requirements_met",
        "gap",
        "requires_company_input",
        "requires_customer_validation",
        "not_automated",
    ]
    priority: list[int] = Field(default_factory=list)
    missing: list[str] = Field(default_factory=list)
    queries: list[str] = Field(default_factory=list)
    stop_reason: str = ""
    linked_assumptions: list[str] = Field(default_factory=list)


class ChartAvailability(BaseModel):
    chart_id: str
    label: str
    available: bool
    missing: list[str] = Field(default_factory=list)
    how_to_obtain: list[str] = Field(default_factory=list)
    question_ids: list[str] = Field(default_factory=list)


class PriceResult(BaseModel):
    """가격 조건 계산 결과. 금액은 만원 단위 고정소수 문자열이다."""

    mode: Literal["actual", "example"]
    status: Literal["withheld", "invalid", "no_positive_price", "no_overlap", "overlap"]
    calc_version: str
    unit: str = "만원"
    inputs: dict[str, str | None] = Field(default_factory=dict)
    provenance: dict[str, dict[str, str]] = Field(default_factory=dict)
    missing: list[str] = Field(default_factory=list)
    errors: list[str] = Field(default_factory=list)
    floor: str | None = None
    ceiling: str | None = None
    floor_display: str | None = None
    ceiling_display: str | None = None
    required_benefit: str | None = None
    required_benefit_display: str | None = None
    max_direct_cost: str | None = None
    max_direct_cost_display: str | None = None


class SemanticResult(BaseModel):
    """replay에서 같은 입력이면 같은 해시가 나와야 하는 의미 결과."""

    schema_version: Literal["planner-semantic-v1"] = "planner-semantic-v1"
    idea_hash: str
    area_id: str
    versions: dict[str, str]
    counts: dict
    entities: list[Entity] = Field(default_factory=list)
    evidence: list[Evidence] = Field(default_factory=list)
    criteria: list[dict] = Field(default_factory=list)
    rows: list[MatrixRow] = Field(default_factory=list)
    cells: list[MatrixCell] = Field(default_factory=list)
    insights: list[Insight] = Field(default_factory=list)
    nodes: list[Node] = Field(default_factory=list)
    edges: list[Edge] = Field(default_factory=list)
    relation_counts: dict = Field(default_factory=dict)
    assumptions: list[AssumptionLink] = Field(default_factory=list)
    questions: list[QuestionPick] = Field(default_factory=list)
    followup_charts: list[ChartAvailability] = Field(default_factory=list)
    price: PriceResult | None = None


class RunManifest(BaseModel):
    run_id: str
    parent_run_id: str = ""
    mode: Literal["refresh", "reanalyze"]
    idea_hash: str
    area_id: str
    idea_title: str
    as_of: str
    timezone: str = "+09:00"
    versions: dict[str, str]
    budget: dict
    files: dict[str, str] = Field(default_factory=dict)
    git_commit: str = "unknown"
