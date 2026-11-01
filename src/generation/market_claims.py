"""시장 분석 문장의 인용·수치 검증과 차원 판정 규칙."""

import re
from datetime import date, datetime

from src.generation.idea_parser import FIELD_LABELS
from src.schemas import MarketDimensionResult, MarketEvidence, StructuredIdea

MAX_CLAIMS = 3
NUMBER_PATTERN = re.compile(r"\d+(?:[.,]\d+)*")
METRIC_PATTERN = re.compile(
    r"\d+(?:[.,]\d+)*\s*(%|퍼센트|배|원|만|억|조|달러|건|대|개사|곳|명|개월)"
)
YEAR_PATTERN = re.compile(r"(?<!\d)(?:19|20)\d{2}년")
CERTAINTY_PATTERN = re.compile(r"확인(?:되었|됐|된다|된\s)|입증|증명")
DEPENDENT_FIELDS = {"price": "revenue", "buyer": "customers"}
SIGNAL_ONLY_NATURES = {"business_signal", "company_claim", "estimate"}
PUBLIC_CUSTOMER_TERMS = (
    "공공",
    "기관",
    "정부",
    "지자체",
    "대학",
    "학교",
    "연구",
    "교육",
)
DEFAULT_CHECKS = {
    "demand": "목표 고객사 5곳 인터뷰로 현재 해결 방식과 도입 의향 확인",
    "competition": "경쟁·대체 솔루션 3개를 골라 기능·가격·도입 방식 비교",
    "price": "공급사 견적이나 공공 지원사업 단가로 도입 가격대 확인",
    "buyer": "목표 고객사의 구매 결정자와 구매 절차 확인",
    "adoption_barrier": "파일럿 고객 1곳에서 설치·운영 시 장애 요인 확인",
}


def _to_date(value: int) -> date:
    return datetime.strptime(str(value), "%Y%m%d").date()


def missing_dependent_field(idea: StructuredIdea, dimension: str) -> str | None:
    """차원이 기대는 아이디어 항목이 비어 있으면 그 항목 이름(한국어)을 반환한다."""
    field = DEPENDENT_FIELDS.get(dimension)
    return FIELD_LABELS[field] if field and not getattr(idea, field) else None


def allowed_verdicts(
    dimension: str,
    status: str,
    cited: list[MarketEvidence],
    missing_field: str | None = None,
    confirmable: list[MarketEvidence] | None = None,
) -> list[str]:
    """충분성 상태·근거 성격·아이디어 항목 공백으로 이 차원에 쓸 수 있는 판정을 정한다.

    confirmed는 확인 가능한 성격의 근거가 있을 때만 허용한다: 수요는 direct_demand,
    그 밖의 차원은 SIGNAL_ONLY_NATURES(사업 신호·기업 주장·추정치)가 아닌 근거.
    confirmable을 주면 cited 중 confirmed 근거로 볼 수 있는 것을 그 목록으로 좁힌다.
    """
    if missing_field or not cited or status not in ("sufficient", "limited"):
        return ["unverified"]
    if status == "limited":
        return ["signal_only", "unverified"]
    candidates = cited if confirmable is None else confirmable
    if not any(confirms(dimension, e) for e in candidates):
        return ["signal_only", "unverified"]
    return ["confirmed", "signal_only", "unverified"]


def confirms(dimension: str, evidence: MarketEvidence) -> bool:
    """이 근거가 차원의 confirmed를 뒷받침할 수 있는 성격인지 판단한다."""
    if dimension == "demand":
        return evidence.evidence_nature == "direct_demand"
    return evidence.evidence_nature not in SIGNAL_ONLY_NATURES


def has_confirming_fact(
    dimension: str, claims: list[dict], by_id: dict[int, MarketEvidence]
) -> bool:
    """confirmed를 뒷받침하는 성격의 근거를 인용한 fact 문장이 있는지 확인한다."""
    return any(
        confirms(dimension, by_id[i])
        for c in claims
        if c.get("claim_type") == "fact"
        for i in c.get("citation_ids") or []
        if i in by_id
    )


def public_target(idea: StructuredIdea) -> bool:
    """아이디어 고객 항목이 공공기관·대학·연구기관 같은 공공 부문을 가리키는지 판단한다."""
    return any(term in (idea.customers or "") for term in PUBLIC_CUSTOMER_TERMS)


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


def disclosing_company(evidence: MarketEvidence) -> str | None:
    """DART 근거면 공시 기업명(publisher의 '(DART 사업보고서)' 앞부분), 그 밖은 None."""
    if evidence.source_type != "dart":
        return None
    return evidence.publisher.split(" (DART")[0].strip() or None


