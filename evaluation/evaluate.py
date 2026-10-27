"""IdeaLens 시장 근거·관련성 및 특허 검색 평가를 실행한다.

시장 검색 평가는 evaluation/market_cases.json의 라벨이 끝난 문항마다 검색 툴과 같은
질의로 상위 K건을 검색해 Hit@K·Recall@K·Precision@K·MRR·nDCG@K와 검색 지연을 계산하고 evaluation/results/에 CSV로 저장한다.
- 관련 문서가 하나도 없는 문항(예: 뉴스에 가격 근거 없음)은 평균에서 빼고 따로 센다.
- 라벨링 후보에 없던 문서가 상위 K건에 나오면 unjudged로 세고 비관련으로 본다.

관련성 필터 평가는 사람 라벨 행에서 필터 판정을 비교하고(행 단위), 사람 라벨만 있는 문항의
충분성 상태를 비교한다(evaluation/market_relevance_eval.py).

사용 예:
    python -m evaluation.evaluate market --label baseline
    python -m evaluation.evaluate patent --mode hybrid --label baseline
    python -m evaluation.evaluate relevance --model gpt-4o
"""

import argparse
import csv
import math
import time
from collections import Counter
from functools import partial
from pathlib import Path

from evaluation.market_labeling import (
    CANDIDATES_PATH,
    case_query,
    default_search_fn,
    load_cases,
    load_ideas,
    read_label_rows,
    write_label_rows,
)
from src.retrieval.patent_search import search_patents as search_patent_documents
from src.retrieval.patent_store import get_collection as get_patent_collection
from evaluation.market_relevance_eval import evaluate_relevance
from src.retrieval.market_relevance import RELEVANCE_MODEL, call_relevance_llm

ROOT_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT_DIR / "evaluation" / "results"
PATENT_CASES_PATH = ROOT_DIR / "evaluation" / "patent_cases.json"
K = 5

RESULT_FIELDS = [
    "case_id",
    "idea_id",
    "dimension",
    "n_relevant",
    "hit",
    "recall",
    "rr",
    "precision",
    "ndcg",
    "search_ms",
    "rerank_ms",
    "unjudged",
    "retrieved",
]


def hit_at_k(retrieved: list[str], relevant: set[str], k: int = K) -> float:
    """상위 k건에 관련 문서가 하나라도 있으면 1.0."""
    return float(any(doc in relevant for doc in retrieved[:k]))


def recall_at_k(retrieved: list[str], relevant: set[str], k: int = K) -> float:
    """관련 문서 중 상위 k건에 들어온 비율. 관련 문서가 없으면 0.0."""
    if not relevant:
        return 0.0
    return len(set(retrieved[:k]) & relevant) / len(relevant)


def reciprocal_rank(retrieved: list[str], relevant: set[str], k: int = K) -> float:
    """상위 k건 중 첫 관련 문서 순위의 역수. 없으면 0.0."""
    for rank, doc in enumerate(retrieved[:k], start=1):
        if doc in relevant:
            return 1 / rank
    return 0.0


def precision_at_k(retrieved: list[str], relevant: set[str], k: int = K) -> float:
    """Top-k 내 관련 문서 비율. 검색 결과가 k개보다 적으면 실제 반환 수로 나눈다."""
    ranked = retrieved[:k]
    return len(set(ranked) & relevant) / len(ranked) if ranked else 0.0


def ndcg_at_k(retrieved: list[str], relevant: set[str], k: int = K) -> float:
    """이진 관련도 기준 nDCG@k를 계산한다."""
    dcg = sum(
        1 / math.log2(rank + 1)
        for rank, doc in enumerate(retrieved[:k], 1)
        if doc in relevant
    )
    ideal = sum(1 / math.log2(rank + 1) for rank in range(1, min(len(relevant), k) + 1))
    return dcg / ideal if ideal else 0.0


def evaluate_market(
    cases: list[dict],
    ideas: dict[str, dict],
    search_fn,
    k: int = K,
    idea_filter: bool = True,
) -> list[dict]:
    """라벨이 끝난 문항마다 검색 지표를 계산한다. 관련 문서가 없는 문항은 지표를 비운다."""
    rows = []
    for case in cases:
        if not case.get("labeled"):
            continue
        idea_id = case["idea_id"] if idea_filter else None
        started = time.perf_counter()
        hits = search_fn(case_query(case, ideas), k, idea_id)
        search_ms = (time.perf_counter() - started) * 1000
        rerank_ms = hits[0].get("rerank_ms", 0.0) if hits else 0.0
        retrieved = [h["source_id"] for h in hits]
        relevant = set(case["relevant_source_ids"])
        judged = set(case["judged_source_ids"])
        has_relevant = bool(relevant)
        rows.append(
            {
                "case_id": case["case_id"],
                "idea_id": case["idea_id"],
                "dimension": case["dimension"],
                "n_relevant": len(relevant),
                "hit": hit_at_k(retrieved, relevant, k) if has_relevant else None,
                "recall": recall_at_k(retrieved, relevant, k) if has_relevant else None,
                "rr": reciprocal_rank(retrieved, relevant, k) if has_relevant else None,
                "precision": (
                    precision_at_k(retrieved, relevant, k) if has_relevant else None
                ),
                "ndcg": ndcg_at_k(retrieved, relevant, k) if has_relevant else None,
                "search_ms": round(search_ms, 3),
                "rerank_ms": round(rerank_ms, 3),
                "unjudged": sum(doc not in judged for doc in retrieved),
                "retrieved": " ".join(retrieved),
            }
        )
    return rows


