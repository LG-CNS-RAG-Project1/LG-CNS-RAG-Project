"""Run controlled chunking, patent aggregation, and reranking experiments.

The experiment uses the checked-in processed patent corpus and a local sparse
retriever so that preparation does not collect patents or call embedding APIs.
"""

import argparse
import csv
import hashlib
import json
import time
from collections import defaultdict
from pathlib import Path

from evaluation.evaluate import (
    hit_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from evaluation.patent_labeling import load_cases
from src.schemas import PatentDocument

ROOT_DIR = Path(__file__).resolve().parents[1]
PATENTS_PATH = ROOT_DIR / "data" / "patents" / "processed" / "patent_docs.jsonl"
OUTPUT_DIR = ROOT_DIR / "data" / "patents" / "processed" / "chunk_rerank_experiment"
AREAS = {"SF-05": "SF-05", "SF-02": "SF-02"}
TOP_K = 20
METRIC_K = 5
LABEL_FIELDS = [
    "case_id",
    "technology_area_id",
    "query",
    "source_id",
    "title",
    "abstract",
    "claim_evidence",
    "claim_numbers",
    "claim_version_ids",
    "retrieved_by",
    "relevant",
    "note",
    "review_status",
    "label_source",
]


def load_patents(path: Path = PATENTS_PATH) -> list[PatentDocument]:
    """Load and validate normalized patent documents from JSONL."""
    if not path.exists():
        raise FileNotFoundError(f"processed patent corpus not found: {path}")
    return [
        PatentDocument.model_validate_json(line)
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def corpus_fingerprint(patents: list[PatentDocument]) -> str:
    """Hash canonical document content and identifiers for experiment provenance."""
    payload = [
        patent.model_dump(mode="json")
        for patent in sorted(patents, key=lambda item: item.patent_id)
    ]
    canonical = json.dumps(
        payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def corpus_inventory(patents: list[PatentDocument]) -> dict:
    """Summarize field coverage and duplicate document-version identifiers."""
    rows = {}
    for area in AREAS:
        selected = [patent for patent in patents if area in patent.technology_area_ids]
        versions = [
            patent.publication_number
            for patent in selected
            if patent.publication_number
        ]
        rows[area] = {
            "patent_count": len({patent.patent_id for patent in selected}),
            "abstract_count": sum(bool(patent.abstract.strip()) for patent in selected),
            "claims_text_count": sum(
                bool(patent.claims.strip()) for patent in selected
            ),
            "structured_claim_count": sum(
                bool(patent.claim_items) for patent in selected
            ),
            "independent_claim_count": sum(
                claim.claim_type == "independent"
                for patent in selected
                for claim in patent.claim_items
            ),
            "dependent_claim_count": sum(
                claim.claim_type == "dependent"
                for patent in selected
                for claim in patent.claim_items
            ),
            "versioned_claim_document_count": sum(
                bool(patent.claim_version_id) for patent in selected
            ),
            "duplicate_publication_number_rows": len(versions) - len(set(versions)),
        }
    return {
        "corpus_path": str(PATENTS_PATH.relative_to(ROOT_DIR)),
        "corpus_sha256": corpus_fingerprint(patents),
        "document_count": len(patents),
        "areas": rows,
    }


def write_inventory(output_dir: Path = OUTPUT_DIR) -> dict:
    """Write a read-only corpus inventory into a new or existing experiment folder."""
    output_dir.mkdir(parents=True, exist_ok=True)
    result = corpus_inventory(load_patents())
    cases_path = ROOT_DIR / "evaluation" / "patent_cases.json"
    result["cases_sha256"] = hashlib.sha256(cases_path.read_bytes()).hexdigest()
    result["case_count"] = len(load_cases())
    result["label_policy"] = (
        "Only reviewed 0/1 labels with label_source=human are ground truth."
    )
    (output_dir / "inventory.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="특허 청킹·집계·리랭킹 통제 실험")
    subparsers = parser.add_subparsers(dest="command", required=True)
    inventory_parser = subparsers.add_parser(
        "inventory", help="코퍼스 지문과 문헌 범위 기록"
    )
    inventory_parser.add_argument("--out-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    if args.command == "inventory":
        result = write_inventory(args.out_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
