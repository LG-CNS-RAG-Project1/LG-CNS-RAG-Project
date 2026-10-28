"""관련성 판정된 시장 검색 결과로 차원별 시장 분석(MarketReport)을 생성하고 인용을 검증한다.

흐름:
    build_evidence(assessed)        관련 판정된 기사만 인용 근거(MarketEvidence)로 정리, 기사당 citation_id 1개
    allowed_verdicts(...)           충분성 상태로 쓸 수 있는 판정 제한
    generate_dimensions(...)        LLM 생성 → validate_dimension 검증 → 실패 시 오류를 알려 최대 MAX_RETRIES회 재생성
    finalize_dimension(...)         재생성 후에도 실패한 문장은 제거하고, 판정을 유지할 수 없으면 미확인으로 바꿈
    build_report(...)               MarketReport로 묶음

판정 제한 (차원별 충분성 상태 기준):
    sufficient    confirmed · signal_only · unverified (confirmed는 수요면 direct_demand 근거,
                  그 밖의 차원은 사업 신호·기업 주장·추정치가 아닌 근거가 있을 때만)
    limited       signal_only · unverified
    그 밖         unverified
차원이 기대는 아이디어 항목(DEPENDENT_FIELDS)이 비어 있으면(모름) 근거가 있어도 unverified만 허용한다.
"""

import json
import re
from datetime import date, datetime
from pathlib import Path
from typing import Callable

from src.generation.idea_parser import FIELD_LABELS
from src.retrieval.market_relevance import DIMENSION_LABELS, call_relevance_llm
from src.schemas import (
    ALL_DIMENSIONS,
    IDEA_FIELDS,
    MarketDimensionResult,
    MarketEvidence,
    MarketOpportunityFinding,
    MarketOpportunityReview,
    MarketReport,
    MarketValidationAction,
    StructuredIdea,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT_DIR / "prompts" / "market_analysis.md"
ANALYSIS_MODEL = "gpt-4o-mini"
MAX_RETRIES = 2
MAX_CLAIMS = 3
RECENT_DAYS = 365
STALE_DAYS = 3 * 365
NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)*")
# 시장 규모·가격·비율·건수처럼 단위가 붙은 수치. 사실 문장에 있으면 기준 연도를 함께 써야 한다.
METRIC_PATTERN = re.compile(
    r"\d+(?:[.,]\d+)*\s*(%|퍼센트|배|원|만|억|조|달러|건|대|개사|곳|명|개월)"
)
YEAR_PATTERN = re.compile(r"(?<!\d)(?:19|20)\d{2}년")

# 시장 차원이 판정에 기대는 아이디어 항목
DEPENDENT_FIELDS = {"price": "revenue", "buyer": "customers"}

# 이 성격의 근거만 있으면 어느 차원도 confirmed가 될 수 없다 (뉴스는 모두 business_signal)
SIGNAL_ONLY_NATURES = {"business_signal", "company_claim", "estimate"}

DEFAULT_CHECKS = {
    "demand": "목표 고객사 5곳 인터뷰로 현재 해결 방식과 도입 의향 확인",
    "competition": "경쟁·대체 솔루션 3개를 골라 기능·가격·도입 방식 비교",
    "price": "공급사 견적이나 공공 지원사업 단가로 도입 가격대 확인",
    "buyer": "목표 고객사의 구매 결정자와 구매 절차 확인",
    "adoption_barrier": "파일럿 고객 1곳에서 설치·운영 시 장애 요인 확인",
}

LLMFn = Callable[[str, str], dict]
MARKET_IDEA_FIELDS = {
    "title",
    *IDEA_FIELDS,
    "current_alternative",
    "target_segment",
    "value_hypotheses",
    "field_sources",
}


def call_analysis_llm(system_prompt: str, user_text: str) -> dict:
    """ANALYSIS_MODEL로 OpenAI 채팅 API를 JSON 모드로 호출한다. OPENAI_API_KEY가 필요하다."""
    return call_relevance_llm(system_prompt, user_text, model=ANALYSIS_MODEL)


def _to_date(value: int) -> date:
    return datetime.strptime(str(value), "%Y%m%d").date()


