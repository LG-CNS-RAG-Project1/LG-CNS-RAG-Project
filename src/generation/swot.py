"""특허·시장 조사 결과로 아이디어의 예비 SWOT(강점·약점·기회·위협)을 만든다.

새 자료를 찾지 않고 PatentReport·MarketReport만 요약해 LLM 1회로 사분면 항목을 고른 뒤, 코드가
항목을 검증한다. 검증에 실패한 항목은 버리고 그 수를 dropped에 남긴다.

- 근거(evidence) 항목은 입력에 있는 근거 ID가 1개 이상 있어야 한다. 시장 M:번호, 특허 P:번호,
  검색 관심도 T, 기업 재무 현황 F를 인용할 수 있다.
- 숫자는 인용한 근거·아이디어 입력에 그대로 있어야 한다.
- 수요 확인·입증 같은 단정 표현은 쓰지 않는다 (뉴스·공시·관심도·조달 공고는 사업 신호).
"""

import json
import re
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field

from src.schemas import IdeaDraft, MarketReport, PatentReport

ROOT_DIR = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT_DIR / "prompts" / "idea_swot.md"
QUADRANTS = ("strengths", "weaknesses", "opportunities", "threats")
QUADRANT_LABELS = {
    "strengths": "강점 (S)",
    "weaknesses": "약점 (W)",
    "opportunities": "기회 (O)",
    "threats": "위협 (T)",
}
BASIS_LABELS = {
    "evidence": "근거 확인",
    "user_claim": "사용자 주장",
    "ai_hypothesis": "검증 전 가설",
}
MAX_ITEMS = 3
MAX_TEXT = 120
MAX_MARKET_EVIDENCE = 20
MAX_PATENT_EVIDENCE = 12
QUOTE_CHARS = 300
NOTE = (
    "특허·시장 조사 결과를 아이디어 관점으로 정리한 예비 SWOT입니다. 근거 ID가 없는 항목은 "
    "사용자 주장이거나 검증 전 가설이며, 사업 성공·특허 등록 가능성을 판단하지 않습니다."
)
# 사업 신호를 수요 확인·시장 성장으로 바꿔 쓰는 단정 표현
OVERCLAIM_RE = re.compile(
    r"시장\s*수요|수요가?\s*(?:확인|증가|확대|늘|안정|존재|있)|구매\s*의사가?\s*확인|입증"
    r"|시장이?\s*(?:성장|커지|확대)"
)
NUMBER_RE = re.compile(r"\d[\d,]*(?:\.\d+)?")
# 검색 관심도(T)를 인용한 문장의 방향 표현과 search_trend.direction이 맞아야 한다
TREND_WORDS = {
    "rising": re.compile(r"상승|증가|늘"),
    "cooling": re.compile(r"둔화|감소|하락|줄"),
}
# '정하지 않음' 약점은 실제로 빈 아이디어 항목에만 쓴다
UNDEFINED_RE = re.compile(r"정의되지|정해지지|정하지|미정|불명확|명확하지|없다|빠져")
FIELD_WORDS = {
    "customers": re.compile(r"고객"),
    "revenue": re.compile(r"수익\s*모델|과금|수익원"),
    "difference": re.compile(r"차별점|차별화"),
}
FIELD_LABELS = {
    "customers": "고객",
    "revenue": "수익모델",
    "difference": "차별점",
    "current_alternative": "현재 대안",
    "target_segment": "목표 세그먼트",
}

LLMFn = Callable[[str, str], dict]


class SwotItem(BaseModel):
    text: str
    basis: Literal["evidence", "user_claim", "ai_hypothesis"]
    citation_ids: list[str] = Field(default_factory=list)


