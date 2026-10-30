"""Compare SF-05 patent queries across local SF-05 and SF-02 patent corpora.

Run writes a blind candidate pool and ranked results under the ignored patent
processed-data directory. Score calculates retrieval metrics after human labels.
"""

import argparse
import csv
import hashlib
import json
from collections import defaultdict
from pathlib import Path

import chromadb
from chromadb.config import Settings

from evaluation.evaluate import (
    hit_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from evaluation.patent_labeling import load_cases
from src.generation.patent_analysis import kipris_application_search_url
from src.retrieval.patent_search import search_patents

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "data" / "patents" / "processed" / "domain_experiment"
LOCAL_CHROMA_DIR = ROOT_DIR / "data" / "patents" / "chroma"
CASES_PATH = ROOT_DIR / "evaluation" / "patent_cases.json"
CORPORA = {"A": "SF-05", "B": "SF-02"}
MODES = ("dense", "bm25", "hybrid")
POOL_K = 20
METRIC_K = 5
RANK_FIELDS = [
    "case_id",
    "corpus_id",
    "mode",
    "rank",
    "source_id",
    "title",
    "summary",
    "score",
]
CANDIDATE_FIELDS = [
    "case_id",
    "corpus_id",
    "query",
    "technical_element",
    "source_id",
    "title",
    "summary",
    "url",
    "relevant",
    "note",
    "review_status",
    "label_source",
]


def sha256(path: Path) -> str:
    """Return a file fingerprint for experiment provenance."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def collection_sha256(collection) -> str:
    """Fingerprint a local Chroma collection without exporting its contents."""
    data = collection.get(include=["documents", "metadatas"])
    rows = sorted(
        zip(data["ids"], data["documents"], data["metadatas"]), key=lambda row: row[0]
    )
    serialized = json.dumps(
        rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(serialized.encode("utf-8")).hexdigest()


def open_local_collection():
    """Open the repository-local patent index without remote Chroma configuration."""
    if not LOCAL_CHROMA_DIR.exists():
        raise FileNotFoundError(f"local Chroma directory not found: {LOCAL_CHROMA_DIR}")
    client = chromadb.PersistentClient(
        path=str(LOCAL_CHROMA_DIR), settings=Settings(anonymized_telemetry=False)
    )
    return client.get_collection("patents")


def preserve_candidate_labels(candidate_map: dict, candidates_path: Path) -> None:
    """재검색 시 동일한 후보의 기존 사람 검토 상태와 메모를 보존한다."""
    if not candidates_path.exists():
        return
    with candidates_path.open(encoding="utf-8-sig", newline="") as file:
        previous = list(csv.DictReader(file))
    review_fields = ("relevant", "note", "review_status", "label_source")
    for row in previous:
        key = (row.get("case_id"), row.get("corpus_id"), row.get("source_id"))
        if key not in candidate_map:
            continue
        for field in review_fields:
            if field in row and row[field] != "":
                candidate_map[key][field] = row[field]


def run_experiment(output_dir: Path = OUTPUT_DIR, top_k: int = POOL_K) -> dict:
    """Search SF-05 queries against both local corpora and export blinded labels."""
    if top_k < METRIC_K:
        raise ValueError(f"top_k must be at least {METRIC_K}")
    cases = [case for case in load_cases() if case.get("technology_area_id") == "SF-05"]
    if not cases:
        raise ValueError("no SF-05 cases found in evaluation/patent_cases.json")

    collection = open_local_collection()
    if collection.count() == 0:
        raise RuntimeError("local patent Chroma collection is empty")

    rankings = []
    candidate_map = {}
    candidates_path = output_dir / "candidates.csv"
    for case in cases:
        for corpus_id, area_id in CORPORA.items():
            for mode in MODES:
                hits = search_patents(
                    case["query"],
                    collection=collection,
                    top_k=top_k,
                    retrieval_mode=mode,
                    technology_area_id=area_id,
                )
                for rank, hit in enumerate(hits, 1):
                    document = hit.document
                    rankings.append(
                        {
                            "case_id": case["case_id"],
                            "corpus_id": corpus_id,
                            "mode": mode,
                            "rank": rank,
                            "source_id": document.source_id,
                            "title": document.title,
                            "summary": document.content[:500],
                            "score": hit.rerank_score
                            or hit.rrf_score
                            or hit.dense_score
                            or hit.bm25_score
                            or "",
                        }
                    )
                    key = (case["case_id"], corpus_id, document.source_id)
                    source_url = document.metadata.get("source_url") or ""
                    if not source_url:
                        source_url = (
                            kipris_application_search_url(
                                document.metadata.get("application_number")
                                or document.source_id
                            )
                            or ""
                        )
                    candidate_map.setdefault(
                        key,
                        {
                            "case_id": case["case_id"],
                            "corpus_id": corpus_id,
                            "query": case["query"],
                            "technical_element": case["technical_element"],
                            "source_id": document.source_id,
                            "title": document.title,
                            "summary": document.content[:800],
                            "url": source_url,
                            "relevant": "",
                            "note": "",
                            "review_status": "to_review",
                            "label_source": "unreviewed",
                        },
                    )

    output_dir.mkdir(parents=True, exist_ok=True)
    rankings_path = output_dir / "rankings.csv"
    preserve_candidate_labels(candidate_map, candidates_path)
    with rankings_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=RANK_FIELDS)
        writer.writeheader()
        writer.writerows(rankings)
    with candidates_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CANDIDATE_FIELDS)
        writer.writeheader()
        writer.writerows(candidate_map[key] for key in sorted(candidate_map))

    cases_path = CASES_PATH
    area_documents = {
        area_id: collection.get(where={f"area_{area_id}": True}, include=["metadatas"])
        for area_id in CORPORA.values()
    }
    metadata = {
        "status": "awaiting_human_labels",
        "corpora": CORPORA,
        "modes": list(MODES),
        "pool_k": top_k,
        "metric_k": METRIC_K,
        "embedding_model": "text-embedding-3-small",
        "local_chroma_dir": str(LOCAL_CHROMA_DIR.relative_to(ROOT_DIR)),
        "local_collection": "patents",
        "collection_chunk_count": collection.count(),
        "collection_snapshot_sha256": collection_sha256(collection),
        "filtered_chunk_counts": {
            area_id: len(
                collection.get(where={f"area_{area_id}": True}, include=[])["ids"]
            )
            for area_id in CORPORA.values()
        },
        "filtered_patent_counts": {
            area_id: len(
                {
                    item.get("source_id")
                    for item in area_documents[area_id]["metadatas"]
                    if item.get("source_id")
                }
            )
            for area_id in CORPORA.values()
        },
        "sf05_query_count": len(cases),
        "candidate_count": len(candidate_map),
        "human_reviewed_candidate_count": sum(
            row["review_status"] == "reviewed" and row["label_source"] == "human"
            for row in candidate_map.values()
        ),
        "ranked_row_count": len(rankings),
        "cases_sha256": sha256(cases_path),
        "rankings_file": rankings_path.name,
        "candidates_file": candidates_path.name,
        "label_policy": "Only review_status=reviewed and label_source=human count as ground truth.",
        "note": "Recall is measured against relevant documents in the judged union pool, not the full patent corpus.",
    }
    metadata_path = output_dir / "metadata.json"
    metadata_path.write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return metadata


def score_experiment(output_dir: Path = OUTPUT_DIR) -> dict:
    """Calculate pooled-candidate metrics only when every candidate is judged."""
    candidates_path = output_dir / "candidates.csv"
    rankings_path = output_dir / "rankings.csv"
    with candidates_path.open(encoding="utf-8-sig", newline="") as file:
        candidates = list(csv.DictReader(file))
    with rankings_path.open(encoding="utf-8-sig", newline="") as file:
        rankings = list(csv.DictReader(file))

    pending = [
        row
        for row in candidates
        if row.get("relevant", "").strip() not in {"0", "1"}
        or row.get("review_status", "").strip() != "reviewed"
        or row.get("label_source", "").strip() != "human"
    ]
    if pending:
        raise ValueError(
            f"{len(pending)} candidates still need a human-reviewed 0/1 label in {candidates_path}"
        )
    relevant_by_pool = defaultdict(set)
    for row in candidates:
        if row["relevant"].strip() == "1":
            relevant_by_pool[(row["case_id"], row["corpus_id"])].add(row["source_id"])

    ranked_by_run = defaultdict(list)
    for row in rankings:
        ranked_by_run[(row["case_id"], row["corpus_id"], row["mode"])].append(row)
    grouped = defaultdict(list)
    for (case_id, corpus_id, mode), rows in ranked_by_run.items():
        rows.sort(key=lambda row: int(row["rank"]))
        retrieved = [row["source_id"] for row in rows]
        relevant = relevant_by_pool[(case_id, corpus_id)]
        grouped[(corpus_id, mode)].append(
            {
                "case_id": case_id,
                "n_relevant_in_pool": len(relevant),
                "judged_candidate_count": sum(
                    row["case_id"] == case_id and row["corpus_id"] == corpus_id
                    for row in candidates
                ),
                "hit_at_5": hit_at_k(retrieved, relevant, METRIC_K),
                "recall_at_pool_k": recall_at_k(retrieved, relevant, len(retrieved)),
                "recall_at_5": recall_at_k(retrieved, relevant, METRIC_K),
                "precision_at_5": precision_at_k(retrieved, relevant, METRIC_K),
                "mrr_at_5": reciprocal_rank(retrieved, relevant, METRIC_K),
                "ndcg_at_5": ndcg_at_k(retrieved, relevant, METRIC_K),
            }
        )

    summary = []
    for (corpus_id, mode), rows in sorted(grouped.items()):
        result = {
            key: sum(row[key] for row in rows) / len(rows)
            for key in (
                "hit_at_5",
                "recall_at_5",
                "recall_at_pool_k",
                "precision_at_5",
                "mrr_at_5",
                "ndcg_at_5",
            )
        }
        result.update(
            {
                "corpus_id": corpus_id,
                "corpus_area": CORPORA[corpus_id],
                "mode": mode,
                "case_count": len(rows),
                "judged_candidate_count": sum(
                    row["judged_candidate_count"] for row in rows
                ),
                "cases_with_no_relevant_in_pool": sum(
                    row["n_relevant_in_pool"] == 0 for row in rows
                ),
            }
        )
        summary.append(result)

    result_path = output_dir / "metrics.json"
    result_path.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"status": "scored", "summary": summary, "output": str(result_path)}


def main() -> None:
    parser = argparse.ArgumentParser(description="SF-05 특허 도메인별 검색 비교 실험")
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser("run", help="로컬 색인 검색과 라벨 후보 생성")
    run_parser.add_argument("--top-k", type=int, default=POOL_K)
    run_parser.add_argument("--out-dir", type=Path, default=OUTPUT_DIR)
    score_parser = subparsers.add_parser("score", help="사람 라벨을 지표로 집계")
    score_parser.add_argument("--out-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()

    if args.command == "run":
        report = run_experiment(args.out_dir, args.top_k)
    else:
        report = score_experiment(args.out_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
