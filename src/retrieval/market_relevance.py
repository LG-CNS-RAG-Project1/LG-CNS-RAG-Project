"""시장 검색 결과가 아이디어의 해당 시장 차원 근거가 되는지 LLM으로 판정하고 차원별 충분성을 정한다.

검색 거리는 관련성을 구분하지 못하므로(평가 라벨 300건 기준 관련/비관련 AUC 0.52) 충분성은
거리 임계값이 아니라 관련성 판정 결과로 정한다. 판정 기준은 평가셋 라벨과 같은
prompts/market_label_judge.md를 쓴다. 같은 호출에서 기사의 근거 성격(구매 신호·간접 수요·
추정치·기업 주장·사업 신호)도 판정해, 수집 단계에서 모두 사업 신호로 둔 뉴스의 성격을 바꾼다. 프로젝트 LLM은 비용 때문에 모두 gpt-4o-mini를 쓴다.
사람 라벨 91건 기준 정밀도는 비교 측정한 gpt-4o 0.89보다 낮은 0.69로, 비관련 기사를 더 많이
관련으로 판정한다(evaluation/results/market_relevance_*.csv).

충분성 상태:
    sufficient    관련 근거 MIN_SUFFICIENT건 이상
    limited       관련 근거가 1건 이상이지만 MIN_SUFFICIENT건 미만 (신호 수준)
    insufficient  검색 결과는 있으나 관련 근거 없음 (자료 부족)
    no_results    검색 결과 없음
    error         관련성 판정 실패 (검색 결과는 판정 없이 반환)

사용 예:
    python -m src.retrieval.market_relevance --idea-id SF-01
"""

import argparse
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

from src.retrieval.market_search import EmbedFn, embed_texts, search_by_dimensions
from src.schemas import IDEA_FIELDS, MarketSearchRequest, StructuredIdea

ROOT_DIR = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT_DIR / "prompts" / "market_label_judge.md"
IDEAS_PATH = ROOT_DIR / "data" / "samples" / "ideas.json"
RELEVANCE_MODEL = "gpt-4o-mini"
MIN_SUFFICIENT = 2
MAX_WORKERS = 8

DIMENSION_LABELS = {
    "demand": "수요",
    "competition": "경쟁·대체재",
    "price": "가격",
    "buyer": "구매자",
    "adoption_barrier": "도입장벽",
}

JudgeFn = Callable[[str, str], dict]

# 판정기가 기사에 붙일 수 있는 근거 성격. direct_demand는 고객 검증 자료에만 쓴다.
ARTICLE_NATURES = {
    "purchase_signal",
    "indirect_demand",
    "estimate",
    "company_claim",
    "business_signal",
}
# confirmed 판정을 열어 주는 성격은 기사 제목·요약에 이 표현이 있어야 유지한다.
NATURE_CUES = {
    "purchase_signal": [
        re.compile(r"도입|구축|적용|계약|공급|납품|수주|운영 중|발주|구매"),
    ],
    "indirect_demand": [
        re.compile(r"조사|설문|통계|실태"),
        re.compile(r"\d+(?:\.\d+)?\s*(?:%|퍼센트|개사|곳|명|건)"),
    ],
}