def recency_grade(published_at: int, data_as_of: int) -> str:
    """기준일까지 경과 일수로 최신성 등급을 정한다 (1년 이내 high, 3년 이내 medium)."""
    days = (_to_date(data_as_of) - _to_date(published_at)).days
    if days <= RECENT_DAYS:
        return "high"
    return "medium" if days <= STALE_DAYS else "low"


def directness_grade(hit: dict) -> str:
    """근거의 직접성 등급. 구매·지불 근거면 high, 관련성 판정 확신이 높으면 medium, 그 밖은 low."""
    if hit["evidence_nature"] in ("direct_demand", "purchase_signal"):
        return "high"
    return "medium" if hit.get("relevance_confidence") == "high" else "low"


def quote_text(hit: dict) -> str:
    """검색 결과 text(제목 + 줄바꿈 + 요약)에서 요약을 인용문으로 쓴다. 요약이 없으면 제목."""
    _, _, summary = hit["text"].partition("\n")
    return summary.strip() or hit["title"]


def build_evidence(
    assessed: dict[str, dict], data_as_of: int
) -> tuple[list[MarketEvidence], dict[str, list[int]]]:
    """관련 판정된 기사를 인용 근거로 만들고 차원별 citation_id 목록을 반환한다.

    같은 기사가 여러 차원에 나오면 citation_id 하나를 공유한다. 판정 실패(error) 차원의
    결과는 근거로 쓰지 않는다.
    """
    evidence: list[MarketEvidence] = []
    by_source: dict[str, int] = {}
    ids_by_dimension: dict[str, list[int]] = {}
    for dimension in ALL_DIMENSIONS:
        result = assessed.get(dimension)
        ids = []
        if result and result["status"] != "error":
            for hit in result["hits"]:
                if not hit.get("relevant"):
                    continue
                if hit["source_id"] not in by_source:
                    distance = hit.get("distance")
                    evidence.append(
                        MarketEvidence(
                            citation_id=len(evidence) + 1,
                            source_id=hit["source_id"],
                            source_type=hit["source_type"],
                            title=hit["title"],
                            publisher=hit["publisher"],
                            quote=quote_text(hit),
                            section=hit.get("section"),
                            url=hit.get("url"),
                            published_at=hit["published_at"],
                            period=hit.get("period"),
                            reliability=hit["reliability"],
                            recency=recency_grade(hit["published_at"], data_as_of),
                            directness=directness_grade(hit),
                            evidence_nature=hit["evidence_nature"],
                            similarity=(
                                None
                                if distance is None
                                else min(max(1 - distance, 0.0), 1.0)
                            ),
                        )
                    )
                    by_source[hit["source_id"]] = len(evidence)
                ids.append(by_source[hit["source_id"]])
        ids_by_dimension[dimension] = ids
    return evidence, ids_by_dimension


def missing_dependent_field(idea: StructuredIdea, dimension: str) -> str | None:
    """차원이 기대는 아이디어 항목이 비어 있으면 그 항목 이름(한국어)을 반환한다."""
    field = DEPENDENT_FIELDS.get(dimension)
    return FIELD_LABELS[field] if field and not getattr(idea, field) else None


def allowed_verdicts(
    dimension: str,
    status: str,
    cited: list[MarketEvidence],
    missing_field: str | None = None,
) -> list[str]:
    """충분성 상태·근거 성격·아이디어 항목 공백으로 이 차원에 쓸 수 있는 판정을 정한다.

    confirmed는 확인 가능한 성격의 근거가 있을 때만 허용한다: 수요는 direct_demand,
    그 밖의 차원은 SIGNAL_ONLY_NATURES(사업 신호·기업 주장·추정치)가 아닌 근거.
    """
    if missing_field or not cited or status not in ("sufficient", "limited"):
        return ["unverified"]
    if status == "limited":
        return ["signal_only", "unverified"]
    confirming = (
        (lambda e: e.evidence_nature == "direct_demand")
        if dimension == "demand"
        else (lambda e: e.evidence_nature not in SIGNAL_ONLY_NATURES)
    )
    if not any(confirming(e) for e in cited):
        return ["signal_only", "unverified"]
    return ["confirmed", "signal_only", "unverified"]


