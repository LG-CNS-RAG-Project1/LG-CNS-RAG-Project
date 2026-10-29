"""시장 조사 진입점. 아이디어 5개 항목으로 차원별 검색 → 관련성 판정 → 시장 분석을 실행해
MarketReport를 만든다.

사용 예:
    python -m src.services.market_service --idea-id SF-01
    python -m src.services.market_service --idea-id SF-01 --out data/samples/market_reports/SF-01.json
"""

import argparse
import json
import time
from datetime import date
from pathlib import Path

from src.generation.market_analysis import LLMFn, build_report, call_analysis_llm
from src.retrieval.market_relevance import (
    IDEAS_PATH,
    JudgeFn,
    call_relevance_llm,
    search_with_relevance,
)
from src.retrieval.market_search import EmbedFn, embed_texts, get_collection
from src.schemas import MarketReport, MarketSearchRequest, StructuredIdea


def search_scope(collection, idea_id: str | None) -> str:
    """보고서에 표시할 검색 범위(출처별 건수·발행일·사업연도·아이디어 범위)를 만든다.

    뉴스는 발행일 범위, DART는 기업 수와 보고 대상 사업연도를 쓴다. idea_id를 주면 그
    아이디어에 연결된 자료만 세고, 연결된 DART 기업이 없으면 그렇다고 쓴다.
    """
    metadatas = collection.get(include=["metadatas"])["metadatas"]
    if idea_id:
        metadatas = [m for m in metadatas if m.get(f"idea_{idea_id}")]
    news = [m for m in metadatas if m.get("source_type") == "news"]
    dart = [m for m in metadatas if m.get("source_type") == "dart"]
    dates = [m["published_at"] for m in news if m.get("published_at")]
    period = f", 발행일 {min(dates)}~{max(dates)}" if dates else ""
    parts = [
        f"네이버 뉴스 검색 API로 사전 수집한 스마트팩토리 기사 {len(news)}건(제목·요약{period})"
    ]
    if dart:
        companies = len({m["publisher"] for m in dart})
        years = ", ".join(sorted({m["period"] for m in dart if m.get("period")}))
        parts.append(
            f"DART 사업보고서 '사업의 내용' 발췌 {len(dart)}건(기업 {companies}곳, {years})"
        )
    elif idea_id:
        parts.append(
            "DART 사업보고서: 사업의 내용에 이 아이디어 용어가 나오는 기업 없음"
        )
    else:
        parts.append("DART 사업보고서 색인 없음")
    target = f"아이디어 {idea_id} 연결 자료 범위" if idea_id else "전체 수집 범위"
    return " · ".join(parts) + f", {target}"


def searched_dart_companies(assessed: dict[str, dict]) -> list[str]:
    """차원별 검색 결과에 들어온 DART 기업명을 처음 나온 순서대로 반환한다."""
    companies = []
    for result in assessed.values():
        for hit in result["hits"]:
            name = hit["publisher"].removesuffix(" (DART 사업보고서)")
            if hit["source_type"] == "dart" and name not in companies:
                companies.append(name)
    return companies


def run_market_research(
    request: MarketSearchRequest,
    idea_id: str | None = None,
    collection=None,
    embed_fn: EmbedFn = embed_texts,
    judge_fn: JudgeFn = call_relevance_llm,
    llm_fn: LLMFn = call_analysis_llm,
    data_as_of: int | None = None,
) -> MarketReport:
    """차원별 검색·관련성 판정·분석을 실행해 MarketReport를 반환한다.

    검색·판정 단계에서 예외가 나면 status=error 보고서를 반환한다. data_as_of가 없으면 오늘 날짜를 쓴다.
    """
    data_as_of = data_as_of or int(date.today().strftime("%Y%m%d"))
    scope = "네이버 뉴스 사전 수집 기사 · DART 사업보고서 발췌"
    try:
        collection = collection or get_collection()
        scope = search_scope(collection, idea_id)
        assessed = search_with_relevance(
            request,
            idea_id=idea_id,
            collection=collection,
            embed_fn=embed_fn,
            judge_fn=judge_fn,
        )
    except Exception as exc:  # 검색 실패를 보고서 단위 오류로 전달
        return MarketReport(
            status="error",
            search_scope=scope,
            data_as_of=data_as_of,
            error_message=f"market search failed: {exc}",
        )
    companies = searched_dart_companies(assessed)
    if companies:
        scope += f" · 아이디어와 가까워 검색한 DART 기업: {', '.join(companies)}"
    return build_report(request.idea, assessed, scope, data_as_of, llm_fn)


def main() -> None:
    """샘플 아이디어 1개로 시장 조사를 실행해 MarketReport JSON을 출력하거나 저장한다."""
    parser = argparse.ArgumentParser(description="시장 조사 실행 → MarketReport JSON")
    parser.add_argument("--idea-id", required=True, help="data/samples/ideas.json의 ID")
    parser.add_argument("--out", type=Path, help="JSON 저장 경로 (없으면 화면 출력)")
    args = parser.parse_args()

    entries = json.loads(IDEAS_PATH.read_text(encoding="utf-8"))
    entry = next(e for e in entries if e["idea_id"] == args.idea_id)
    request = MarketSearchRequest(idea=StructuredIdea(**entry["idea"]))

    started = time.perf_counter()
    report = run_market_research(request, idea_id=args.idea_id)
    elapsed = time.perf_counter() - started

    payload = report.model_dump_json(indent=2)
    if not args.out:
        print(payload)
        return
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(payload + "\n", encoding="utf-8")
    print(
        f"{report.status} -> {args.out} ({elapsed:.1f}s, 근거 {len(report.evidence)}건)"
    )
    for d in report.dimensions:
        print(f"  {d.dimension:17} {d.verdict:12} 문장 {len(d.claims)}")
    if report.error_message:
        print(f"  error: {report.error_message}")


if __name__ == "__main__":
    main()
