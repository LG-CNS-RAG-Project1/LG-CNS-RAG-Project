"""아이디어 입력과 특허·시장 조사 결과로 예비 비즈니스 모델 캔버스(9개 블록)를 만든다.

새 자료를 찾지 않고 아이디어 항목·MarketReport·PatentReport·구축 비용 추정만 요약해 LLM 1회로
블록 내용을 채운 뒤, SWOT과 같은 규칙(src.generation.swot.validate_items)으로 항목을 검증한다.

- 아이디어에 적힌 내용은 user_claim, 조사 근거로 확인한 내용은 evidence(근거 ID 필수),
  입력에 없는 블록(채널·고객 관계·핵심 파트너 등)은 아이디어에 맞춘 ai_hypothesis로 채운다.
- 구축 비용 추정(C)은 LLM 추정치이므로 C만 인용한 항목은 evidence가 아니라 ai_hypothesis로 둔다.
"""

import json
from pathlib import Path
from typing import Callable, Literal

from pydantic import BaseModel, Field

from src.generation.swot import (
    FIELD_LABELS,
    SwotItem,
    _idea_digest,
    _market_digest,
    _patent_digest,
    validate_items,
)
from src.schemas import IdeaDraft, MarketReport, PatentReport

ROOT_DIR = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT_DIR / "prompts" / "business_canvas.md"
BLOCKS = (
    "key_partners",
    "key_activities",
    "key_resources",
    "value_propositions",
    "customer_relationships",
    "channels",
    "customer_segments",
    "cost_structure",
    "revenue_streams",
)
BLOCK_LABELS = {
    "key_partners": "핵심 파트너",
    "key_activities": "핵심 활동",
    "key_resources": "핵심 자원",
    "value_propositions": "가치 제안",
    "customer_relationships": "고객 관계",
    "channels": "채널",
    "customer_segments": "고객 세그먼트",
    "cost_structure": "비용 구조",
    "revenue_streams": "수익원",
}
MAX_ITEMS = 3
NOTE = (
    "아이디어 입력과 특허·시장 조사 결과를 비즈니스 모델 캔버스로 정리한 예비 초안입니다. "
    "'가설' 표시는 검증 전 AI 제안이고, 근거 ID가 붙은 항목만 조사 자료로 확인한 내용입니다."
)

LLMFn = Callable[[str, str], dict]
CanvasItem = SwotItem