def attribute_dart(claim: dict, by_id: dict[int, MarketEvidence]) -> dict:
    """DART를 인용했는데 공시 기업명이 없는 문장 앞에 '기업 사업보고서(FY연도)에 따르면'을 붙인다.

    기업 주장이 시장 전체의 사실처럼 읽히지 않게 한다. 인용 ID가 근거에 없으면 그대로 둔다.
    """
    statement = str(claim.get("statement", "")).strip()
    cited = [
        by_id[i]
        for i in claim.get("citation_ids") or []
        if isinstance(i, int) and i in by_id
    ]
    reports = dict.fromkeys(
        (disclosing_company(e), e.period) for e in cited if disclosing_company(e)
    )
    missing = [(c, p) for c, p in reports if c not in statement]
    if not statement or not missing:
        return claim
    prefix = "·".join(
        f"{c} 사업보고서({p})" if p else f"{c} 사업보고서" for c, p in missing
    )
    return {**claim, "statement": f"{prefix}에 따르면 {statement}"}


def attribute_procurement(claim: dict, by_id: dict[int, MarketEvidence]) -> dict:
    """나라장터 공고를 인용했는데 4자리 기준 연도가 없는 문장 앞에 공고 기간을 붙인다.

    공고 근거의 period('2026년 4월~2026년 9월' 등)를 써서 금액 문장의 기준 시점 검증을 통과하게 한다.
    문장에 이미 '나라장터'가 있으면 기간만 붙인다.
    """
    statement = str(claim.get("statement", "")).strip()
    periods = dict.fromkeys(
        by_id[i].period
        for i in claim.get("citation_ids") or []
        if isinstance(i, int)
        and i in by_id
        and by_id[i].source_type == "procurement"
        and by_id[i].period
    )
    if not statement or not periods or YEAR_PATTERN.search(statement):
        return claim
    period = "·".join(periods)
    prefix = period if "나라장터" in statement else f"나라장터 입찰공고({period}) 기준"
    return {**claim, "statement": f"{prefix} {statement}"}


def claim_errors(
    claim: dict, allowed_ids: set[int], by_id: dict[int, MarketEvidence], idea_text: str
) -> list[str]:
    """문장 1개의 검증 오류 목록. 빈 목록이면 통과다.

    - 문장 유형이 fact·user_claim·ai_hypothesis 중 하나인지
    - fact는 인용이 1개 이상이고 모두 이 차원의 근거 ID인지
    - user_claim·ai_hypothesis가 "확인되었다"처럼 확인된 사실로 쓰이지 않았는지
    - DART 사업보고서를 인용하면 문장에 공시 기업명이 있는지 (기업 주장을 시장 사실로 쓰지 않게)
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
    if claim_type != "fact" and CERTAINTY_PATTERN.search(statement):
        return [f"{claim_type} 문장을 확인된 사실처럼 씀: {statement}"]
    unknown = [i for i in citation_ids if i not in allowed_ids]
    if unknown:
        return [f"이 차원의 근거에 없는 인용 {unknown}: {statement}"]
    unnamed = [
        company
        for company in dict.fromkeys(disclosing_company(by_id[i]) for i in citation_ids)
        if company and company not in statement
    ]
    if unnamed:
        return [
            f"DART 공시 내용은 공시 기업({', '.join(unnamed)})을 주어로 써야 함: {statement}"
        ]

    sources = (
        idea_text
        + " "
        + " ".join(
            f"{by_id[i].title} {by_id[i].quote} {publication_date_text(by_id[i])}"
            f" {by_id[i].period or ''}"
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
    claims = [
        (
            attribute_procurement(attribute_dart(c, by_id), by_id)
            if isinstance(c, dict)
            else c
        )
        for c in raw.get("claims") or []
    ]
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
    elif verdict == "confirmed" and not has_confirming_fact(
        str(raw.get("dimension")), claims, by_id
    ):
        errors.append(
            "confirmed 판정의 fact 문장이 구매 신호·간접 수요 근거를 인용하지 않음"
        )
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
    attributed = [
        attribute_procurement(attribute_dart(c, by_id), by_id)
        for c in raw.get("claims") or []
        if isinstance(c, dict)
    ]
    claims = [
        {
            "statement": " ".join(str(c["statement"]).split()),
            "claim_type": c["claim_type"],
            "citation_ids": list(dict.fromkeys(c.get("citation_ids") or [])),
        }
        for c in attributed
        if not claim_errors(c, allowed_ids, by_id, idea_text)
    ]
    hypotheses = [c for c in claims if c["claim_type"] == "ai_hypothesis"]
    claims = [c for c in claims if c["claim_type"] != "ai_hypothesis"] + hypotheses[:1]
    claims = claims[:MAX_CLAIMS]

    verdict = raw.get("verdict")
    has_fact = any(c["claim_type"] == "fact" for c in claims)
    if verdict == "confirmed" and not has_confirming_fact(dimension, claims, by_id):
        verdict = "signal_only"
    if verdict not in allowed or (verdict != "unverified" and not has_fact):
        verdict = "unverified"
    next_check = " ".join(str(raw.get("next_check") or "").split()) or None
    if verdict == "unverified" and not next_check:
        next_check = default_check or DEFAULT_CHECKS[dimension]
    return MarketDimensionResult(
        dimension=dimension, verdict=verdict, claims=claims, next_check=next_check
    )
