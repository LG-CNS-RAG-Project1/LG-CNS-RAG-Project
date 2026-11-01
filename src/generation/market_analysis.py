"""관련성 판정된 자료를 차원별 시장 분석과 MarketReport로 묶는다.

흐름:
    build_evidence(assessed)        관련 자료를 출처가 추적되는 인용 근거로 정리
    dimension_inputs(...)           차원별 허용 판정과 근거 범위를 구성
    generate_dimensions(...)        LLM 분석을 생성하고 market_claims 규칙으로 검증·확정
    with_limitations(...)           검색 상태·근거 수·미확인 이유를 보강
    build_report(...)               MarketReport로 묶음

확인 판정은 시장 수요에 직접 고객 검증 자료, 다른 차원에는 사업 신호·기업 주장·추정치가
아닌 근거가 인용된 fact 문장이 있을 때만 허용한다. 기대는 아이디어 항목이 비어 있거나
나라장터 자료의 고객 범위가 맞지 않으면 판정을 제한한다.
"""

import json
import re
from pathlib import Path
from typing import Callable

from src.generation.market_claims import (
    CERTAINTY_PATTERN,
    DEFAULT_CHECKS,
    DEPENDENT_FIELDS,
    MAX_CLAIMS,
    METRIC_PATTERN,
    NUMBER_PATTERN,
    PUBLIC_CUSTOMER_TERMS,
    SIGNAL_ONLY_NATURES,
    YEAR_PATTERN,
    allowed_verdicts,
    attribute_dart,
    attribute_procurement,
    claim_errors,
    confirms,
    content_overlap,
    disclosing_company,
    finalize_dimension,
    has_confirming_fact,
    missing_dependent_field,
    numbers_in,
    public_target,
    publication_date_text,
    validate_dimension,
)
from src.generation.idea_parser import FIELD_LABELS
from src.generation.market_markdown import VERDICT_LABELS
from src.retrieval.market_relevance import DIMENSION_LABELS, call_relevance_llm
from src.schemas import (
    ALL_DIMENSIONS,
    IDEA_FIELDS,
    MarketDimensionResult,
    MarketEvidence,
    MarketOpportunityFinding,
    MarketOpportunityReview,
    MarketCommercialAnalysis,
    MarketReport,
    MarketValidationAction,
    StructuredIdea,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT_DIR / "prompts" / "market_analysis.md"
ANALYSIS_MODEL = "gpt-4o-mini"
MAX_RETRIES = 2

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
    """선택한 LLM provider의 ANALYSIS_MODEL로 JSON 응답을 호출한다."""
    return call_relevance_llm(system_prompt, user_text, model=ANALYSIS_MODEL)


from src.generation.market_evidence import (
    build_evidence,
    directness_grade,
    quote_text,
    recency_grade,
    source_natures,
)


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
        confirmable = (
            [e for e in cited if e.source_type != "procurement"]
            if dimension == "buyer" and not public_target(idea)
            else None
        )
        missing = missing_dependent_field(idea, dimension)
        inputs.append(
            {
                "dimension": dimension,
                "label": DIMENSION_LABELS[dimension],
                "allowed_verdicts": allowed_verdicts(
                    dimension,
                    assessed[dimension]["status"],
                    cited,
                    missing,
                    confirmable,
                ),
                **({"missing_idea_field": missing} if missing else {}),
                "evidence": [
                    {
                        "citation_id": e.citation_id,
                        "source_type": e.source_type,
                        "title": e.title,
                        "quote": e.quote,
                        "publisher": e.publisher,
                        "published_at": e.published_at,
                        **({"period": e.period} if e.period else {}),
                        "evidence_nature": e.evidence_nature,
                    }
                    for e in cited
                ],
            }
        )
    return inputs


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


def limitation_text(
    dimension: str,
    verdict: str,
    result: dict | None,
    pool: list[MarketEvidence],
    missing_field: str | None,
) -> str | None:
    """판정이 confirmed가 아닌 이유를 자료 없음·판정 실패·관련 부족·근거 성격으로 구분해 쓴다.

    result는 assess_dimensions의 차원 결과, pool은 이 차원에 관련 판정된 근거다.
    """
    if verdict == "confirmed":
        return None
    if missing_field:
        return f"아이디어 {missing_field} 항목이 비어 있어 판단하지 않음"
    status = (result or {}).get("status", "no_results")
    searched = len((result or {}).get("hits", []))
    if status == "no_results":
        return "검색 범위에 이 차원의 자료가 없음 (수요·시장이 없다는 뜻은 아님)"
    if status == "error":
        return "관련성 판정이 실패해 근거로 쓰지 않음"
    if status == "insufficient":
        return f"검색된 자료 {searched}건이 모두 이 차원과 무관하다고 판정됨"
    if status == "limited":
        return "관련 자료가 1건뿐이라 확인할 수 없음 (최대 신호 수준)"
    if dimension == "demand":
        return "수요 확인에는 고객 검증 자료(인터뷰·설문·파일럿·LOI)가 필요하며 기사·공시로는 확인할 수 없음"
    if all(e.evidence_nature in SIGNAL_ONLY_NATURES for e in pool):
        return f"관련 자료 {len(pool)}건이 모두 사업 신호·기업 주장·추정치라 확인할 수 없음"
    return "구매·조사 근거가 있으나 분석 단계에서 판단에 충분하지 않다고 봄"


def with_limitations(
    idea: StructuredIdea,
    dimensions: list[MarketDimensionResult],
    assessed: dict[str, dict],
    evidence: list[MarketEvidence],
    ids_by_dimension: dict[str, list[int]],
) -> list[MarketDimensionResult]:
    """차원 결과에 검색 상태·관련 근거 수·확인되지 않은 이유를 붙인다."""
    by_id = {e.citation_id: e for e in evidence}
    enriched = []
    for d in dimensions:
        result = assessed.get(d.dimension)
        pool = [by_id[i] for i in ids_by_dimension.get(d.dimension, [])]
        enriched.append(
            d.model_copy(
                update={
                    "evidence_status": (result or {}).get("status", "no_results"),
                    "relevant_count": (result or {}).get("relevant_count"),
                    "limitation": limitation_text(
                        d.dimension,
                        d.verdict,
                        result,
                        pool,
                        missing_dependent_field(idea, d.dimension),
                    ),
                }
            )
        )
    return enriched


def report_unknowns(
    idea: StructuredIdea, dimensions: list[MarketDimensionResult]
) -> list[str]:
    """비어 있는 아이디어 항목과 미확인 차원(이유 포함)을 미확인 목록으로 만든다."""
    unknowns = [
        f"아이디어 {FIELD_LABELS[f]} 항목 미입력"
        for f in IDEA_FIELDS
        if not getattr(idea, f)
    ]
    unknowns += [
        f"{DIMENSION_LABELS[d.dimension]} 근거 미확인"
        + (f": {d.limitation}" if d.limitation else "")
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
                        f"{labels[dimension.dimension]} 판단: "
                        f"{VERDICT_LABELS[dimension.verdict]}. "
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


# 공공 조달 근거로 채울 수 있는 사업 승인 분석 항목
PUBLIC_SCOPE_FIELDS = (
    "buyer",
    "budget_owner",
    "purchase_process",
    "pricing_hypothesis",
)


def mark_target_unknown(
    result: MarketCommercialAnalysis, idea: StructuredIdea
) -> MarketCommercialAnalysis:
    """고객이 공공 부문이 아니면 공공 조달로 채운 항목 끝에 목표 고객은 미확인임을 붙인다.

    '공공'으로 시작하거나 '나라장터'가 들어간 항목만 대상이며, 이미 '목표 고객'을 밝혔으면 그대로 둔다.
    """
    if public_target(idea):
        return result
    target = idea.customers or "목표 고객"
    updates = {}
    for field in PUBLIC_SCOPE_FIELDS:
        value = getattr(result, field)
        if (
            value.startswith("공공") or "나라장터" in value
        ) and "목표 고객" not in value:
            updates[field] = f"{value} / 목표 고객({target})은 미확인"
    return result.model_copy(update=updates)


def generate_commercial_analysis(
    idea: StructuredIdea, evidence: list[MarketEvidence], llm_fn: LLMFn
) -> MarketCommercialAnalysis:
    """사업 승인자가 볼 구매 구조를 별도 출력 계약으로 분석한다."""
    prompt = (ROOT_DIR / "prompts" / "market_commercial_review.md").read_text(
        encoding="utf-8"
    )
    payload = {
        "idea": idea.model_dump(include=MARKET_IDEA_FIELDS),
        "evidence": [item.model_dump() for item in evidence],
    }
    raw = llm_fn(prompt, json.dumps(payload, ensure_ascii=False))
    result = MarketCommercialAnalysis.model_validate(
        raw.get("commercial_analysis", raw)
    )
    allowed = {item.citation_id for item in evidence}
    if not set(result.citation_ids) <= allowed:
        raise ValueError("사업 승인 분석이 제공되지 않은 citation ID를 참조합니다")
    for hypothesis in result.hypotheses:
        if not set(hypothesis.citation_ids) <= allowed:
            raise ValueError("시장 가설이 제공되지 않은 citation ID를 참조합니다")
        if hypothesis.numeric_value is not None:
            token = f"{hypothesis.numeric_value:g}"
            if not hypothesis.citation_ids or not any(
                re.search(
                    rf"(?<!\d){re.escape(token.replace(',', ''))}(?!\d)",
                    re.sub(r"(?<=\d),(?=\d)", "", item.quote).replace(" ", ""),
                )
                for item in evidence
                if item.citation_id in hypothesis.citation_ids
            ):
                raise ValueError("시장 수치 가설이 인용 원문과 일치하지 않습니다")
    return mark_target_unknown(result, idea)


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
        dimensions = with_limitations(
            idea, dimensions, assessed, evidence, ids_by_dimension
        )
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
    commercial = None
    commercial_unknowns = []
    try:
        commercial = generate_commercial_analysis(idea, evidence, llm_fn)
    except Exception as exc:
        commercial_unknowns.append(
            f"사업 승인 관점 분석 미생성({type(exc).__name__}); 구매 구조는 미확인입니다."
        )
    return MarketReport(
        status="completed",
        dimensions=dimensions,
        commercial_analysis=commercial,
        evidence=evidence,
        opportunity_review=opportunity_review(idea, dimensions, evidence),
        unknowns=report_unknowns(idea, dimensions) + commercial_unknowns,
        search_scope=search_scope,
        data_as_of=data_as_of,
    )