def call_relevance_llm(
    system_prompt: str, user_text: str, model: str = RELEVANCE_MODEL
) -> dict:
    """OpenAI 채팅 API를 JSON 모드로 호출해 판정 결과를 dict로 반환한다.

    .env의 OPENAI_API_KEY가 필요하며, 없으면 RuntimeError를 발생시킨다.
    """
    from openai import OpenAI

    load_dotenv(ROOT_DIR / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set in .env")
    response = OpenAI().chat.completions.create(
        model=model,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
    )
    return json.loads(response.choices[0].message.content)


def judge_input(idea: StructuredIdea, dimension: str, hit: dict) -> str:
    """판정 프롬프트에 넘길 입력 JSON(아이디어·차원·질문·기사 제목·요약)을 만든다."""
    _, _, summary = hit["text"].partition("\n")
    return json.dumps(
        {
            "idea": idea.model_dump(include={"title", *IDEA_FIELDS}),
            "dimension": dimension,
            "question": f"'{idea.title}'의 {DIMENSION_LABELS[dimension]} 판단 근거가 되는가?",
            "title": hit["title"],
            "summary": summary,
        },
        ensure_ascii=False,
    )


def parse_relevance(raw: dict) -> dict:
    """LLM 응답을 relevant(bool)·relevance_confidence·relevance_reason·article_nature로 정리한다.

    label이 1이 아니면 비관련, confidence가 high가 아니면 low로 본다. evidence_nature가
    ARTICLE_NATURES에 없으면 article_nature는 business_signal이다.
    """
    nature = str(raw.get("evidence_nature", "")).strip()
    return {
        "relevant": str(raw.get("label", "")).strip() == "1",
        "relevance_confidence": "high" if raw.get("confidence") == "high" else "low",
        "relevance_reason": " ".join(str(raw.get("reason", "")).split()),
        "article_nature": nature if nature in ARTICLE_NATURES else "business_signal",
    }


def checked_nature(nature: str, text: str) -> str:
    """NATURE_CUES의 표현이 기사에 모두 없으면 판정기가 고른 성격 대신 business_signal을 쓴다."""
    cues = NATURE_CUES.get(nature, [])
    return nature if all(cue.search(text) for cue in cues) else "business_signal"


def judged_hit(hit: dict, raw: dict) -> dict:
    """검색 결과에 판정 필드를 붙인다. 뉴스는 근거 성격을 검사를 통과한 article_nature로 바꾼다."""
    judged = {**hit, **parse_relevance(raw)}
    judged["article_nature"] = checked_nature(judged["article_nature"], hit["text"])
    if hit.get("source_type") == "news":
        judged["evidence_nature"] = judged["article_nature"]
    return judged


def judge_hits(
    idea: StructuredIdea,
    dimension: str,
    hits: list[dict],
    judge_fn: JudgeFn = call_relevance_llm,
    max_workers: int = MAX_WORKERS,
) -> list[dict]:
    """검색 결과마다 관련성을 병렬로 판정해 판정 필드를 붙인 결과를 검색 순서대로 반환한다."""
    if not hits:
        return []
    system_prompt = PROMPT_PATH.read_text(encoding="utf-8")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        raws = list(
            executor.map(
                lambda hit: judge_fn(system_prompt, judge_input(idea, dimension, hit)),
                hits,
            )
        )
    return [judged_hit(hit, raw) for hit, raw in zip(hits, raws)]


def sufficiency_status(judged: list[dict]) -> str:
    """판정된 검색 결과로 충분성 상태(sufficient·limited·insufficient·no_results)를 정한다."""
    if not judged:
        return "no_results"
    relevant = sum(hit["relevant"] for hit in judged)
    if relevant >= MIN_SUFFICIENT:
        return "sufficient"
    return "limited" if relevant else "insufficient"


def assess_dimensions(
    idea: StructuredIdea,
    results: dict[str, list[dict]],
    judge_fn: JudgeFn = call_relevance_llm,
) -> dict[str, dict]:
    """차원별 검색 결과를 판정해 {차원: {status, relevant_count, hits[, error_message]}}로 반환한다.

    한 차원의 판정이 실패하면 그 차원만 status=error로 두고 검색 결과를 판정 없이 담는다.
    """
    assessed = {}
    for dimension, hits in results.items():
        try:
            judged = judge_hits(idea, dimension, hits, judge_fn)
        except Exception as exc:  # 판정 실패를 차원 단위 오류로 전달
            assessed[dimension] = {
                "status": "error",
                "relevant_count": None,
                "hits": hits,
                "error_message": str(exc),
            }
            continue
        assessed[dimension] = {
            "status": sufficiency_status(judged),
            "relevant_count": sum(hit["relevant"] for hit in judged),
            "hits": judged,
        }
    return assessed


def search_with_relevance(
    request: MarketSearchRequest,
    idea_id: str | None = None,
    collection=None,
    embed_fn: EmbedFn = embed_texts,
    judge_fn: JudgeFn = call_relevance_llm,
    dart_companies: list[str] | None = None,
) -> dict[str, dict]:
    """차원별로 검색한 뒤 관련성을 판정해 충분성 상태와 함께 반환한다 (에이전트용 툴).

    dart_companies는 search_by_dimensions에 그대로 전달한다 (없으면 아이디어로 기업을 고른다).

    반환: {차원: {"status", "relevant_count", "hits"}}. hits의 각 항목은 search_market 반환 형식에
    relevant·relevance_confidence·relevance_reason·article_nature가 추가되고, 뉴스는
    evidence_nature가 article_nature로 바뀐다.
    """
    results = search_by_dimensions(
        request,
        idea_id=idea_id,
        collection=collection,
        embed_fn=embed_fn,
        dart_companies=dart_companies,
    )
    return assess_dimensions(request.idea, results, judge_fn)


def main() -> None:
    """샘플 아이디어 1개로 차원별 검색·관련성 판정 결과를 출력한다."""
    parser = argparse.ArgumentParser(description="시장 근거 검색 + 관련성 판정")
    parser.add_argument("--idea-id", required=True, help="data/samples/ideas.json의 ID")
    parser.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    entries = json.loads(IDEAS_PATH.read_text(encoding="utf-8"))
    entry = next(e for e in entries if e["idea_id"] == args.idea_id)
    request = MarketSearchRequest(
        idea=StructuredIdea(**entry["idea"]), top_k=args.top_k
    )
    for dimension, result in search_with_relevance(request, args.idea_id).items():
        print(
            f"\n## {dimension} [{result['status']}] 관련 {result['relevant_count']}건"
        )
        for hit in result["hits"]:
            mark = "O" if hit.get("relevant") else "-"
            reason = hit.get("relevance_reason", "")
            print(f"  {mark} {hit['distance']:.3f} {hit['title'][:50]} | {reason}")


if __name__ == "__main__":
    main()
