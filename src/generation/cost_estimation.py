"""LLM가 제안한 비용 가설을 검증 가능한 산식으로 계산한다. 금액은 견적이 아니다."""

import json
from datetime import date
from pathlib import Path
from typing import Callable

from src.schemas import (
    CostScenarioTotals,
    ImplementationCostEstimate,
    MarketReport,
    PatentReport,
    IdeaDraft,
)

ROOT = Path(__file__).resolve().parents[2]
PROMPT = ROOT / "prompts" / "cost_estimation.md"


def call_cost_llm(system_prompt: str, user_text: str) -> dict:
    from src.retrieval.market_relevance import call_relevance_llm

    return call_relevance_llm(system_prompt, user_text, model="gpt-4o-mini")


def estimate_costs(
    draft: IdeaDraft,
    market: MarketReport,
    patent: PatentReport,
    llm_fn: Callable[[str, str], dict] = call_cost_llm,
) -> ImplementationCostEstimate:
    """구현 작업·가격 가설을 제안하고, 오류 시에도 분석을 실패시키지 않는 상위용 함수."""
    if market.status != "completed" or patent.status != "completed":
        return ImplementationCostEstimate(
            status="insufficient_data",
            unknowns=[
                "특허·시장 분석이 모두 완료되지 않아 비용 범위를 제안하지 않았습니다."
            ],
        )
    allowed = {e.citation_id for e in market.evidence}
    payload = {
        "idea": draft.to_structured_idea().model_dump(),
        "market_evidence": [e.model_dump() for e in market.evidence],
        "market_review": (
            market.commercial_analysis.model_dump()
            if market.commercial_analysis
            else None
        ),
        "patent_status": patent.status,
        "today": date.today().isoformat(),
    }
    try:
        raw = llm_fn(
            PROMPT.read_text(encoding="utf-8"), json.dumps(payload, ensure_ascii=False)
        )
        estimate = ImplementationCostEstimate.model_validate(raw)
        if (
            not set(cid for item in estimate.items for cid in item.citation_ids)
            <= allowed
        ):
            raise ValueError("비용 가정이 존재하지 않는 시장 인용 ID를 참조합니다")
        if estimate.status == "estimated" and not estimate.items:
            raise ValueError("estimated 상태에는 최소 한 개 비용 항목이 필요합니다")
        return estimate
    except Exception as exc:
        return ImplementationCostEstimate(
            status="error", unknowns=[f"LLM 비용 추정 검증 실패: {type(exc).__name__}"]
        )


def calculate_scenarios(estimate: ImplementationCostEstimate) -> CostScenarioTotals:
    """수량×단가 산식으로 초기·월 반복비와 손익분기 수량을 결정론적으로 계산."""
    totals = {
        kind: {scenario: 0.0 for scenario in ("low", "base", "high")}
        for kind in ("one_time", "monthly", "annual")
    }
    for item in estimate.items:
        for scenario in ("low", "base", "high"):
            totals[item.cost_type][scenario] += item.quantity * getattr(
                item, f"{scenario}_unit_cost"
            )
    monthly = {
        s: totals["monthly"][s] + totals["annual"][s] / 12
        for s in ("low", "base", "high")
    }
    price, variable = estimate.revenue_unit_price, estimate.variable_cost_per_unit
    if price is not None and variable is not None and price > variable:
        contribution = price - variable
        be = {
            s: int(
                __import__("math").ceil(
                    (totals["one_time"][s] + monthly[s]) / contribution
                )
            )
            for s in ("low", "base", "high")
        }
        note = "초기 구축비와 첫 달 반복비 기준의 단순 손익분기 판매량이며, 세금·할인·현금흐름은 제외합니다."
    else:
        be = {s: None for s in ("low", "base", "high")}
        note = "판매 단가와 단위 변동비가 검증되지 않아 손익분기 판매량을 계산하지 않았습니다."
    return CostScenarioTotals(
        initial_low=totals["one_time"]["low"],
        initial_base=totals["one_time"]["base"],
        initial_high=totals["one_time"]["high"],
        recurring_monthly_low=monthly["low"],
        recurring_monthly_base=monthly["base"],
        recurring_monthly_high=monthly["high"],
        break_even_units_low=be["low"],
        break_even_units_base=be["base"],
        break_even_units_high=be["high"],
        calculation_note=note,
    )