def evaluate_patents(cases: list[dict], search_fn, k: int = K) -> list[dict]:
    """라벨된 특허 질의마다 문헌 단위 검색 지표와 지연시간을 계산한다."""
    rows = []
    for case in cases:
        if not case.get("labeled"):
            continue
        started = time.perf_counter()
        hits = search_fn(case["query"], k)
        elapsed_ms = (time.perf_counter() - started) * 1000
        rerank_ms = hits[0].get("rerank_ms", 0.0) if hits else 0.0
        retrieved = [hit["source_id"] for hit in hits]
        relevant = set(case["relevant_source_ids"])
        judged = set(case["judged_source_ids"])
        has_relevant = bool(relevant)
        rows.append(
            {
                "case_id": case["case_id"],
                "idea_id": case.get("idea_id", ""),
                "dimension": case.get("technical_element", "patent"),
                "n_relevant": len(relevant),
                "hit": hit_at_k(retrieved, relevant, k) if has_relevant else None,
                "recall": recall_at_k(retrieved, relevant, k) if has_relevant else None,
                "rr": reciprocal_rank(retrieved, relevant, k) if has_relevant else None,
                "precision": (
                    precision_at_k(retrieved, relevant, k) if has_relevant else None
                ),
                "ndcg": ndcg_at_k(retrieved, relevant, k) if has_relevant else None,
                "search_ms": round(max(elapsed_ms - rerank_ms, 0.0), 3),
                "rerank_ms": round(rerank_ms, 3),
                "unjudged": sum(doc not in judged for doc in retrieved),
                "retrieved": " ".join(retrieved),
            }
        )
    return rows


def default_patent_search_fn(retrieval_mode: str = "dense", reranker=None):
    """특허 Chroma 색인을 지정한 검색 모드로 평가하는 함수를 만든다."""
    collection = get_patent_collection()
    if collection.count() == 0:
        raise RuntimeError(
            "patent Chroma index is empty; ingest and index patent documents before evaluation"
        )

    def search(query: str, top_k: int) -> list[dict]:
        rerank_times = []
        timed_reranker = None
        if reranker:

            def timed_reranker(query_text, documents):
                started = time.perf_counter()
                scores = reranker(query_text, documents)
                rerank_times.append((time.perf_counter() - started) * 1000)
                return scores

        hits = search_patent_documents(
            query,
            collection=collection,
            top_k=top_k,
            retrieval_mode=retrieval_mode,
            reranker=timed_reranker,
        )
        rerank_ms = rerank_times[0] if rerank_times else 0.0
        return [
            {"source_id": hit.document.source_id, "rerank_ms": rerank_ms}
            for hit in hits
        ]

    return search


def summarize(rows: list[dict]) -> dict[str, dict]:
    """전체·차원별 평균 지표와 관련 문서 없는 문항 수를 계산한다."""
    groups = {"all": rows}
    for row in rows:
        groups.setdefault(row["dimension"], []).append(row)

    summary = {}
    for name, group in groups.items():
        scored = [r for r in group if r["n_relevant"]]
        n = len(scored)
        summary[name] = {
            "cases": len(group),
            "no_relevant": len(group) - n,
            "hit": sum(r["hit"] for r in scored) / n if n else None,
            "recall": sum(r["recall"] for r in scored) / n if n else None,
            "mrr": sum(r["rr"] for r in scored) / n if n else None,
            "precision": sum(r["precision"] for r in scored) / n if n else None,
            "ndcg": sum(r["ndcg"] for r in scored) / n if n else None,
            "search_ms": (
                sum(r["search_ms"] for r in group) / len(group) if group else 0.0
            ),
            "rerank_ms": (
                sum(r["rerank_ms"] for r in group) / len(group) if group else 0.0
            ),
            "unjudged": sum(r["unjudged"] for r in group),
        }
    return summary


def save_results(rows: list[dict], label: str, results_dir: Path = RESULTS_DIR):
    """문항별 결과를 market_retrieval_{label}.csv로 저장한다."""
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"market_retrieval_{label}.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def save_patent_results(rows: list[dict], label: str, results_dir: Path = RESULTS_DIR):
    """문항별 특허 검색 결과를 patent_retrieval_{label}.csv로 저장한다."""
    results_dir.mkdir(parents=True, exist_ok=True)
    path = results_dir / f"patent_retrieval_{label}.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=RESULT_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return path