class BusinessCanvas(BaseModel):
    """예비 비즈니스 모델 캔버스. 블록마다 최대 3개."""

    status: Literal["completed", "insufficient", "error"]
    key_partners: list[CanvasItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    key_activities: list[CanvasItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    key_resources: list[CanvasItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    value_propositions: list[CanvasItem] = Field(
        default_factory=list, max_length=MAX_ITEMS
    )
    customer_relationships: list[CanvasItem] = Field(
        default_factory=list, max_length=MAX_ITEMS
    )
    channels: list[CanvasItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    customer_segments: list[CanvasItem] = Field(
        default_factory=list, max_length=MAX_ITEMS
    )
    cost_structure: list[CanvasItem] = Field(default_factory=list, max_length=MAX_ITEMS)
    revenue_streams: list[CanvasItem] = Field(
        default_factory=list, max_length=MAX_ITEMS
    )
    dropped: int = 0  # 검증에 실패해 버린 항목 수
    note: str = NOTE
    error_message: str | None = None


def _cost_digest(cost_estimate) -> tuple[dict | None, dict[str, str]]:
    """구축 비용 추정 요약(id C, 금액은 만원 단위 정수)과 숫자 검증용 원문."""
    if cost_estimate is None or cost_estimate.status != "estimated":
        return None, {}
    items = [
        {
            "name": item.name,
            "cost_type": item.cost_type,
            "base_total_manwon": round(item.base_unit_cost * item.quantity / 1e4),
        }
        for item in cost_estimate.items
    ]
    digest = {"id": "C", "items": items, "assumptions": cost_estimate.assumptions}
    return digest, {"C": json.dumps(items, ensure_ascii=False)}


def build_business_canvas(
    draft: IdeaDraft,
    patent: PatentReport,
    market: MarketReport,
    llm_fn: LLMFn,
    cost_estimate=None,
    technical_components: list[str] | None = None,
) -> BusinessCanvas:
    """아이디어·조사 결과로 예비 비즈니스 모델 캔버스를 만든다.

    technical_components를 주면 draft의 구성요소 대신 쓴다(화면에서 확정한 핵심 구성).
    남은 항목이 없으면 insufficient, LLM 호출·응답 형식 실패는 error다.
    """
    idea = _idea_digest(draft)
    components = (
        technical_components
        if technical_components is not None
        else draft.technical_components
    )
    lists = {
        "technical_components": list(components),
        "value_hypotheses": list(draft.value_hypotheses),
    }
    market_digest, market_sources = _market_digest(market)
    patent_digest, patent_sources = _patent_digest(patent)
    cost_digest, cost_sources = _cost_digest(cost_estimate)
    allowed = {**market_sources, **patent_sources, **cost_sources}
    payload = {
        "idea": {**idea, **lists},
        "market": market_digest,
        "patent": patent_digest,
        "cost_estimate": cost_digest,
    }
    try:
        raw = llm_fn(
            PROMPT_PATH.read_text(encoding="utf-8"),
            json.dumps(payload, ensure_ascii=False),
        )
        if not isinstance(raw, dict):
            raise ValueError("캔버스 응답이 JSON 객체가 아닙니다")
    except Exception as exc:  # 캔버스 실패는 종합 보고서 나머지를 막지 않는다
        return BusinessCanvas(status="error", error_message=str(exc))

    idea_text = " ".join(
        [v for k, v in idea.items() if k != "missing_fields"]
        + [text for values in lists.values() for text in values]
    )
    trend = getattr(market, "search_trend", None)
    trend_direction = trend.direction if trend is not None else None
    missing = {field for field in FIELD_LABELS if not idea[field]}
    blocks, dropped = {}, 0
    for name in BLOCKS:
        items, lost = validate_items(
            raw.get(name), allowed, idea_text, trend_direction, missing
        )
        blocks[name] = [
            (
                item.model_copy(update={"basis": "ai_hypothesis"})
                if item.basis == "evidence" and set(item.citation_ids) == {"C"}
                else item
            )
            for item in items
        ]
        dropped += lost
    status = "completed" if any(blocks.values()) else "insufficient"
    return BusinessCanvas(status=status, dropped=dropped, **blocks)


def item_suffix(item: CanvasItem) -> str:
    """항목 뒤에 붙일 짧은 출처 표시. 아이디어 입력은 표시하지 않는다."""
    refs = ", ".join(item.citation_ids)
    if item.basis == "ai_hypothesis":
        return f"가설 · {refs}" if refs else "가설"
    return refs


def canvas_markdown_lines(canvas: BusinessCanvas | None) -> list[str]:
    """종합 보고서용 '비즈니스 모델 캔버스 (예비)' 마크다운 줄. canvas가 없으면 빈 목록."""
    if canvas is None:
        return []
    from src.generation.market_markdown import cell

    lines = ["", "## 비즈니스 모델 캔버스 (예비)", ""]
    if canvas.status != "completed":
        reason = canvas.error_message or "검증을 통과한 항목이 없습니다."
        return lines + [f"- 캔버스를 만들지 못했습니다. ({cell(reason)})"]
    lines += ["| 블록 | 내용 |", "|---|---|"]
    for name in BLOCKS:
        parts = []
        for item in getattr(canvas, name):
            suffix = item_suffix(item)
            parts.append(cell(item.text) + (f" ({cell(suffix)})" if suffix else ""))
        lines.append(f"| {BLOCK_LABELS[name]} | {'<br>'.join(parts) or '-'} |")
    lines += ["", f"> {cell(canvas.note)}"]
    return lines