def analysis_input(
    idea: StructuredIdea,
    dimension_inputs: list[dict],
    previous_errors: dict[str, list[str]] | None = None,
) -> str:
    """분석 프롬프트에 넘길 입력 JSON(아이디어·차원별 판정 범위·근거)을 만든다."""
    data = {
        "idea": idea.model_dump(include=MARKET_IDEA_FIELDS),
        "dimensions": dimension_inputs,
    }
    if previous_errors:
        data["previous_errors"] = previous_errors
    return json.dumps(data, ensure_ascii=False)


def dimension_inputs(
    idea: StructuredIdea,
    assessed: dict[str, dict],
    evidence: list[MarketEvidence],
    ids_by_dimension: dict[str, list[int]],
) -> list[dict]:
    """차원별로 판정 범위와 근거 기사(인용 번호·제목·요약)를 정리한다.

    기대는 아이디어 항목이 비어 있는 차원에는 missing_idea_field(항목 이름)를 붙인다.
    """
    by_id = {e.citation_id: e for e in evidence}
    inputs = []
    for dimension in ALL_DIMENSIONS:
        if dimension not in assessed:
            continue
        cited = [by_id[i] for i in ids_by_dimension.get(dimension, [])]
        missing = missing_dependent_field(idea, dimension)
        inputs.append(
            {
                "dimension": dimension,
                "label": DIMENSION_LABELS[dimension],
                "allowed_verdicts": allowed_verdicts(
                    dimension, assessed[dimension]["status"], cited, missing
                ),
                **({"missing_idea_field": missing} if missing else {}),
                "evidence": [
                    {
                        "citation_id": e.citation_id,
                        "title": e.title,
                        "quote": e.quote,
                        "publisher": e.publisher,
                        "published_at": e.published_at,
                        "evidence_nature": e.evidence_nature,
                    }
                    for e in cited
                ],
            }
        )
    return inputs


def publication_date_text(evidence: MarketEvidence) -> str:
    """발행일의 연·월·일 숫자(앞자리 0 제거). '(2026년 3월 보도)' 같은 시점 표기를 숫자 검증에서 허용한다."""
    published = _to_date(evidence.published_at)
    return f"{published.year}년 {published.month}월 {published.day}일"


def numbers_in(text: str) -> set[str]:
    """문장 속 숫자를 쉼표를 뺀 문자열 집합으로 추출한다."""
    return {n.replace(",", "") for n in NUMBER_PATTERN.findall(text)}


def content_overlap(statement: str, sources: str) -> float:
    """문장과 인용 원문 사이의 핵심 표현 토큰 겹침 비율을 계산한다."""
    from src.retrieval.engine import tokenize

    statement_tokens = {
        token for token in tokenize(statement) if len(token) > 1 and not token.isdigit()
    }
    source_tokens = {
        token for token in tokenize(sources) if len(token) > 1 and not token.isdigit()
    }
    if not statement_tokens:
        return 1.0
    return len(statement_tokens & source_tokens) / len(statement_tokens)


def claim_errors(
    claim: dict, allowed_ids: set[int], by_id: dict[int, MarketEvidence], idea_text: str
) -> list[str]:
    """문장 1개의 검증 오류 목록. 빈 목록이면 통과다.

    - 문장 유형이 fact·user_claim·ai_hypothesis 중 하나인지
    - fact는 인용이 1개 이상이고 모두 이 차원의 근거 ID인지
    - 문장의 숫자가 인용 기사(제목·요약·발행연도)나 아이디어 입력에 있는지
    - fact 문장에 단위가 붙은 수치(METRIC_PATTERN)가 있으면 4자리 기준 연도도 있는지
    """
    statement = str(claim.get("statement", "")).strip()
    claim_type = claim.get("claim_type")
    citation_ids = claim.get("citation_ids") or []
    if not statement:
        return ["빈 문장"]
    if claim_type not in ("fact", "user_claim", "ai_hypothesis"):
        return [f"알 수 없는 claim_type: {claim_type}"]
    if not all(isinstance(i, int) for i in citation_ids):
        return [f"citation_ids는 정수 목록이어야 함: {citation_ids}"]
    if claim_type == "fact" and not citation_ids:
        return [f"인용 없는 fact 문장: {statement}"]
    unknown = [i for i in citation_ids if i not in allowed_ids]
    if unknown:
        return [f"이 차원의 근거에 없는 인용 {unknown}: {statement}"]

    sources = (
        idea_text
        + " "
        + " ".join(
            f"{by_id[i].title} {by_id[i].quote} {publication_date_text(by_id[i])}"
            for i in citation_ids
        )
    )
    missing = numbers_in(statement) - numbers_in(sources)
    if missing:
        return [f"근거에 없는 숫자 {sorted(missing)}: {statement}"]
    if citation_ids and content_overlap(statement, sources) < 0.2:
        return [f"문장 내용과 인용 원문의 핵심 표현이 연결되지 않음: {statement}"]
    if (
        claim_type == "fact"
        and METRIC_PATTERN.search(statement)
        and not YEAR_PATTERN.search(statement)
    ):
        return [f"수치에 기준 연도가 없음 (예: '(2026년 3월 보도)'): {statement}"]
    return []


