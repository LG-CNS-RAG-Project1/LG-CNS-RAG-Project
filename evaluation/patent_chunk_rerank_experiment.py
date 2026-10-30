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
from src.schemas import PatentChunk, PatentClaim, PatentDocument

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


def _claim_map(patent: PatentDocument) -> dict[int, PatentClaim]:
    """Return the claims indexed by number for dependency context assembly."""
    return {claim.claim_number: claim for claim in patent.claim_items}


def _ancestor_numbers(claim_number: int, claims: dict[int, PatentClaim]) -> list[int]:
    """Resolve available parent claims without looping on malformed references."""
    pending = list(claims[claim_number].depends_on)
    seen = set()
    while pending:
        number = pending.pop(0)
        if number in seen or number == claim_number or number not in claims:
            continue
        seen.add(number)
        pending.extend(claims[number].depends_on)
    return sorted(seen)


def build_experiment_chunks(
    patents: list[PatentDocument], area: str, strategy: str
) -> list[PatentChunk]:
    """Build baseline, independent-only, or ancestor-context claim chunks.

    ``independent`` indexes independent claims for candidate retrieval; dependent
    claims remain available in the source document as auxiliary evidence.
    ``parent_context`` keeps every claim's exact text and adds referenced parent
    claim text to dependent claim chunks.
    """
    if strategy not in {"baseline", "independent", "parent_context"}:
        raise ValueError("strategy must be baseline, independent, or parent_context")
    chunks = []
    for patent in patents:
        if area not in patent.technology_area_ids:
            continue
        if patent.abstract.strip():
            chunks.append(
                PatentChunk(
                    chunk_id=f"{patent.patent_id}_{patent.claim_version_id or 'noversion'}_abstract_0",
                    patent_id=patent.patent_id,
                    section="abstract",
                    text=patent.abstract.strip(),
                    chunk_index=0,
                    version_id=patent.claim_version_id,
                )
            )
        claim_map = _claim_map(patent)
        selected = [
            claim
            for claim in patent.claim_items
            if strategy != "independent" or claim.claim_type == "independent"
        ]
        for index, claim in enumerate(selected):
            content = claim.text
            if strategy == "parent_context" and claim.claim_type == "dependent":
                ancestors = _ancestor_numbers(claim.claim_number, claim_map)
                context = [
                    f"상위 청구항 {number} 원문: {claim_map[number].text}"
                    for number in ancestors
                ]
                if context:
                    content = "\n".join(
                        context
                        + [f"현재 청구항 {claim.claim_number} 원문: {claim.text}"]
                    )
            chunks.append(
                PatentChunk(
                    chunk_id=(
                        f"{patent.patent_id}_{claim.version_id or patent.claim_version_id or 'noversion'}"
                        f"_claim_{claim.claim_number}_{strategy}"
                    ),
                    patent_id=patent.patent_id,
                    section="claims",
                    text=content,
                    chunk_index=index,
                    claim_number=claim.claim_number,
                    claim_type=claim.claim_type,
                    depends_on=claim.depends_on,
                    version_id=claim.version_id or patent.claim_version_id,
                )
            )
    return chunks


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