def run_relevance(model: str, label: str) -> None:
    """관련성 필터를 사람 라벨과 비교하고 행별 결과를 market_relevance_{label}.csv로 저장한다."""
    result = evaluate_relevance(
        read_label_rows(CANDIDATES_PATH),
        load_ideas(),
        partial(call_relevance_llm, model=model),
    )
    path = write_label_rows(
        result["rows"],
        ["case_id", "source_id", "title", "gold", "pred", "confidence", "reason"],
        RESULTS_DIR / f"market_relevance_{label}.csv",
    )
    m = result["metrics"]
    print(f"{model}: {m['n']} rows -> {path}")
    print(
        f"  정확도={m['accuracy']:.2f} 정밀도={m['precision']:.2f} 재현율={m['recall']:.2f}"
        f" kappa={m['kappa']:.2f} (관련: 사람 {m['gold_positive']} / 필터 {m['pred_positive']})"
    )
    pairs = Counter((s["gold"], s["pred"]) for s in result["status"])
    agree = sum(n for (g, p), n in pairs.items() if g == p)
    print(
        f"  충분성 상태 일치 {agree}/{len(result['status'])}문항 (사람→필터: {dict(pairs)})"
    )


def main() -> None:
    """market: 시장 근거 검색 평가, relevance: 관련성 필터 평가를 실행하고 요약을 출력한다."""
    parser = argparse.ArgumentParser(description="IdeaLens 평가")
    sub = parser.add_subparsers(dest="command", required=True)
    market = sub.add_parser("market", help="시장 근거 검색 평가")
    market.add_argument("--label", default="baseline", help="결과 파일 이름")
    market.add_argument("--mode", choices=["dense", "bm25", "hybrid"], default="dense")
    market.add_argument(
        "--rerank",
        action="store_true",
        help="BGE reranker 사용 (sentence-transformers 필요)",
    )
    market.add_argument(
        "--no-idea-filter", action="store_true", help="아이디어 필터 없이 전체 검색"
    )
    patent = sub.add_parser("patent", help="특허 문헌 검색 평가")
    patent.add_argument("--label", default="baseline", help="결과 파일 이름")
    patent.add_argument("--mode", choices=["dense", "bm25", "hybrid"], default="dense")
    patent.add_argument(
        "--rerank",
        action="store_true",
        help="BGE reranker 사용 (sentence-transformers 필요)",
    )
    relevance = sub.add_parser("relevance", help="시장 관련성 필터 평가")
    relevance.add_argument(
        "--model", default=RELEVANCE_MODEL, help="판정 모델 (기본: 필터 기본 모델)"
    )
    relevance.add_argument("--label", help="결과 파일 이름 (기본: 모델명)")
    args = parser.parse_args()

    if args.command == "relevance":
        run_relevance(args.model, args.label or args.model)
        return

    reranker = None
    if args.rerank:
        from src.retrieval.engine import bge_reranker

        reranker = bge_reranker()
    if args.command == "market":
        rows = evaluate_market(
            load_cases(),
            load_ideas(),
            default_search_fn(args.mode, reranker=reranker),
            idea_filter=not args.no_idea_filter,
        )
        result_path = save_results(
            rows, f"{args.mode}_{'rerank_' if args.rerank else ''}{args.label}"
        )
    else:
        from evaluation.market_labeling import load_cases as load_json_cases

        cases = load_json_cases(PATENT_CASES_PATH)
        if not any(case.get("labeled") for case in cases):
            raise SystemExit(
                "no labeled patent cases; run python -m evaluation.patent_labeling export, "
                "fill relevant=0/1, then run python -m evaluation.patent_labeling import"
            )
        rows = evaluate_patents(
            cases,
            default_patent_search_fn(args.mode, reranker=reranker),
        )
        result_path = save_patent_results(
            rows, f"{args.mode}_{'rerank_' if args.rerank else ''}{args.label}"
        )
    if not rows:
        label_command = (
            "evaluation.market_labeling import"
            if args.command == "market"
            else "evaluation.patent_labeling import"
        )
        raise SystemExit(f"no labeled cases; run python -m {label_command}")
    print(f"{len(rows)} cases -> {result_path}")
    for name, s in summarize(rows).items():
        metrics = (
            f"Hit@{K}={s['hit']:.2f} Recall@{K}={s['recall']:.2f} "
            f"Precision@{K}={s['precision']:.2f} MRR={s['mrr']:.2f} "
            f"nDCG@{K}={s['ndcg']:.2f} latency={s['search_ms']:.1f}ms "
            f"rerank={s['rerank_ms']:.1f}ms"
            if s["hit"] is not None
            else "관련 문서 없음"
        )
        print(
            f"  {name:17} {metrics} (문항 {s['cases']}, 관련 없음 {s['no_relevant']},"
            f" unjudged {s['unjudged']})"
        )


if __name__ == "__main__":
    main()