def validate_dimension(
    raw: dict,
    allowed: list[str],
    allowed_ids: set[int],
    by_id: dict[int, MarketEvidence],
    idea_text: str,
) -> list[str]:
    """LLM이 만든 차원 결과 1개의 검증 오류 목록을 반환한다."""
    errors = []
    verdict = raw.get("verdict")
    if verdict not in allowed:
        errors.append(f"허용되지 않은 판정 {verdict} (허용: {allowed})")
    claims = raw.get("claims") or []
    if len(claims) > MAX_CLAIMS:
        errors.append(f"문장 {len(claims)}개 (최대 {MAX_CLAIMS}개)")
    for claim in claims:
        errors += claim_errors(claim, allowed_ids, by_id, idea_text)
    if sum(c.get("claim_type") == "ai_hypothesis" for c in claims) > 1:
        errors.append("ai_hypothesis 문장은 차원당 1개까지")
    if verdict in ("confirmed", "signal_only") and not any(
        c.get("claim_type") == "fact" for c in claims
    ):
        errors.append(f"{verdict} 판정에 인용된 fact 문장이 없음")
    if verdict == "unverified" and not str(raw.get("next_check") or "").strip():
        errors.append("unverified 판정에 next_check가 없음")
    return errors


def finalize_dimension(
    dimension: str,
    raw: dict | None,
    allowed: list[str],
    allowed_ids: set[int],
    by_id: dict[int, MarketEvidence],
    idea_text: str,
    default_check: str | None = None,
) -> MarketDimensionResult:
    """검증을 통과한 문장만 남겨 차원 결과를 확정한다.

    판정이 허용 범위 밖이거나 남은 fact 문장이 없으면 미확인으로 바꾸고, 검증 과제가 없으면
    default_check(없으면 DEFAULT_CHECKS)를 쓴다.
    """
    raw = raw or {}
    claims = [
        {
            "statement": " ".join(str(c["statement"]).split()),
            "claim_type": c["claim_type"],
            "citation_ids": list(dict.fromkeys(c.get("citation_ids") or [])),
        }
        for c in (raw.get("claims") or [])
        if not claim_errors(c, allowed_ids, by_id, idea_text)
    ]
    hypotheses = [c for c in claims if c["claim_type"] == "ai_hypothesis"]
    claims = [c for c in claims if c["claim_type"] != "ai_hypothesis"] + hypotheses[:1]
    claims = claims[:MAX_CLAIMS]

    verdict = raw.get("verdict")
    has_fact = any(c["claim_type"] == "fact" for c in claims)
    if verdict not in allowed or (verdict != "unverified" and not has_fact):
        verdict = "unverified"
    next_check = " ".join(str(raw.get("next_check") or "").split()) or None
    if verdict == "unverified" and not next_check:
        next_check = default_check or DEFAULT_CHECKS[dimension]
    return MarketDimensionResult(
        dimension=dimension, verdict=verdict, claims=claims, next_check=next_check
    )