class SwotAnalysis(BaseModel):
    """아이디어 관점 예비 SWOT. 사분면마다 최대 3개."""

    status: Literal["completed", "insufficient", "error"]
    strengths: list[SwotItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    weaknesses: list[SwotItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    opportunities: list[SwotItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    threats: list[SwotItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    dropped: int = 0  # 검증에 실패해 버린 항목 수
    note: str = NOTE
    error_message: str | None = None


def _idea_digest(draft: IdeaDraft) -> dict:
    """아이디어 항목과 사용자가 정하지 않은 항목 목록(missing_fields, 한국어 이름)."""
    fields = (
        "title",
        "problem",
        "technology",
        "customers",
        "difference",
        "revenue",
        "current_alternative",
        "target_segment",
    )
    digest = {field: getattr(draft, field, "") or "" for field in fields}
    digest["missing_fields"] = [
        label for field, label in FIELD_LABELS.items() if not digest[field]
    ]
    return digest


def _market_digest(market: MarketReport) -> tuple[dict, dict[str, str]]:
    """LLM 입력용 시장 요약과 인용 ID별 원문 텍스트(숫자 검증용)."""
    from src.generation.market_markdown import (
        NATURE_LABELS,
        VERDICT_LABELS,
        procurement_summary,
        search_trend_summary,
    )
    from src.retrieval.market_relevance import DIMENSION_LABELS

    sources: dict[str, str] = {}
    evidence = []
    for item in market.evidence[:MAX_MARKET_EVIDENCE]:
        cid = f"M:{item.citation_id}"
        quote = " ".join(item.quote.split())[:QUOTE_CHARS]
        sources[cid] = f"{item.title} {quote} {item.period or ''} {item.published_at}"
        evidence.append(
            {
                "id": cid,
                "source_type": item.source_type,
                "nature": NATURE_LABELS.get(item.evidence_nature, item.evidence_nature),
                "title": item.title,
                "quote": quote,
            }
        )
    dimensions = [
        {
            "dimension": DIMENSION_LABELS.get(d.dimension, d.dimension),
            "verdict": VERDICT_LABELS.get(d.verdict, d.verdict),
            "limitation": d.limitation or "",
            "claims": [
                {
                    "text": c.statement,
                    "citation_ids": [f"M:{i}" for i in c.citation_ids],
                }
                for c in d.claims
            ],
        }
        for d in market.dimensions
    ]
    digest: dict = {
        "status": market.status,
        "evidence": evidence,
        "dimensions": dimensions,
    }
    trend = getattr(market, "search_trend", None)
    if trend is not None:
        summary = search_trend_summary(trend)
        sources["T"] = summary
        digest["search_trend"] = {"id": "T", "summary": summary}
    procurement = getattr(market, "procurement", None)
    if procurement is not None:
        digest["procurement"] = procurement_summary(procurement)
    financials = getattr(market, "company_financials", None)
    if financials is not None and financials.companies:
        rows = []
        for company in financials.companies:
            latest = company.years[-1] if company.years else None
            if latest is None:
                continue
            rows.append(
                {
                    "company": company.company,
                    "year": latest.year,
                    "revenue_eok": (
                        round(latest.revenue / 1e8) if latest.revenue else None
                    ),
                    "operating_income_eok": (
                        round(latest.operating_income / 1e8)
                        if latest.operating_income is not None
                        else None
                    ),
                }
            )
        sources["F"] = json.dumps(rows, ensure_ascii=False)
        digest["company_financials"] = {"id": "F", "companies": rows}
    return digest, sources


def _patent_digest(patent: PatentReport) -> tuple[dict, dict[str, str]]:
    """LLM 입력용 특허 요약과 인용 ID별 원문 텍스트(숫자 검증용)."""
    sources: dict[str, str] = {}
    evidence = []
    for item in patent.evidence[:MAX_PATENT_EVIDENCE]:
        cid = f"P:{item.citation_id}"
        quote = " ".join(item.quote.split())[:QUOTE_CHARS]
        sources[cid] = f"{item.title} {quote}"
        evidence.append(
            {"id": cid, "title": item.title, "section": item.section, "quote": quote}
        )
    comparisons = [
        {
            "component": comparison.idea_component,
            "status": comparison.status,
            "difference": comparison.difference,
            "citation_ids": [f"P:{i}" for i in comparison.citation_ids],
        }
        for review in patent.patent_reviews
        for comparison in review.component_comparisons
    ]
    precheck = patent.patentability_precheck
    digest: dict = {
        "status": patent.status,
        "evidence": evidence,
        "component_comparisons": comparisons,
    }
    if precheck is not None:
        digest["precheck"] = {
            "status": precheck.status,
            "summary": precheck.summary,
            "citation_ids": [f"P:{i}" for i in precheck.citation_ids],
            "distinction_hypotheses": precheck.distinction_hypotheses,
        }
    return digest, sources


def _numbers_supported(text: str, corpus: str) -> bool:
    """문장의 숫자가 모두 corpus(인용 원문·아이디어)에 그대로 있는지. 쉼표는 무시한다."""
    flat = corpus.replace(",", "")
    return all(n.replace(",", "") in flat for n in NUMBER_RE.findall(text))


def _trend_consistent(text: str, ids: list[str], trend_direction: str | None) -> bool:
    """검색 관심도(T)를 인용한 문장이 실제 방향과 반대되는 표현을 쓰지 않는지."""
    if "T" not in ids or trend_direction is None:
        return True
    return not any(
        pattern.search(text)
        for direction, pattern in TREND_WORDS.items()
        if direction != trend_direction
    )


def _undefined_claim_valid(text: str, missing_fields: set[str]) -> bool:
    """'항목을 정하지 않았다'는 문장이 실제로 빈 아이디어 항목만 가리키는지."""
    if not UNDEFINED_RE.search(text):
        return True
    named = {field for field, pattern in FIELD_WORDS.items() if pattern.search(text)}
    return named <= missing_fields


def validate_items(
    raw_items,
    allowed: dict[str, str],
    idea_text: str,
    trend_direction: str | None = None,
    missing_fields: set[str] | None = None,
) -> tuple[list[SwotItem], int]:
    """LLM 항목을 검증해 (통과 항목 최대 MAX_ITEMS개, 버린 수)를 반환한다.

    알 수 없는 근거 ID는 지우고, 다음 항목은 버린다: 근거 항목에 남은 ID가 없음, 숫자가 인용
    원문·아이디어에 없음, 수요 확인·증가·시장 성장 단정 표현, 검색 관심도(T)를 인용하면서 실제
    방향(trend_direction)과 반대 표현, 채워진 아이디어 항목을 '정하지 않았다'고 씀.
    user_claim은 근거 ID를 쓰지 않는다.
    """
    missing_fields = missing_fields or set()
    kept, dropped = [], 0
    for raw in raw_items if isinstance(raw_items, list) else []:
        try:
            item = SwotItem.model_validate(raw)
        except Exception:
            dropped += 1
            continue
        text = " ".join(item.text.split())
        ids = [str(i).strip() for i in item.citation_ids]
        ids = [i for i in dict.fromkeys(ids) if i in allowed]
        if item.basis == "user_claim":
            ids = []
        corpus = idea_text + " " + " ".join(allowed[i] for i in ids)
        if (
            not text
            or len(text) > MAX_TEXT
            or (item.basis == "evidence" and not ids)
            or OVERCLAIM_RE.search(text)
            or not _numbers_supported(text, corpus)
            or not _trend_consistent(text, ids, trend_direction)
            or not _undefined_claim_valid(text, missing_fields)
        ):
            dropped += 1
            continue
        kept.append(SwotItem(text=text, basis=item.basis, citation_ids=ids))
    return kept[:MAX_ITEMS], dropped + max(len(kept) - MAX_ITEMS, 0)


def build_swot(
    draft: IdeaDraft,
    patent: PatentReport,
    market: MarketReport,
    llm_fn: LLMFn,
) -> SwotAnalysis:
    """두 조사 결과로 예비 SWOT을 만든다.

    두 조사가 모두 결과 없음·오류면 LLM을 부르지 않고 insufficient, 남은 항목이 없어도
    insufficient, LLM 호출·응답 형식 실패는 error다.
    """
    failed = {"error", "no_results"}
    if market.status in failed and patent.status in failed:
        return SwotAnalysis(
            status="insufficient",
            error_message="특허·시장 조사 결과가 모두 없어 SWOT을 만들지 않았습니다.",
        )
    idea = _idea_digest(draft)
    market_digest, market_sources = _market_digest(market)
    patent_digest, patent_sources = _patent_digest(patent)
    allowed = {**market_sources, **patent_sources}
    payload = {"idea": idea, "market": market_digest, "patent": patent_digest}
    try:
        raw = llm_fn(
            PROMPT_PATH.read_text(encoding="utf-8"),
            json.dumps(payload, ensure_ascii=False),
        )
        if not isinstance(raw, dict):
            raise ValueError("SWOT 응답이 JSON 객체가 아닙니다")
    except Exception as exc:  # SWOT 실패는 종합 보고서 나머지를 막지 않는다
        return SwotAnalysis(status="error", error_message=str(exc))

    idea_text = " ".join(v for k, v in idea.items() if k != "missing_fields")
    trend = getattr(market, "search_trend", None)
    trend_direction = trend.direction if trend is not None else None
    missing = {field for field in FIELD_LABELS if not idea[field]}
    quadrants, dropped = {}, 0
    for name in QUADRANTS:
        quadrants[name], lost = validate_items(
            raw.get(name), allowed, idea_text, trend_direction, missing
        )
        dropped += lost
    status = "completed" if any(quadrants.values()) else "insufficient"
    return SwotAnalysis(status=status, dropped=dropped, **quadrants)


def swot_markdown_lines(swot: SwotAnalysis | None) -> list[str]:
    """종합 보고서용 'SWOT 분석 (예비)' 마크다운 줄. swot이 없으면 빈 목록."""
    if swot is None:
        return []
    from src.generation.market_markdown import cell

    lines = ["", "## SWOT 분석 (예비)", ""]
    if swot.status != "completed":
        reason = swot.error_message or "검증을 통과한 항목이 없습니다."
        return lines + [f"- SWOT을 만들지 못했습니다. ({cell(reason)})"]
    for name in QUADRANTS:
        items = getattr(swot, name)
        lines.append(f"**{QUADRANT_LABELS[name]}**")
        if not items:
            lines.append("- 확인된 항목 없음")
        for item in items:
            refs = f", {', '.join(item.citation_ids)}" if item.citation_ids else ""
            lines.append(
                f"- {cell(item.text)} ({BASIS_LABELS[item.basis]}{cell(refs)})"
            )
        lines.append("")
    lines.append(f"> {cell(swot.note)}")
    return lines
