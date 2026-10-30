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
from collections import Counter
from pathlib import Path

from evaluation.evaluate import (
    hit_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from evaluation.patent_labeling import load_cases
from src.generation.patent_analysis import kipris_application_search_url
from src.ingestion.patent_processor import build_chunks
from src.retrieval.engine import bm25_scores
from src.retrieval.schemas import SearchDocument
from src.schemas import PatentChunk, PatentClaim, PatentDocument

ROOT_DIR = Path(__file__).resolve().parents[1]
PATENTS_PATH = ROOT_DIR / "data" / "patents" / "processed" / "patent_docs.jsonl"
OUTPUT_DIR = ROOT_DIR / "data" / "patents" / "processed" / "chunk_rerank_experiment"
LOCAL_CHROMA_DIR = ROOT_DIR / "data" / "patents" / "chroma"
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
    "version_id",
    "application_number",
    "publication_number",
    "url",
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


def patent_version_id(patent: PatentDocument) -> str:
    """Return the best available stable identifier for a document version."""
    return patent.claim_version_id or patent.publication_number or "unknown"


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
    result = {
        "corpus_path": str(PATENTS_PATH.relative_to(ROOT_DIR)),
        "corpus_sha256": corpus_fingerprint(patents),
        "document_count": len(patents),
        "duplicate_patent_id_rows": sum(
            count - 1
            for count in Counter(patent.patent_id for patent in patents).values()
            if count > 1
        ),
        "areas": rows,
    }
    result["local_index"] = local_index_inventory(patents)
    return result


def local_index_inventory(patents: list[PatentDocument]) -> dict:
    """Fingerprint the local Chroma snapshot and verify baseline chunk parity."""
    if not LOCAL_CHROMA_DIR.exists():
        return {"status": "not_available", "chunk_content_matches_processed": None}
    try:
        import chromadb
        from chromadb.config import Settings

        client = chromadb.PersistentClient(
            path=str(LOCAL_CHROMA_DIR), settings=Settings(anonymized_telemetry=False)
        )
        collection = client.get_collection("patents")
        data = collection.get(include=["documents", "metadatas"])
    except Exception as exc:
        return {
            "status": "unavailable",
            "error_type": type(exc).__name__,
            "chunk_content_matches_processed": None,
        }
    rows = sorted(
        zip(data["ids"], data["documents"], data["metadatas"]), key=lambda row: row[0]
    )
    canonical = json.dumps(
        rows, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    )
    processed = {chunk.chunk_id: chunk.text for chunk in build_chunks(patents)}
    indexed = dict(zip(data["ids"], data["documents"]))
    matched_ids = set(processed) & set(indexed)
    area_stats = {}
    for area in AREAS:
        metadata = [item for item in data["metadatas"] if item.get(f"area_{area}")]
        area_stats[area] = {
            "chunk_count": len(metadata),
            "patent_count": len({item.get("source_id") for item in metadata}),
        }
    return {
        "status": "available",
        "path": str(LOCAL_CHROMA_DIR.relative_to(ROOT_DIR)),
        "collection": "patents",
        "chunk_count": len(data["ids"]),
        "patent_counts_by_area": area_stats,
        "snapshot_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "processed_chunk_count": len(processed),
        "matching_chunk_id_count": len(matched_ids),
        "chunk_content_matches_processed": len(processed) == len(indexed)
        and len(matched_ids) == len(processed)
        and all(processed[key] == indexed[key] for key in matched_ids),
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


AGGREGATION_WEIGHTS = {
    "abstract": 1.0,
    "independent": 1.5,
    "dependent": 0.75,
    "unclassified": 1.0,
}


def aggregate_patent_scores(
    rows: list[dict], strategy: str, top_n: int = 3
) -> list[dict]:
    """Aggregate chunk scores without merging distinct patent publication versions.

    Returned rows retain the best evidence chunk and all matched sections and
    claim coordinates so a rank can be audited against its source.
    """
    if strategy not in {"max", "top_n_mean", "section_weighted"}:
        raise ValueError("strategy must be max, top_n_mean, or section_weighted")
    if top_n < 1:
        raise ValueError("top_n must be at least 1")
    grouped = defaultdict(list)
    for row in rows:
        version = row.get("version_id") or row.get("publication_number") or "unknown"
        grouped[(row["patent_id"], version)].append(row)
    output = []
    for (patent_id, version), chunks in grouped.items():
        ordered = sorted(chunks, key=lambda item: float(item["score"]), reverse=True)
        if strategy == "max":
            score = float(ordered[0]["score"])
        elif strategy == "top_n_mean":
            score = sum(float(item["score"]) for item in ordered[:top_n]) / min(
                top_n, len(ordered)
            )
        else:
            section_scores = {}
            for item in ordered:
                section = item.get("section", "unknown")
                claim_type = item.get("claim_type") or "unclassified"
                key = "abstract" if section == "abstract" else claim_type
                section_scores[key] = max(
                    section_scores.get(key, float("-inf")), float(item["score"])
                )
            numerator = sum(
                value * AGGREGATION_WEIGHTS.get(section, 1.0)
                for section, value in section_scores.items()
            )
            denominator = sum(
                AGGREGATION_WEIGHTS.get(section, 1.0) for section in section_scores
            )
            score = numerator / denominator
        representative = ordered[0]
        output.append(
            {
                "patent_id": patent_id,
                "version_id": version,
                "score": score,
                "representative_chunk_id": representative["chunk_id"],
                "representative_section": representative.get("section", "unknown"),
                "matched_sections": sorted(
                    {item.get("section", "unknown") for item in chunks}
                ),
                "claim_numbers": sorted(
                    {
                        int(item["claim_number"])
                        for item in chunks
                        if item.get("claim_number")
                    }
                ),
                "depends_on": {
                    str(item["claim_number"]): sorted(set(item.get("depends_on", [])))
                    for item in chunks
                    if item.get("claim_number")
                },
                "chunk_count": len(chunks),
            }
        )
    return sorted(
        output, key=lambda item: (-item["score"], item["patent_id"], item["version_id"])
    )


def build_reranker_document(patent: PatentDocument, profile: str) -> SearchDocument:
    """Format a patent candidate for controlled Cross-Encoder input profiles."""
    if profile not in {"title_abstract_independent", "claims_only"}:
        raise ValueError("profile must be title_abstract_independent or claims_only")
    claims = patent.claim_items
    if profile == "title_abstract_independent":
        independent = [claim for claim in claims if claim.claim_type == "independent"]
        sections = [
            f"발명의 명칭: {patent.title}" if patent.title.strip() else "",
            f"초록: {patent.abstract}" if patent.abstract.strip() else "",
            *[f"독립항 {claim.claim_number}: {claim.text}" for claim in independent],
        ]
    else:
        sections = [
            f"청구항 {claim.claim_number} ({claim.claim_type}): {claim.text}"
            for claim in claims
        ]
    content = "\n".join(section for section in sections if section)
    if not content.strip():
        content = patent.title or patent.patent_id
    version = patent.claim_version_id or patent.publication_number or "unknown"
    return SearchDocument(
        chunk_id=f"{patent.patent_id}:{version}:rerank:{profile}",
        source_id=patent.patent_id,
        source_type="patent",
        title="",
        content=content,
        metadata={
            "profile": profile,
            "input_sections": (
                ["title", "abstract", "independent_claims"]
                if profile == "title_abstract_independent"
                else ["claims"]
            ),
            "version_id": version,
            "publication_number": patent.publication_number,
            "application_number": patent.application_number,
        },
    )


CHUNKING_RUNS = [
    ("baseline_max", "baseline", "max"),
    ("independent_max", "independent", "max"),
    ("parent_context_max", "parent_context", "max"),
    ("baseline_top3_mean", "baseline", "top_n_mean"),
    ("baseline_section_weighted", "baseline", "section_weighted"),
]
RERANKER_MODEL = "BAAI/bge-reranker-v2-m3"
RANK_FIELDS = [
    "case_id",
    "technology_area_id",
    "run_id",
    "rank",
    "source_id",
    "version_id",
    "score",
    "reranker_score",
    "representative_chunk_id",
    "representative_section",
    "matched_sections",
    "claim_numbers",
    "depends_on",
    "chunk_count",
    "search_ms",
    "model_load_ms",
    "rerank_ms",
    "reranker_profile",
]


def rank_chunks(
    query: str,
    patents: list[PatentDocument],
    area: str,
    chunk_strategy: str,
    aggregation: str,
) -> tuple[list[dict], float]:
    """Run sparse retrieval on one chunk strategy and aggregate patent versions."""
    started = time.perf_counter()
    selected = [patent for patent in patents if area in patent.technology_area_ids]
    by_patent = {patent.patent_id: patent for patent in selected}
    chunks = build_experiment_chunks(patents, area, chunk_strategy)
    documents = [
        SearchDocument(
            chunk_id=chunk.chunk_id,
            source_id=chunk.patent_id,
            source_type="patent",
            title=by_patent[chunk.patent_id].title,
            content=chunk.text,
            metadata={
                "section": chunk.section,
                "claim_number": chunk.claim_number,
                "claim_type": chunk.claim_type,
                "depends_on": chunk.depends_on,
                "version_id": chunk.version_id,
            },
        )
        for chunk in chunks
    ]
    scored = bm25_scores(query, documents)
    score_rows = []
    for document, score in scored:
        patent = by_patent[document.source_id]
        score_rows.append(
            {
                "patent_id": patent.patent_id,
                "version_id": document.metadata.get("version_id")
                or patent.publication_number
                or "unknown",
                "publication_number": patent.publication_number,
                "chunk_id": document.chunk_id,
                "section": document.metadata.get("section"),
                "claim_type": document.metadata.get("claim_type"),
                "claim_number": document.metadata.get("claim_number"),
                "depends_on": document.metadata.get("depends_on", []),
                "score": score,
            }
        )
    ranked = aggregate_patent_scores(score_rows, aggregation)
    return ranked, (time.perf_counter() - started) * 1000


def _write_csv(path: Path, fields: list[str], rows: list[dict]) -> None:
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)


def _old_candidate_labels(path: Path) -> dict[tuple[str, str, str], dict]:
    if not path.exists():
        return {}
    with path.open(encoding="utf-8-sig", newline="") as file:
        return {
            (row["case_id"], row["technology_area_id"], row["source_id"]): row
            for row in csv.DictReader(file)
        }


def run_experiment(
    output_dir: Path = OUTPUT_DIR,
    candidate_k: int = TOP_K,
    with_cross_encoder: bool = False,
) -> dict:
    """Export blinded review rows and run fixed-candidate local retrieval variants."""
    if candidate_k < METRIC_K:
        raise ValueError(f"candidate_k must be at least {METRIC_K}")
    patents = load_patents()
    cases = load_cases()
    if not patents or not cases:
        raise ValueError("patent corpus and evaluation cases must both be non-empty")
    duplicate_ids = [
        patent_id
        for patent_id, count in Counter(patent.patent_id for patent in patents).items()
        if count > 1
    ]
    if duplicate_ids:
        raise ValueError(
            "multiple document versions share a patent_id; split versions before ranking: "
            + ", ".join(sorted(duplicate_ids))
        )
    output_dir.mkdir(parents=True, exist_ok=True)
    inventory = corpus_inventory(patents)
    cases_path = ROOT_DIR / "evaluation" / "patent_cases.json"
    inventory["cases_sha256"] = hashlib.sha256(cases_path.read_bytes()).hexdigest()
    (output_dir / "inventory.json").write_text(
        json.dumps(inventory, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )

    rankings = []
    candidates = {}
    reranker_status = "not_requested"
    cross_encoder = None
    model_load_ms = 0.0
    if with_cross_encoder:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError:
            reranker_status = "unavailable_sentence_transformers_missing"
        else:
            load_started = time.perf_counter()
            cross_encoder = CrossEncoder(RERANKER_MODEL)
            model_load_ms = (time.perf_counter() - load_started) * 1000
            reranker_status = "loaded"

    for case in cases:
        for area in AREAS:
            area_patents = [
                patent for patent in patents if area in patent.technology_area_ids
            ]
            if not area_patents:
                continue
            by_patent = {patent.patent_id: patent for patent in area_patents}
            per_run = {}
            for run_id, chunk_strategy, aggregation in CHUNKING_RUNS:
                ranked, search_ms = rank_chunks(
                    case["query"], patents, area, chunk_strategy, aggregation
                )
                per_run[run_id] = ranked[:candidate_k]
                for rank, row in enumerate(per_run[run_id], 1):
                    rankings.append(
                        {
                            "case_id": case["case_id"],
                            "technology_area_id": area,
                            "run_id": run_id,
                            "rank": rank,
                            "source_id": row["patent_id"],
                            "version_id": row["version_id"],
                            "score": row["score"],
                            "reranker_score": "",
                            "representative_chunk_id": row["representative_chunk_id"],
                            "representative_section": row["representative_section"],
                            "matched_sections": json.dumps(
                                row["matched_sections"], ensure_ascii=False
                            ),
                            "claim_numbers": json.dumps(
                                row["claim_numbers"], ensure_ascii=False
                            ),
                            "depends_on": json.dumps(
                                row["depends_on"], ensure_ascii=False
                            ),
                            "chunk_count": row["chunk_count"],
                            "search_ms": round(search_ms, 3),
                            "model_load_ms": 0.0,
                            "rerank_ms": 0.0,
                            "reranker_profile": "none",
                        }
                    )

            fixed_pool = per_run["baseline_max"]
            if cross_encoder and fixed_pool:
                for profile in ("title_abstract_independent", "claims_only"):
                    rerank_documents = [
                        build_reranker_document(by_patent[row["patent_id"]], profile)
                        for row in fixed_pool
                    ]
                    started = time.perf_counter()
                    scores = cross_encoder.predict(
                        [
                            (case["query"], document.content)
                            for document in rerank_documents
                        ]
                    )
                    rerank_ms = (time.perf_counter() - started) * 1000
                    reranked = sorted(
                        zip(fixed_pool, scores),
                        key=lambda item: (-float(item[1]), item[0]["patent_id"]),
                    )
                    for rank, (row, score) in enumerate(reranked, 1):
                        rankings.append(
                            {
                                "case_id": case["case_id"],
                                "technology_area_id": area,
                                "run_id": f"fixed_pool_{profile}",
                                "rank": rank,
                                "source_id": row["patent_id"],
                                "version_id": row["version_id"],
                                "score": float(score),
                                "reranker_score": float(score),
                                "representative_chunk_id": row[
                                    "representative_chunk_id"
                                ],
                                "representative_section": row["representative_section"],
                                "matched_sections": json.dumps(
                                    row["matched_sections"], ensure_ascii=False
                                ),
                                "claim_numbers": json.dumps(
                                    row["claim_numbers"], ensure_ascii=False
                                ),
                                "depends_on": json.dumps(
                                    row["depends_on"], ensure_ascii=False
                                ),
                                "chunk_count": row["chunk_count"],
                                "search_ms": 0.0,
                                "model_load_ms": round(model_load_ms, 3),
                                "rerank_ms": round(rerank_ms, 3),
                                "reranker_profile": profile,
                            }
                        )

            candidate_ids = {
                row["patent_id"] for run in per_run.values() for row in run
            }
            for patent_id in candidate_ids:
                patent = by_patent[patent_id]
                claim_text = "\n".join(
                    f"청구항 {claim.claim_number} ({claim.claim_type}, 상위항 {claim.depends_on}): {claim.text}"
                    for claim in patent.claim_items
                )
                key = (case["case_id"], area, patent.patent_id)
                candidates[key] = {
                    "case_id": case["case_id"],
                    "technology_area_id": area,
                    "query": case["query"],
                    "source_id": patent.patent_id,
                    "title": patent.title,
                    "abstract": patent.abstract,
                    "claim_evidence": claim_text,
                    "claim_numbers": json.dumps(
                        [claim.claim_number for claim in patent.claim_items],
                        ensure_ascii=False,
                    ),
                    "claim_version_ids": patent.claim_version_id or "",
                    "version_id": patent_version_id(patent),
                    "application_number": patent.application_number or "",
                    "publication_number": patent.publication_number or "",
                    "url": patent.source_url
                    or kipris_application_search_url(
                        patent.application_number or patent.patent_id
                    )
                    or "",
                    "relevant": "",
                    "note": "",
                    "review_status": "to_review",
                    "label_source": "unreviewed",
                }

    candidates_path = output_dir / "candidates.csv"
    old_labels = _old_candidate_labels(candidates_path)
    for key, row in candidates.items():
        previous = old_labels.get(key, {})
        for field in ("relevant", "note", "review_status", "label_source"):
            if previous.get(field):
                row[field] = previous[field]
    _write_csv(output_dir / "rankings.csv", RANK_FIELDS, rankings)
    _write_csv(
        output_dir / "candidates.csv",
        LABEL_FIELDS,
        [candidates[key] for key in sorted(candidates)],
    )
    reviewed_count = sum(
        row["review_status"] == "reviewed"
        and row["label_source"] == "human"
        and row["relevant"] in {"0", "1"}
        for row in candidates.values()
    )
    result = {
        "status": (
            "awaiting_human_labels"
            if reviewed_count < len(candidates)
            else "ready_to_score"
        ),
        "corpus_sha256": inventory["corpus_sha256"],
        "cases_sha256": inventory["cases_sha256"],
        "candidate_count": len(candidates),
        "human_reviewed_count": reviewed_count,
        "ranked_row_count": len(rankings),
        "candidate_k_requested": candidate_k,
        "metric_k": METRIC_K,
        "candidate_count_by_area": {
            area: len(
                {
                    patent.patent_id
                    for patent in patents
                    if area in patent.technology_area_ids
                }
            )
            for area in AREAS
        },
        "chunking_and_aggregation_runs": [name for name, _, _ in CHUNKING_RUNS],
        "reranker_status": reranker_status,
        "reranker_model": RERANKER_MODEL if with_cross_encoder else "none",
        "model_load_ms": round(model_load_ms, 3),
        "candidate_policy": "Reranker profiles share the baseline top-K pool; chunk strategies rank the same complete area corpus.",
        "label_policy": "Only reviewed 0/1 labels with label_source=human are ground truth.",
        "scope_limit": "The local sparse retriever ranks at most 14 patents per area; results do not generalize beyond this corpus snapshot.",
    }
    (output_dir / "metadata.json").write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return result


def score_experiment(output_dir: Path = OUTPUT_DIR) -> dict:
    """Score fully human-judged query-area pools and report label coverage."""
    with (output_dir / "candidates.csv").open(encoding="utf-8-sig", newline="") as file:
        candidates = list(csv.DictReader(file))
    with (output_dir / "rankings.csv").open(encoding="utf-8-sig", newline="") as file:
        rankings = list(csv.DictReader(file))
    candidate_groups = defaultdict(list)
    for row in candidates:
        candidate_groups[(row["case_id"], row["technology_area_id"])].append(row)
    rank_groups = defaultdict(list)
    for row in rankings:
        rank_groups[(row["case_id"], row["technology_area_id"], row["run_id"])].append(
            row
        )
    complete = set()
    pending = hold = judged_count = invalid_count = 0
    for key, rows in candidate_groups.items():
        judged = [
            row
            for row in rows
            if row["review_status"] == "reviewed"
            and row["label_source"] == "human"
            and row["relevant"] in {"0", "1"}
        ]
        judged_count += len(judged)
        pending += sum(
            row["review_status"] not in {"reviewed", "hold"}
            or (
                row["review_status"] == "reviewed"
                and not (
                    row["label_source"] == "human" and row["relevant"] in {"0", "1"}
                )
            )
            for row in rows
        )
        hold += sum(row["review_status"] == "hold" for row in rows)
        invalid_count += sum(
            row["relevant"] not in {"", "0", "1"}
            or row["review_status"] not in {"to_review", "reviewed", "hold"}
            or row["label_source"] not in {"unreviewed", "human", "ai_draft"}
            for row in rows
        )
        if rows and len(judged) == len(rows):
            complete.add(key)
    per_query = []
    for (case_id, area, run_id), rows in sorted(rank_groups.items()):
        if (case_id, area) not in complete:
            continue
        candidate_rows = candidate_groups[(case_id, area)]
        relevant = {
            row["source_id"] for row in candidate_rows if row["relevant"] == "1"
        }
        rows.sort(key=lambda row: int(row["rank"]))
        retrieved = [row["source_id"] for row in rows]
        has_relevant = bool(relevant)
        per_query.append(
            {
                "case_id": case_id,
                "technology_area_id": area,
                "run_id": run_id,
                "candidate_pool_size": len(candidate_rows),
                "judged_candidate_count": len(candidate_rows),
                "relevant_candidate_count": len(relevant),
                "no_relevant_in_pool": not has_relevant,
                "unjudged_top5_count": sum(
                    source_id not in {row["source_id"] for row in candidate_rows}
                    for source_id in retrieved[:METRIC_K]
                ),
                "candidate_recall_at_k": (
                    recall_at_k(retrieved, relevant, len(retrieved))
                    if has_relevant
                    else None
                ),
                "hit_at_5": (
                    hit_at_k(retrieved, relevant, METRIC_K) if has_relevant else None
                ),
                "precision_at_5": (
                    precision_at_k(retrieved, relevant, METRIC_K)
                    if has_relevant
                    else None
                ),
                "recall_at_5": (
                    recall_at_k(retrieved, relevant, METRIC_K) if has_relevant else None
                ),
                "mrr_at_5": (
                    reciprocal_rank(retrieved, relevant, METRIC_K)
                    if has_relevant
                    else None
                ),
                "ndcg_at_5": (
                    ndcg_at_k(retrieved, relevant, METRIC_K) if has_relevant else None
                ),
                "search_ms": float(rows[0]["search_ms"] or 0),
                "model_load_ms": float(rows[0]["model_load_ms"] or 0),
                "rerank_ms": float(rows[0]["rerank_ms"] or 0),
            }
        )
    grouped = defaultdict(list)
    for row in per_query:
        grouped[(row["technology_area_id"], row["run_id"])].append(row)
    metric_names = (
        "candidate_recall_at_k",
        "hit_at_5",
        "precision_at_5",
        "recall_at_5",
        "mrr_at_5",
        "ndcg_at_5",
    )
    macro = []
    for (area, run_id), rows in sorted(grouped.items()):
        macro.append(
            {
                "technology_area_id": area,
                "run_id": run_id,
                "macro_query_count": sum(
                    not row["no_relevant_in_pool"] for row in rows
                ),
                "no_relevant_query_count": sum(
                    row["no_relevant_in_pool"] for row in rows
                ),
                **{
                    metric: (
                        sum(row[metric] for row in rows if row[metric] is not None)
                        / sum(row[metric] is not None for row in rows)
                        if any(row[metric] is not None for row in rows)
                        else None
                    )
                    for metric in metric_names
                },
            }
        )
    result = {
        "status": "scored" if complete else "awaiting_human_labels",
        "human_judged_candidate_count": judged_count,
        "pending_candidate_count": pending,
        "hold_candidate_count": hold,
        "invalid_label_count": invalid_count,
        "fully_judged_query_area_count": len(complete),
        "query_area_count": len(candidate_groups),
        "candidate_k_requested": TOP_K,
        "metric_k": METRIC_K,
        "per_query": per_query,
        "macro": macro,
        "metric_scope": "Candidate Recall@K uses relevant documents in the fully judged query-area pool, not the full patent corpus.",
        "no_relevant_policy": "Pools with no relevant candidate are counted separately and excluded from metric means.",
    }
    (output_dir / "metrics.json").write_text(
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
    run_parser = subparsers.add_parser(
        "run", help="로컬 검색 비교와 블라인드 라벨 후보 생성"
    )
    run_parser.add_argument("--out-dir", type=Path, default=OUTPUT_DIR)
    run_parser.add_argument("--candidate-k", type=int, default=TOP_K)
    run_parser.add_argument(
        "--with-cross-encoder",
        action="store_true",
        help="sentence-transformers의 BGE Cross-Encoder를 명시적으로 실행",
    )
    score_parser = subparsers.add_parser(
        "score", help="사람 라벨 완료 풀의 검색 지표 계산"
    )
    score_parser.add_argument("--out-dir", type=Path, default=OUTPUT_DIR)
    args = parser.parse_args()
    if args.command == "inventory":
        result = write_inventory(args.out_dir)
    elif args.command == "run":
        result = run_experiment(args.out_dir, args.candidate_k, args.with_cross_encoder)
    else:
        result = score_experiment(args.out_dir)
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