def generate_dimensions(
    idea: StructuredIdea,
    inputs: list[dict],
    evidence: list[MarketEvidence],
    llm_fn: LLMFn = call_analysis_llm,
    max_retries: int = MAX_RETRIES,
) -> tuple[list[MarketDimensionResult], int]:
    """LLM으로 차원별 분석을 생성·검증하고 (확정 결과, 재생성 횟수)를 반환한다.

    검증 오류가 있으면 오류 내용을 previous_errors로 넘겨 최대 max_retries회 재생성한다.
    """
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    by_id = {e.citation_id: e for e in evidence}
    idea_text = " ".join(
        str(value)
        for key, value in idea.model_dump(include=MARKET_IDEA_FIELDS).items()
        if key != "value_hypotheses" and key != "field_sources"
    )
    specs = {
        d["dimension"]: (
            d["allowed_verdicts"],
            {e["citation_id"] for e in d["evidence"]},
        )
        for d in inputs
    }
    default_checks = {
        d["dimension"]: (
            f"아이디어 {d['missing_idea_field']} 항목을 정한 뒤 {DEFAULT_CHECKS[d['dimension']]}"
            if d.get("missing_idea_field")
            else DEFAULT_CHECKS[d["dimension"]]
        )
        for d in inputs
    }

    errors: dict[str, list[str]] = {}
    raw_by_dim: dict[str, dict] = {}
    retries = 0
    for attempt in range(max_retries + 1):
        response = llm_fn(system_prompt, analysis_input(idea, inputs, errors or None))
        raw_by_dim = {
            d.get("dimension"): d
            for d in response.get("dimensions", [])
            if isinstance(d, dict)
        }
        errors = {}
        for dimension, (allowed, allowed_ids) in specs.items():
            raw = raw_by_dim.get(dimension)
            found = (
                validate_dimension(raw, allowed, allowed_ids, by_id, idea_text)
                if raw
                else ["차원 결과 누락"]
            )
            if found:
                errors[dimension] = found
        retries = attempt
        if not errors:
            break

    results = [
        finalize_dimension(
            dimension,
            raw_by_dim.get(dimension),
            allowed,
            allowed_ids,
            by_id,
            idea_text,
            default_checks[dimension],
        )
        for dimension, (allowed, allowed_ids) in specs.items()
    ]
    return results, retries


def report_unknowns(
    idea: StructuredIdea, dimensions: list[MarketDimensionResult]
) -> list[str]:
    """비어 있는 아이디어 항목과 미확인 차원을 미확인 목록으로 만든다."""
    unknowns = [
        f"아이디어 {FIELD_LABELS[f]} 항목 미입력"
        for f in IDEA_FIELDS
        if not getattr(idea, f)
    ]
    unknowns += [
        f"{DIMENSION_LABELS[d.dimension]} 근거 미확인"
        for d in dimensions
        if d.verdict == "unverified"
    ]
    return unknowns


