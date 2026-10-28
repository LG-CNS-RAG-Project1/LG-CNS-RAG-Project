"""시장 관련성 필터(src.retrieval.market_relevance)를 사람 라벨과 비교해 평가한다.

- 행 단위: 사람 라벨 행(label_source=human)마다 필터 판정과 비교해 정확도·정밀도·재현율·kappa 계산
- 충분성 단위: 벡터 후보가 모두 사람 라벨인 문항에서 검색 상위 TOP_K건(벡터 순위)의 충분성 상태를
  사람 라벨로 정한 상태와 비교
LLM 라벨 행은 필터와 같은 기준의 LLM이 만든 값이므로 평가에 쓰지 않는다.
"""

from collections import defaultdict

from src.retrieval.market_relevance import judge_hits, sufficiency_status
from src.schemas import StructuredIdea

TOP_K = 5


def classification_metrics(gold: list[bool], pred: list[bool]) -> dict:
    """이진 판정의 정확도·정밀도·재현율·Cohen's kappa와 양성 비율을 계산한다."""
    n = len(gold)
    if not n:
        return {"n": 0}
    tp = sum(g and p for g, p in zip(gold, pred))
    fp = sum(p and not g for g, p in zip(gold, pred))
    fn = sum(g and not p for g, p in zip(gold, pred))
    observed = sum(g == p for g, p in zip(gold, pred)) / n
    gold_pos, pred_pos = sum(gold) / n, sum(pred) / n
    expected = gold_pos * pred_pos + (1 - gold_pos) * (1 - pred_pos)
    return {
        "n": n,
        "accuracy": observed,
        "precision": tp / (tp + fp) if tp + fp else None,
        "recall": tp / (tp + fn) if tp + fn else None,
        "kappa": (observed - expected) / (1 - expected) if expected < 1 else 1.0,
        "gold_positive": sum(gold),
        "pred_positive": sum(pred),
    }


def row_to_hit(row: dict) -> dict:
    """라벨 CSV 행을 관련성 판정 입력(검색 결과 형식)으로 바꾼다."""
    return {
        "source_id": row["source_id"],
        "title": row["title"],
        "text": f"{row['title']}\n{row['summary']}",
    }


def evaluate_relevance(rows: list[dict], ideas: dict[str, dict], judge_fn) -> dict:
    """사람 라벨 행으로 필터를 평가해 {rows, metrics, status}를 반환한다."""
    human_by_case: dict[str, list[dict]] = defaultdict(list)
    all_by_case: dict[str, list[dict]] = defaultdict(list)
    for row in rows:
        all_by_case[row["case_id"]].append(row)
        if row.get("label_source") == "human":
            human_by_case[row["case_id"]].append(row)

    results, pred_by_key = [], {}
    for case_id, group in human_by_case.items():
        idea = StructuredIdea(**ideas[group[0]["idea_id"]]["idea"])
        judged = judge_hits(
            idea, group[0]["dimension"], [row_to_hit(r) for r in group], judge_fn
        )
        for row, hit in zip(group, judged):
            pred_by_key[(case_id, row["source_id"])] = hit["relevant"]
            results.append(
                {
                    "case_id": case_id,
                    "source_id": row["source_id"],
                    "title": row["title"],
                    "gold": int(row["relevant"].strip() == "1"),
                    "pred": int(hit["relevant"]),
                    "confidence": hit["relevance_confidence"],
                    "reason": hit["relevance_reason"],
                }
            )

    status = []
    for case_id, group in all_by_case.items():
        vector = [r for r in group if r["pool"] == "vector"]
        if not vector or not all(r.get("label_source") == "human" for r in vector):
            continue
        top = sorted(vector, key=lambda r: int(r["rank"]))[:TOP_K]
        gold = [{"relevant": r["relevant"].strip() == "1"} for r in top]
        pred = [{"relevant": pred_by_key[(case_id, r["source_id"])]} for r in top]
        status.append(
            {
                "case_id": case_id,
                "gold": sufficiency_status(gold),
                "pred": sufficiency_status(pred),
            }
        )

    metrics = classification_metrics(
        [bool(r["gold"]) for r in results], [bool(r["pred"]) for r in results]
    )
    return {"rows": results, "metrics": metrics, "status": status}
