"""IdeaLens 평가 실행. 현재는 시장 근거 검색 평가(market)를 제공한다.

시장 검색 평가는 evaluation/market_cases.json의 라벨이 끝난 문항마다 검색 툴과 같은
질의로 상위 K건을 검색해 Hit@K·Recall@K·MRR을 계산하고 evaluation/results/에 CSV로 저장한다.
- 관련 문서가 하나도 없는 문항(예: 뉴스에 가격 근거 없음)은 평균에서 빼고 따로 센다.
- 라벨링 후보에 없던 문서가 상위 K건에 나오면 unjudged로 세고 비관련으로 본다.

사용 예:
    python -m evaluation.evaluate market --label baseline
"""

import argparse
import csv
from pathlib import Path

from evaluation.market_labeling import (
    case_query,
    default_search_fn,
    load_cases,
    load_ideas,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT_DIR / "evaluation" / "results"
K = 5

RESULT_FIELDS = [
    "case_id",
    "idea_id",
    "dimension",
    "n_relevant",
    "hit",
    "recall",
    "rr",
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
        hits = search_fn(case_query(case, ideas), k, idea_id)
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
                "unjudged": sum(doc not in judged for doc in retrieved),
                "retrieved": " ".join(retrieved),
            }
        )
    return rows


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


def main() -> None:
    """market: 시장 근거 검색 평가를 실행하고 요약을 출력한다."""
    parser = argparse.ArgumentParser(description="IdeaLens 평가")
    sub = parser.add_subparsers(dest="command", required=True)
    market = sub.add_parser("market", help="시장 근거 검색 평가")
    market.add_argument("--label", default="baseline", help="결과 파일 이름")
    market.add_argument(
        "--no-idea-filter", action="store_true", help="아이디어 필터 없이 전체 검색"
    )
    args = parser.parse_args()

    rows = evaluate_market(
        load_cases(),
        load_ideas(),
        default_search_fn(),
        idea_filter=not args.no_idea_filter,
    )
    if not rows:
        raise SystemExit("no labeled cases; run evaluation.market_labeling import")
    path = save_results(rows, args.label)
    print(f"{len(rows)} cases -> {path}")
    for name, s in summarize(rows).items():
        metrics = (
            f"Hit@{K}={s['hit']:.2f} Recall@{K}={s['recall']:.2f} MRR={s['mrr']:.2f}"
            if s["hit"] is not None
            else "관련 문서 없음"
        )
        print(
            f"  {name:17} {metrics} (문항 {s['cases']}, 관련 없음 {s['no_relevant']},"
            f" unjudged {s['unjudged']})"
        )


if __name__ == "__main__":
    main()