def opportunity_review(
    idea: StructuredIdea,
    dimensions: list[MarketDimensionResult],
    evidence: list[MarketEvidence],
) -> MarketOpportunityReview:
    """차원별 근거를 아이디어 시장성·다음 검증 행동으로 요약한다."""
    by_dimension = {item.dimension: item for item in dimensions}
    by_id = {item.citation_id: item for item in evidence}
    direct = [
        item
        for item in evidence
        if item.source_type == "customer_validation"
        and item.evidence_nature == "direct_demand"
    ]
    buyer = by_dimension.get("buyer")
    buyer_ids = (
        list(dict.fromkeys(cid for claim in buyer.claims for cid in claim.citation_ids))
        if buyer
        else []
    )
    if direct:
        status = "validated_demand"
    elif buyer_ids:
        status = "buyer_signals"
    elif evidence:
        status = "indirect_signals"
    else:
        status = "insufficient_evidence"

    reasons = []
    for dimension in dimensions:
        cited = list(
            dict.fromkeys(
                cid for claim in dimension.claims for cid in claim.citation_ids
            )
        )
        if dimension.verdict != "unverified" or cited:
            labels = {
                "demand": "수요",
                "competition": "경쟁·대체재",
                "price": "가격·수익모델",
                "buyer": "구매자",
                "adoption_barrier": "도입장벽",
            }
            reasons.append(
                MarketOpportunityFinding(
                    topic=labels[dimension.dimension],
                    statement=(
                        f"{labels[dimension.dimension]} 판단은 {dimension.verdict}이며, "
                        f"현재 확정 아이디어의 고객·문제 범위 안에서 해석해야 합니다."
                    ),
                    citation_ids=cited,
                )
            )

    unknowns = []
    if not idea.customers:
        unknowns.append("목표 고객과 구매 결정자")
    if not idea.current_alternative:
        unknowns.append("고객의 현재 해결 방식과 대체재")
    if not direct:
        unknowns.append("고객 인터뷰·구매 검토·파일럿 등 직접 수요 증거")
    if not idea.revenue:
        unknowns.append("과금 방식과 지불 주체")
    if not idea.value_hypotheses:
        unknowns.append("고객 가치와 ROI를 계산할 측정 변수")
    unknowns.extend(
        f"{dimension.dimension} 차원 추가 근거"
        for dimension in dimensions
        if dimension.verdict == "unverified"
    )

    actions = []
    if not direct:
        actions.append(
            MarketValidationAction(
                title="목표 고객 문제·구매 검증",
                target=idea.target_segment or idea.customers or "목표 고객 후보",
                method="현재 해결 방식, 문제 발생 맥락, 비용 영향, 구매결정자와 도입 조건을 묻는 인터뷰를 수행하고 익명 요약만 기록",
                success_signal="여러 고객이 같은 문제와 현재 대안을 구체적 사례로 확인하고, 구매 절차 또는 후속 실증 의사를 설명함",
            )
        )
    if not idea.revenue or not idea.customers:
        actions.append(
            MarketValidationAction(
                title="구매자·과금 가설 정리",
                target=idea.target_segment or idea.customers or "목표 고객 후보",
                method="사용자, 구매 결정자, 예산 주체, 구매·구독·유지보수 중 가능한 과금 방식을 구분하고 공급사 견적과 대조",
                success_signal="구매 주체·예산 경로·비교 가능한 가격 기준이 확인되거나 미확인 사유가 명시됨",
                citation_ids=[cid for cid in buyer_ids if cid in by_id],
            )
        )
    if not idea.value_hypotheses:
        actions.append(
            MarketValidationAction(
                title="고객 가치 측정 기준 설정",
                target=idea.target_segment or idea.customers or "목표 고객 후보",
                method="고객과 함께 문제 빈도, 현재 처리시간·불량·비용 중 측정 가능한 기준을 선택하고 파일럿 전후에 같은 방식으로 기록",
                success_signal="현재 기준선과 목표 효과를 고객이 합의하고, 측정 자료 접근 범위가 정해짐",
            )
        )

    return MarketOpportunityReview(
        status=status,
        target_segment=idea.target_segment or idea.customers,
        value_hypotheses=idea.value_hypotheses,
        reasons=reasons,
        unknowns=list(dict.fromkeys(unknowns)),
        validation_actions=actions,
    )


def build_report(
    idea: StructuredIdea,
    assessed: dict[str, dict],
    search_scope: str,
    data_as_of: int,
    llm_fn: LLMFn = call_analysis_llm,
) -> MarketReport:
    """관련성 판정 결과로 MarketReport를 만든다.

    검색 결과가 하나도 없으면 no_results, 분석 생성이 실패하면 error(근거는 유지)로 반환한다.
    """
    evidence, ids_by_dimension = build_evidence(assessed, data_as_of)
    if not any(result["hits"] for result in assessed.values()):
        return MarketReport(
            status="no_results",
            search_scope=search_scope,
            data_as_of=data_as_of,
            unknowns=report_unknowns(idea, []),
            opportunity_review=opportunity_review(idea, [], []),
        )
    inputs = dimension_inputs(idea, assessed, evidence, ids_by_dimension)
    try:
        dimensions, _ = generate_dimensions(idea, inputs, evidence, llm_fn)
    except Exception as exc:  # 생성 실패를 보고서 단위 오류로 전달
        return MarketReport(
            status="error",
            evidence=evidence,
            search_scope=search_scope,
            data_as_of=data_as_of,
            error_message=f"market analysis failed: {exc}",
            opportunity_review=opportunity_review(idea, [], evidence),
            unknowns=report_unknowns(idea, []),
        )
    return MarketReport(
        status="completed",
        dimensions=dimensions,
        evidence=evidence,
        opportunity_review=opportunity_review(idea, dimensions, evidence),
        unknowns=report_unknowns(idea, dimensions),
        search_scope=search_scope,
        data_as_of=data_as_of,
    )
