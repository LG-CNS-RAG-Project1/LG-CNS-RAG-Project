"""아이디어 주제어로 나라장터 입찰공고를 찾아 공공 조달 사례(MarketProcurement)를 만든다.

1. 검색 관심도에서 고른 주제어(대표 범주 + 다른 이름)로 기준일 직전 달까지 months개월의 물품·용역
   입찰공고를 달마다 조회한다 (src/ingestion/procurement_client.py).
2. 같은 공고번호는 마지막 차수 1건만 남기고, 번호가 바뀌는 재공고는 '(재공고)'·'[번호]' 같은 머리말을
   뺀 공고명과 수요기관이 같으면 최근 1건만 남긴다. 취소공고는 뺀다.
3. 공고명에 주제어 글자만 들어간 다른 물건을 거르기 위해 LLM이 공고명·세부품명으로 같은 제품·서비스
   범주인지 판정한다 (prompts/market_procurement_relevance.md).
4. 수요기관 이름으로 구매 주체 유형(민간 기업·대학·학교·연구기관·공공기관)을 나눈다.

공공 조달은 공공기관·대학·연구기관의 구매가 대부분이라 민간 고객 수요의 근거가 아니며, 차원별 판정에
쓰지 않는다.
"""

import json
import re
from datetime import date
from pathlib import Path
from typing import Callable

from src.ingestion.procurement_client import (
    fetch_bid_notices,
    load_procurement_config,
)
from src.retrieval.market_relevance import call_relevance_llm
from src.schemas import MarketProcurement, ProcurementNotice, StructuredIdea

ROOT_DIR = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT_DIR / "prompts" / "market_procurement_relevance.md"
NOTE = (
    "나라장터 공공 입찰공고입니다. 공공기관·대학·연구기관의 구매가 대부분이어서 민간 고객 수요의 근거가 "
    "아니며, 공공 구매 사례와 예산 수준을 참고하는 자료입니다."
)
CANCELLED = "취소"
# 공고명 앞의 재공고·긴급·내부 번호 머리말: (재공고) (재) 수의)(재) [52251] [긴급] (새로운공고)
_TITLE_PREFIX_RE = re.compile(r"^(?:\s*(?:\[[^\]]*\]|\([^)]*\)|[^()\[\]\s]{1,4}\)))+")
# 공고명 어디에나 붙는 재공고 표시
_RENOTICE_RE = re.compile(r"\((?:재공고|재|긴급|긴급공고)\)")

FetchFn = Callable[[str, str, str], list[dict]]  # (주제어, 공고 종류, YYYYMM) → 공고
LLMFn = Callable[[str, str], dict]


def recent_months(as_of: date, months: int) -> list[str]:
    """기준일이 속한 달을 빼고 직전 months개월을 오래된 달부터 'YYYYMM'으로 반환한다."""
    year, month = as_of.year, as_of.month
    result = []
    for _ in range(months):
        year, month = (year - 1, 12) if month == 1 else (year, month - 1)
        result.append(f"{year}{month:02d}")
    return result[::-1]


def buyer_type(buyer: str, config: dict) -> str:
    """수요기관 이름에 들어간 말로 구매 주체 유형을 정한다. 맞는 유형이 없으면 기본 유형."""
    for item in config["buyer_types"]:
        if any(term in buyer for term in item["terms"]):
            return item["name"]
    return config["default_buyer_type"]


def _amount(value) -> int | None:
    text = str(value or "").replace(",", "").strip()
    return int(float(text)) if text and text.replace(".", "").isdigit() else None


def to_notice(raw: dict, config: dict) -> ProcurementNotice:
    """API 공고 dict를 ProcurementNotice로 바꾼다. 예산은 배정예산, 없으면 추정가격."""
    budget = _amount(raw.get("asignBdgtAmt")) or _amount(raw.get("presmptPrce"))
    return ProcurementNotice(
        notice_no=f"{raw['bidNtceNo']}-{raw.get('bidNtceOrd') or '000'}",
        title=" ".join(str(raw.get("bidNtceNm", "")).split()),
        buyer=raw.get("dminsttNm", ""),
        buyer_type=buyer_type(raw.get("dminsttNm", ""), config),
        kind=raw["kind"],
        notice_date=int(str(raw.get("bidNtceDt", ""))[:10].replace("-", "") or 0),
        budget=budget,
        product=raw.get("dtilPrdctClsfcNoNm", ""),
        url=raw.get("bidNtceDtlUrl", ""),
    )


