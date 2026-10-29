"""아이디어 주제어의 네이버 검색 관심도 흐름(MarketSearchTrend)을 만든다.

1. 아이디어 5개 항목에서 LLM으로 검색 주제어 1~3개를 고른다 (prompts/market_trend_terms.md).
2. 주제어 그룹과 기준 주제어(스마트공장) 그룹을 한 요청으로 조회한다 (src/ingestion/trend_client.py).
3. 월별 '주제어 ÷ 기준 × 100' 지수로 플랫폼 전체 검색량 변화를 걸러 내고, 최근 N개월 평균을
   직전 N개월과 비교해 상승·유지·둔화를 정한다.
4. 주제어 검색량이 너무 적으면 LLM이 고른 상위 범주 주제어로 한 번 더 조회한다. 그래도 적으면
   판정하지 않되, 검색량이 더 많은 쪽의 월별 지수를 참고용으로 남긴다.

검색 관심도는 시장 규모·고객 수요의 근거가 아니며, 보고서의 차원별 판정에 쓰지 않는다.
"""

import json
from datetime import date, timedelta
from pathlib import Path
from typing import Callable

from src.ingestion.trend_client import fetch_search_trend, load_trend_config
from src.retrieval.market_relevance import call_relevance_llm
from src.schemas import MarketSearchTrend, MarketTrendPoint, StructuredIdea

ROOT_DIR = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT_DIR / "prompts" / "market_trend_terms.md"
NOTE = (
    "네이버 검색 관심도를 기준 주제어 검색량 대비 지수로 나타낸 것이며, "
    "시장 규모나 고객 수요의 근거가 아닙니다."
)
# 단독으로는 주제를 가리키지 못하는 넓은 말
BROAD_TERMS = {"ai", "제조", "자동화", "스마트공장", "스마트팩토리", "공장", "솔루션"}
MAX_TERM_LENGTH = 15

LLMFn = Callable[[str, str], dict]
FetchFn = Callable[[list[dict], str, str], dict[str, dict[str, float]]]


def period_range(as_of: date, months: int) -> tuple[str, str]:
    """기준일 직전 달까지 months개월의 조회 기간 (시작일, 종료일)을 YYYY-MM-DD로 반환한다."""
    end = as_of.replace(day=1) - timedelta(days=1)
    year, month = end.year, end.month - months + 1
    while month < 1:
        year, month = year - 1, month + 12
    return f"{year}-{month:02d}-01", end.isoformat()


def month_list(start: str, end: str) -> list[str]:
    """시작일·종료일 사이의 YYYY-MM 목록."""
    year, month = int(start[:4]), int(start[5:7])
    months = []
    while f"{year}-{month:02d}" <= end[:7]:
        months.append(f"{year}-{month:02d}")
        year, month = (year + 1, 1) if month == 12 else (year, month + 1)
    return months


def clean_keywords(raw: list, max_keywords: int, reserved: list[str]) -> list[str]:
    """LLM이 고른 주제어에서 너무 길거나 넓은 말·기준 주제어·중복을 빼고 최대 max_keywords개를 남긴다."""
    blocked = BROAD_TERMS | {k.lower() for k in reserved}
    keywords = []
    for item in raw if isinstance(raw, list) else []:
        term = " ".join(str(item).split())
        if 2 <= len(term) <= MAX_TERM_LENGTH and term.lower() not in blocked:
            if term not in keywords:
                keywords.append(term)
    return keywords[:max_keywords]


def extract_trend_keywords(
    idea: StructuredIdea, config: dict, llm_fn: LLMFn = call_relevance_llm
) -> tuple[list[str], list[str]]:
    """아이디어 5개 항목에서 검색 주제어와 검색량이 적을 때 쓸 상위 범주 주제어를 고른다.

    응답 {"category", "synonyms", "broader"}에서 category를 첫 주제어로 둔다. 상위 범주는
    주제어와 겹치지 않는 것만 남긴다. 쓸 수 있는 주제어가 없으면 빈 목록.
    """
    fields = idea.model_dump(
        include={"title", "problem", "technology", "customers", "difference", "revenue"}
    )
    raw = llm_fn(
        PROMPT_PATH.read_text(encoding="utf-8"), json.dumps(fields, ensure_ascii=False)
    )
    synonyms = raw.get("synonyms")
    terms = [raw.get("category")] + (synonyms if isinstance(synonyms, list) else [])
    reserved = config["reference"]["keywords"]
    keywords = clean_keywords(terms, config["max_keywords"], reserved)
    broader = clean_keywords(
        raw.get("broader"), config["max_keywords"], reserved + keywords
    )
    return keywords, broader


