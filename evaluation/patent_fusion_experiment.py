"""Compare query- and patent-section rank fusion on the local patent corpus.

The experiment is an offline diagnostic. It keeps the existing corpus and
candidate pool fixed and reports AI-draft metrics separately from human labels.
"""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from evaluation.evaluate import (
    hit_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from evaluation.patent_chunk_rerank_experiment import (
    AREAS,
    METRIC_K,
    OUTPUT_DIR as CHUNK_EXPERIMENT_DIR,
    TOP_K,
    build_experiment_chunks,
    load_patents,
    rank_chunks,
)
from evaluation.patent_labeling import load_cases
from src.retrieval.engine import bm25_scores
from src.retrieval.schemas import SearchDocument

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "data" / "patents" / "processed" / "query_fusion_experiment"
RRF_K = 60
RUN_FIELDS = (
    "baseline_bm25",
    "query_rrf",
    "section_rrf",
    "section_weighted_rrf",
)


def _rank_patent_scores(scores: dict[str, float]) -> list[str]:
    return [
        key for key, _ in sorted(scores.items(), key=lambda item: (-item[1], item[0]))
    ]


def _field_rankings(query, patents, area, section):
    selected = [patent for patent in patents if area in patent.technology_area_ids]
    documents = []
    chunks = (
        build_experiment_chunks(patents, area, "baseline")
        if section != "title_abstract"
        else []
    )
    for patent in selected:
        if section == "title_abstract":
            documents.append(
                SearchDocument(
                    chunk_id=f"{patent.patent_id}:title_abstract",
                    source_id=patent.patent_id,
                    source_type="patent",
                    title=patent.title,
                    content=patent.abstract,
                    metadata={"section": section},
                )
            )
            continue
        for chunk in chunks:
            if chunk.patent_id != patent.patent_id or chunk.section != "claims":
                continue
            if section == "independent_claims" and chunk.claim_type != "independent":
                continue
            if section == "dependent_claims" and chunk.claim_type != "dependent":
                continue
            documents.append(
                SearchDocument(
                    chunk_id=chunk.chunk_id,
                    source_id=patent.patent_id,
                    source_type="patent",
                    title=patent.title,
                    content=chunk.text,
                    metadata={"section": section},
                )
            )
    scored = bm25_scores(query, documents)
    best_by_patent = {}
    for document, score in scored:
        best_by_patent[document.source_id] = max(
            best_by_patent.get(document.source_id, float("-inf")), score
        )
    return _rank_patent_scores(best_by_patent)


def reciprocal_rank_fusion(rankings, weights=None, rrf_k=RRF_K):
    """Combine patent rankings with explicit nonnegative source weights."""
    weights = weights or [1.0] * len(rankings)
    if len(weights) != len(rankings) or any(weight < 0 for weight in weights):
        raise ValueError("weights must match rankings and be nonnegative")
    scores = defaultdict(float)
    for ranking, weight in zip(rankings, weights):
        for rank, patent_id in enumerate(ranking, 1):
            scores[patent_id] += weight / (rrf_k + rank)
    return sorted(scores, key=lambda patent_id: (-scores[patent_id], patent_id)), scores


def _rank_all(patents, cases):
    rankings = []
    for case in cases:
        for area in AREAS:
            baseline, _ = rank_chunks(case["query"], patents, area, "baseline", "max")
            baseline_ids = [row["patent_id"] for row in baseline]
            baseline_scores = {row["patent_id"]: row["score"] for row in baseline}
            query_rankings = []
            for query in (case["query"], case["technical_element"]):
                query_ranked, _ = rank_chunks(query, patents, area, "baseline", "max")
                query_rankings.append([row["patent_id"] for row in query_ranked])
            query_fused, query_scores = reciprocal_rank_fusion(query_rankings)

            section_rankings = [
                _field_rankings(case["query"], patents, area, section)
                for section in (
                    "title_abstract",
                    "independent_claims",
                    "dependent_claims",
                )
            ]
            section_fused, section_scores = reciprocal_rank_fusion(section_rankings)
            weighted_fused, weighted_scores = reciprocal_rank_fusion(
                section_rankings, weights=[2.0, 2.0, 0.5]
            )
            profiles = {
                "baseline_bm25": (baseline_ids, baseline_scores),
                "query_rrf": (query_fused, query_scores),
                "section_rrf": (section_fused, section_scores),
                "section_weighted_rrf": (weighted_fused, weighted_scores),
            }
            for run_id, (ids, scores) in profiles.items():
                for rank, patent_id in enumerate(ids[:TOP_K], 1):
                    rankings.append(
                        {
                            "case_id": case["case_id"],
                            "technology_area_id": area,
                            "run_id": run_id,
                            "rank": rank,
                            "source_id": patent_id,
                            "score": scores.get(patent_id, 0.0),
                        }
                    )
    return rankings


def _score(rankings, candidate_path):
    with candidate_path.open(encoding="utf-8-sig", newline="") as file:
        candidates = list(csv.DictReader(file))
    pools = defaultdict(list)
    for row in candidates:
        pools[(row["case_id"], row["technology_area_id"])].append(row)
    by_run = defaultdict(list)
    for row in rankings:
        by_run[(row["case_id"], row["technology_area_id"], row["run_id"])].append(row)

    metrics = (
        "candidate_recall_at_20",
        "hit_at_5",
        "precision_at_5",
        "recall_at_5",
        "mrr_at_5",
        "ndcg_at_5",
    )

    def evaluate_label_source(label_source):
        complete_pools = set()
        pending_pool_count = 0
        for pool_key, pool in pools.items():
            judged = [
                row
                for row in pool
                if row["label_source"] == label_source
                and row["relevant"] in {"0", "1"}
                and (label_source == "ai_draft" or row["review_status"] == "reviewed")
            ]
            if pool and len(judged) == len(pool):
                complete_pools.add(pool_key)
            else:
                pending_pool_count += 1

        per_query = []
        for (case_id, area, run_id), rows in sorted(by_run.items()):
            if (case_id, area) not in complete_pools:
                continue
            pool = pools[(case_id, area)]
            relevant = {row["source_id"] for row in pool if row["relevant"] == "1"}
            rows.sort(key=lambda row: int(row["rank"]))
            retrieved = [row["source_id"] for row in rows]
            record = {
                "case_id": case_id,
                "technology_area_id": area,
                "run_id": run_id,
                "label_source": label_source,
                "judged_candidate_count": len(pool),
                "relevant_candidate_count": len(relevant),
                "no_relevant_in_pool": not relevant,
            }
            if relevant:
                record.update(
                    {
                        "candidate_recall_at_20": recall_at_k(
                            retrieved, relevant, len(retrieved)
                        ),
                        "hit_at_5": hit_at_k(retrieved, relevant, METRIC_K),
                        "precision_at_5": precision_at_k(retrieved, relevant, METRIC_K),
                        "recall_at_5": recall_at_k(retrieved, relevant, METRIC_K),
                        "mrr_at_5": reciprocal_rank(retrieved, relevant, METRIC_K),
                        "ndcg_at_5": ndcg_at_k(retrieved, relevant, METRIC_K),
                    }
                )
            per_query.append(record)
        macro_groups = defaultdict(list)
        for row in per_query:
            if not row["no_relevant_in_pool"]:
                macro_groups[(row["technology_area_id"], row["run_id"])].append(row)
        macro = [
            {
                "technology_area_id": area,
                "run_id": run_id,
                "label_source": label_source,
                "query_count": len(rows),
                **{
                    metric: sum(row[metric] for row in rows) / len(rows)
                    for metric in metrics
                },
            }
            for (area, run_id), rows in sorted(macro_groups.items())
        ]
        return {
            "status": "scored" if complete_pools else "awaiting_labels",
            "complete_query_area_pool_count": len(complete_pools),
            "pending_query_area_pool_count": pending_pool_count,
            "per_query": per_query,
            "macro": macro,
        }

    metrics_by_source = {
        source: evaluate_label_source(source) for source in ("human", "ai_draft")
    }
    sources = {row["label_source"] for row in candidates}
    return {
        "status": (
            "exploratory_only_ai_drafts"
            if sources == {"ai_draft"}
            else "mixed_or_unreviewed_labels"
        ),
        "candidate_count": len(candidates),
        "human_reviewed_candidate_count": sum(
            row["label_source"] == "human"
            and row["review_status"] == "reviewed"
            and row["relevant"] in {"0", "1"}
            for row in candidates
        ),
        "ai_draft_candidate_count": sum(
            row["label_source"] == "ai_draft" for row in candidates
        ),
        "pending_candidate_count": sum(
            row["label_source"] != "human" or row["review_status"] != "reviewed"
            for row in candidates
        ),
        "candidate_pool_limit": "14 patents per area; Recall@20 is exhaustive within this local pool and cannot estimate corpus-wide recall.",
        "label_limit": "AI draft relevance is exploratory only and cannot establish a validated improvement.",
        "metrics_by_label_source": metrics_by_source,
        "per_query": metrics_by_source["ai_draft"]["per_query"],
        "macro": metrics_by_source["ai_draft"]["macro"],
    }


def run(output_dir=OUTPUT_DIR):
    patents = load_patents()
    cases = load_cases()
    output_dir.mkdir(parents=True, exist_ok=True)
    candidate_path = CHUNK_EXPERIMENT_DIR / "candidates.csv"
    if not candidate_path.exists():
        raise FileNotFoundError(f"candidate labels not found: {candidate_path}")
    rankings = _rank_all(patents, cases)
    ranking_path = output_dir / "rankings.csv"
    with ranking_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "case_id",
                "technology_area_id",
                "run_id",
                "rank",
                "source_id",
                "score",
            ],
        )
        writer.writeheader()
        writer.writerows(rankings)
    result = _score(rankings, candidate_path)
    result["corpus_sha256"] = hashlib.sha256(
        (ROOT_DIR / "data/patents/processed/patent_docs.jsonl").read_bytes()
    ).hexdigest()
    result["cases_sha256"] = hashlib.sha256(
        (ROOT_DIR / "evaluation/patent_cases.json").read_bytes()
    ).hexdigest()
    result["ranking_file"] = ranking_path.name
    result["rrf_k"] = RRF_K
    result["section_weights"] = {
        "title_abstract": 2.0,
        "independent_claims": 2.0,
        "dependent_claims": 0.5,
    }
    result["runs"] = list(RUN_FIELDS)
    (output_dir / "metrics.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main():
    parser = argparse.ArgumentParser(
        description="특허 질의·필드 순위 결합 오프라인 실험"
    )
    parser.add_argument("run", choices=["run"])
    parser.add_argument("--out-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    print(json.dumps(run(args.out_dir), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