def title_key(title: str) -> str:
    """재공고 비교용 공고명: 머리말·재공고 표시·공백을 뺀다."""
    return "".join(_RENOTICE_RE.sub("", _TITLE_PREFIX_RE.sub("", title)).split())


def unique_notices(raw_notices: list[dict], config: dict) -> list[ProcurementNotice]:
    """중복·재공고·취소공고를 뺀 공고를 공고일 최신순으로 반환한다.

    같은 공고번호는 마지막 차수, 머리말을 뺀 공고명과 수요기관이 같은 공고는 가장 최근 1건만 남긴다.
    """
    latest: dict[str, dict] = {}
    for raw in raw_notices:
        number = raw.get("bidNtceNo")
        if not number:
            continue
        if number not in latest or str(raw.get("bidNtceOrd")) > str(
            latest[number].get("bidNtceOrd")
        ):
            latest[number] = raw
    notices = sorted(
        (
            to_notice(raw, config)
            for raw in latest.values()
            if CANCELLED not in str(raw.get("ntceKindNm", ""))
        ),
        key=lambda n: (-n.notice_date, n.notice_no),
    )
    seen, unique = set(), []
    for notice in notices:
        key = (notice.buyer, title_key(notice.title))
        if key not in seen:
            seen.add(key)
            unique.append(notice)
    return unique


def judge_relevant(
    idea: StructuredIdea,
    notices: list[ProcurementNotice],
    llm_fn: LLMFn,
    batch_size: int = 20,
) -> list[ProcurementNotice]:
    """LLM이 아이디어와 같은 제품·서비스 범주라고 판정한 공고만 원래 순서대로 반환한다.

    batch_size건씩 나눠 공고마다 relevant를 받는다. 응답에서 빠진 공고는 관련 없음으로 본다.
    """
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    fields = idea.model_dump(
        include={"title", "problem", "technology", "customers", "difference"}
    )
    kept = []
    for start in range(0, len(notices), batch_size):
        batch = notices[start : start + batch_size]
        payload = {
            "idea": fields,
            "notices": [
                {"id": i, "title": n.title, "product": n.product}
                for i, n in enumerate(batch)
            ],
        }
        raw = llm_fn(prompt, json.dumps(payload, ensure_ascii=False))
        judgments = raw.get("judgments")
        relevant = {
            j.get("id")
            for j in (judgments if isinstance(judgments, list) else [])
            if isinstance(j, dict) and j.get("relevant") is True
        }
        kept += [n for i, n in enumerate(batch) if i in relevant]
    return kept


def build_procurement(
    idea: StructuredIdea,
    keywords: list[str],
    data_as_of: int,
    fetch_fn: FetchFn | None = None,
    llm_fn: LLMFn = call_relevance_llm,
    config: dict | None = None,
) -> MarketProcurement:
    """주제어로 공공 조달 입찰공고를 찾고 관련 공고만 남긴다. 주제어가 없으면 no_keywords, 실패는 error."""
    if not keywords:
        return MarketProcurement(status="no_keywords", note=NOTE)
    config = config or load_procurement_config()
    as_of = date(data_as_of // 10000, data_as_of // 100 % 100, data_as_of % 100)
    months = recent_months(as_of, config["months"])
    period = f"{months[0][:4]}-{months[0][4:]} ~ {months[-1][:4]}-{months[-1][4:]}"
    fetch = fetch_fn or (lambda k, kind, m: fetch_bid_notices(k, kind, m, config))
    try:
        raw_notices = [
            notice
            for keyword in keywords
            for kind in config["api"]["operations"]
            for month in months
            for notice in fetch(keyword, kind, month)
        ]
        found = unique_notices(raw_notices, config)
        relevant = judge_relevant(
            idea,
            found[: config["max_judge_notices"]],
            llm_fn,
            config["judge_batch_size"],
        )
    except Exception as exc:  # 조달 조회 실패는 시장 보고서 전체를 막지 않는다
        return MarketProcurement(
            status="error",
            keywords=keywords,
            period=period,
            error_message=str(exc),
            note=NOTE,
        )
    return MarketProcurement(
        status="completed",
        keywords=keywords,
        period=period,
        searched_count=len(found),
        notices=relevant,
        note=NOTE,
    )