def summarize_trend(
    theme: dict[str, float],
    reference: dict[str, float],
    months: list[str],
    config: dict,
) -> tuple[list[MarketTrendPoint], str, float | None, str]:
    """월별 지수와 (points, status, 최근 변화율, 방향)을 계산한다.

    주제어 평균 검색량이 min_average_ratio 미만이거나 최근 12개월 중 값이 없는 달이
    max_missing_months보다 많으면 insufficient_volume·unknown이다.
    """
    points = []
    for month in months:
        theme_ratio, ref_ratio = theme.get(month, 0.0), reference.get(month, 0.0)
        index = round(theme_ratio / ref_ratio * 100, 2) if ref_ratio else None
        points.append(
            MarketTrendPoint(
                period=month,
                theme_ratio=theme_ratio,
                reference_ratio=ref_ratio,
                relative_index=index,
            )
        )
    average = sum(p.theme_ratio for p in points) / len(points) if points else 0.0
    missing = sum(1 for m in months[-12:] if m not in theme)
    if average < config["min_average_ratio"] or missing > config["max_missing_months"]:
        return points, "insufficient_volume", None, "unknown"

    n = config["recent_months"]
    recent = [p.relative_index for p in points[-n:] if p.relative_index is not None]
    previous = [
        p.relative_index for p in points[-2 * n : -n] if p.relative_index is not None
    ]
    if not recent or not previous or not sum(previous):
        return points, "insufficient_volume", None, "unknown"
    change = round(
        (sum(recent) / len(recent)) / (sum(previous) / len(previous)) * 100 - 100, 1
    )
    threshold = config["direction_threshold_pct"]
    direction = (
        "rising"
        if change >= threshold
        else "cooling" if change <= -threshold else "stable"
    )
    return points, "completed", change, direction


def build_search_trend(
    idea: StructuredIdea,
    data_as_of: int,
    llm_fn: LLMFn = call_relevance_llm,
    fetch_fn: FetchFn | None = None,
    config: dict | None = None,
) -> MarketSearchTrend:
    """아이디어의 검색 관심도 흐름을 만든다. 주제어 선정·조회 실패는 status=error로 반환한다.

    주제어 검색량이 적으면 상위 범주 주제어로 다시 조회하고, 그 결과를 쓰면 원래 주제어를
    fallback_from에 남긴다. 둘 다 적으면 insufficient_volume이며 검색량이 더 많은 쪽의 points를 둔다.
    """
    config = config or load_trend_config()
    reference = config["reference"]
    base = {"reference_keywords": reference["keywords"], "note": NOTE}
    try:
        keywords, broader = extract_trend_keywords(idea, config, llm_fn)
        if not keywords:
            return MarketSearchTrend(
                status="error", error_message="검색 주제어를 정하지 못함", **base
            )
        as_of = date(data_as_of // 10000, data_as_of // 100 % 100, data_as_of % 100)
        start, end = period_range(as_of, config["months"])
        months = month_list(start, end)
        fetch = fetch_fn or (lambda g, s, e: fetch_search_trend(g, s, e, config))

        def query(terms: list[str]) -> dict:
            series = fetch(
                [
                    {"groupName": reference["name"], "keywords": reference["keywords"]},
                    {"groupName": "주제어", "keywords": terms},
                ],
                start,
                end,
            )
            theme = series.get("주제어", {})
            points, status, change, direction = summarize_trend(
                theme, series.get(reference["name"], {}), months, config
            )
            return {
                "status": status,
                "keywords": terms,
                "points": points,
                "recent_change_pct": change,
                "direction": direction,
                "volume": sum(theme.values()),
            }

        result = query(keywords)
        if result["status"] == "insufficient_volume" and broader:
            wider = query(broader)
            if wider["status"] == "completed" or wider["volume"] > result["volume"]:
                result = {**wider, "fallback_from": keywords}
    except Exception as exc:  # 관심도 조회 실패는 시장 보고서 전체를 막지 않는다
        return MarketSearchTrend(status="error", error_message=str(exc), **base)

    result.pop("volume")
    return MarketSearchTrend(**result, **base)
