"""관련성 판정된 시장 검색 결과로 차원별 시장 분석(MarketReport)을 생성하고 인용을 검증한다.

흐름:
    build_evidence(assessed)        관련 판정된 기사만 인용 근거(MarketEvidence)로 정리, 기사당 citation_id 1개
    allowed_verdicts(...)           충분성 상태로 쓸 수 있는 판정 제한
    generate_dimensions(...)        LLM 생성 → validate_dimension 검증 → 실패 시 오류를 알려 최대 MAX_RETRIES회 재생성
    finalize_dimension(...)         재생성 후에도 실패한 문장은 제거하고, 판정을 유지할 수 없으면 미확인으로 바꿈
    build_report(...)               MarketReport로 묶음

판정 제한 (차원별 충분성 상태 기준):
    sufficient    confirmed · signal_only · unverified (수요 confirmed는 direct_demand 근거가 있을 때만)
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
    MarketReport,
    StructuredIdea,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT_DIR / "prompts" / "market_analysis.md"
ANALYSIS_MODEL = "gpt-4o"
MAX_RETRIES = 2
MAX_CLAIMS = 3
RECENT_DAYS = 365
STALE_DAYS = 3 * 365
NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)*")
# 시장 규모·가격·비율·건수처럼 단위가 붙은 수치. 사실 문장에 있으면 기준 연도를 함께 써야 한다.
METRIC_PATTERN = re.compile(
    r"\d+(?:[.,]\d+)*\s*(%|퍼센트|배|원|만|억|조|달러|건|대|개사|곳|명|개월)"
)
YEAR_PATTERN = re.compile(r"(19|20)\d{2}")

# 시장 차원이 판정에 기대는 아이디어 항목
DEPENDENT_FIELDS = {"price": "revenue", "buyer": "customers"}

DEFAULT_CHECKS = {
    "demand": "목표 고객사 5곳 인터뷰로 현재 해결 방식과 도입 의향 확인",
    "competition": "경쟁·대체 솔루션 3개를 골라 기능·가격·도입 방식 비교",
    "price": "공급사 견적이나 공공 지원사업 단가로 도입 가격대 확인",
    "buyer": "목표 고객사의 구매 결정자와 구매 절차 확인",
    "adoption_barrier": "파일럿 고객 1곳에서 설치·운영 시 장애 요인 확인",
}

LLMFn = Callable[[str, str], dict]


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
    """충분성 상태·근거 성격·아이디어 항목 공백으로 이 차원에 쓸 수 있는 판정을 정한다."""
    if missing_field or not cited or status not in ("sufficient", "limited"):
        return ["unverified"]
    if status == "limited":
        return ["signal_only", "unverified"]
    if dimension == "demand" and not any(
        e.evidence_nature == "direct_demand" for e in cited
    ):
        return ["signal_only", "unverified"]
    return ["confirmed", "signal_only", "unverified"]


def analysis_input(
    idea: StructuredIdea,
    dimension_inputs: list[dict],
    previous_errors: dict[str, list[str]] | None = None,
) -> str:
    """분석 프롬프트에 넘길 입력 JSON(아이디어·차원별 판정 범위·근거)을 만든다."""
    data = {
        "idea": idea.model_dump(include={"title", *IDEA_FIELDS}),
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
    return f"{published.year} {published.month} {published.day}"


def numbers_in(text: str) -> set[str]:
    """문장 속 숫자를 쉼표를 뺀 문자열 집합으로 추출한다."""
    return {n.replace(",", "") for n in NUMBER_PATTERN.findall(text)}


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
    idea_text = " ".join(idea.model_dump(include={"title", *IDEA_FIELDS}).values())
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
        )
    return MarketReport(
        status="completed",
        dimensions=dimensions,
        evidence=evidence,
        unknowns=report_unknowns(idea, dimensions),
        search_scope=search_scope,
        data_as_of=data_as_of,
    )
