"""Compare full dense search with a one-request on-demand candidate budget."""

import argparse
import csv
import hashlib
import json
import math
import time
from datetime import datetime, timezone
from pathlib import Path
import xml.etree.ElementTree as ET

import chromadb
import yaml
from chromadb.config import Settings

from evaluation.evaluate import (
    hit_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
)
from evaluation.patent_index_effect import cosine
from evaluation.patent_labeling import load_cases
from src.generation.patent_analysis import kipris_application_search_url
from src.ingestion.kipris_client import search_patents as kipris_search
from src.ingestion.patent_processor import to_patent_document
from src.retrieval.engine import bm25_scores
from src.retrieval.market_search import EMBED_BATCH_SIZE, embed_texts
from src.retrieval.patent_store import to_chroma_record
from src.retrieval.schemas import SearchDocument
from src.schemas import PatentChunk, PatentDocument

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = (
    ROOT_DIR
    / "data"
    / "patents"
    / "processed"
    / "domain_experiment"
    / "candidate_budget"
)
RAW_DIR = OUTPUT_DIR / "raw"
DOCS_PATH = OUTPUT_DIR / "patent_docs.jsonl"
CHROMA_DIR = OUTPUT_DIR / "chroma"
RESULTS_PATH = OUTPUT_DIR / "results.json"
CANDIDATES_PATH = OUTPUT_DIR / "candidates.csv"
METRICS_PATH = OUTPUT_DIR / "metrics.json"
COLLECTION_REPORT_PATH = OUTPUT_DIR / "collection.json"
INDEX_BUILD_PATH = OUTPUT_DIR / "index_build.json"
AREA_ID = "SF-05"
COLLECTION_NAME = "sf05_candidate_budget"
NO_INDEX_INPUT_CAP = EMBED_BATCH_SIZE
NO_INDEX_CANDIDATE_CAP = NO_INDEX_INPUT_CAP - 1
TOP_K = 5
POOL_K = 20
EMBEDDING_MODEL = "text-embedding-3-small"
CASE_PATH = ROOT_DIR / "evaluation" / "patent_cases.json"
CANDIDATE_FIELDS = [
    "case_id",
    "query",
    "technical_element",
    "source_id",
    "title",
    "summary",
    "url",
    "relevant",
    "note",
]


def sha256(path: Path) -> str:
    """Return a file fingerprint for experiment provenance."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_keywords() -> list[str]:
    """Load the configured SF-05 patent search terms."""
    config = yaml.safe_load(
        (ROOT_DIR / "configs" / "technology_areas.yaml").read_text(encoding="utf-8")
    )
    areas = {area["id"]: area for area in config.get("technology_areas", [])}
    return list(dict.fromkeys(areas[AREA_ID]["patent_keywords"]))


def load_existing_area_patents() -> list[PatentDocument]:
    """Read already processed SF-05 patents as a local supplement to fresh results."""
    source_path = ROOT_DIR / "data" / "patents" / "processed" / "patent_docs.jsonl"
    if not source_path.exists():
        return []
    patents = [
        PatentDocument.model_validate_json(line)
        for line in source_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return [patent for patent in patents if AREA_ID in patent.technology_area_ids]


def collect_corpus(limit: int) -> tuple[list[PatentDocument], dict]:
    """Collect configured KIPRIS results and keep the experiment corpus local."""
    if not 1 <= limit <= 500:
        raise ValueError("limit must be between 1 and 500")
    RAW_DIR.mkdir(parents=True, exist_ok=True)
    collected = {}
    per_keyword = {}
    for keyword in load_keywords():
        records = kipris_search(keyword, limit=limit, raw_dir=RAW_DIR)
        per_keyword[keyword] = len(records)
        for record in records:
            record["technology_area_ids"] = [AREA_ID]
            record["collected_at"] = datetime.now(timezone.utc).isoformat()
            document = to_patent_document(record)
            collected.setdefault(document.patent_id, document)

    for document in load_existing_area_patents():
        collected.setdefault(document.patent_id, document)

    patents = list(collected.values())
    abstract_patents = [patent for patent in patents if patent.abstract.strip()]
    DOCS_PATH.parent.mkdir(parents=True, exist_ok=True)
    DOCS_PATH.write_text(
        "".join(patent.model_dump_json() + "\n" for patent in patents),
        encoding="utf-8",
    )
    report = {
        "search_terms": load_keywords(),
        "limit_per_term": limit,
        "kipris_requests": len(per_keyword),
        "returned_per_term": per_keyword,
        "unique_patent_count": len(patents),
        "abstract_candidate_count": len(abstract_patents),
        "documents_sha256": sha256(DOCS_PATH),
    }
    COLLECTION_REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return abstract_patents, report


def load_experiment_corpus(limit: int) -> tuple[list[PatentDocument], dict]:
    """Load the corpus saved before an interrupted embedding or ranking run."""
    if not DOCS_PATH.exists():
        raise FileNotFoundError(f"no saved experiment corpus at {DOCS_PATH}")
    patents = [
        PatentDocument.model_validate_json(line)
        for line in DOCS_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    abstracts = [patent for patent in patents if patent.abstract.strip()]
    if COLLECTION_REPORT_PATH.exists():
        report = json.loads(COLLECTION_REPORT_PATH.read_text(encoding="utf-8"))
    else:
        returned_per_term = {}
        for metadata_path in RAW_DIR.glob("patent_search_*.json"):
            metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
            response_path = RAW_DIR / metadata["response_file"]
            root = ET.parse(response_path).getroot()
            returned_per_term[metadata["identifier"]] = sum(
                1
                for node in root.iter()
                if node.tag.rsplit("}", 1)[-1].lower() == "patentutilityinfo"
            )
        report = {
            "search_terms": load_keywords(),
            "limit_per_term": limit,
            "kipris_requests": len(returned_per_term),
            "returned_per_term": returned_per_term,
        }
    report.update(
        {
            "corpus_reused": True,
            "unique_patent_count": len(patents),
            "abstract_candidate_count": len(abstracts),
            "documents_sha256": sha256(DOCS_PATH),
        }
    )
    COLLECTION_REPORT_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return abstracts, report


def local_collection(rebuild: bool):
    """Open the dedicated experiment index without using shared Chroma settings."""
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False)
    )
    names = [collection.name for collection in client.list_collections()]
    if rebuild and COLLECTION_NAME in names:
        client.delete_collection(COLLECTION_NAME)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={"hnsw:space": "cosine", "technology_area_id": AREA_ID},
        embedding_function=None,
    )
    return collection


def index_matches_corpus(collection, patents: list[PatentDocument]) -> bool:
    """Check whether the experiment index already contains the exact abstract corpus."""
    expected = {
        f"{patent.patent_id}_abstract_0": patent.abstract.strip() for patent in patents
    }
    if collection.count() != len(expected):
        return False
    result = collection.get(include=["documents"])
    return dict(zip(result["ids"], result["documents"])) == expected


def build_cached_index(patents: list[PatentDocument], collection) -> dict:
    """Embed one abstract per patent once and persist it in the local collection."""
    chunks = [
        PatentChunk(
            chunk_id=f"{patent.patent_id}_abstract_0",
            patent_id=patent.patent_id,
            section="abstract",
            text=patent.abstract.strip(),
            chunk_index=0,
        )
        for patent in patents
    ]
    patent_by_id = {patent.patent_id: patent for patent in patents}
    records = [
        to_chroma_record(chunk, patent_by_id[chunk.patent_id]) for chunk in chunks
    ]
    started = time.perf_counter()
    vectors = embed_texts([record[1] for record in records])
    embedding_ms = (time.perf_counter() - started) * 1000
    write_started = time.perf_counter()
    for start in range(0, len(records), EMBED_BATCH_SIZE):
        batch = records[start : start + EMBED_BATCH_SIZE]
        collection.upsert(
            ids=[record[0] for record in batch],
            documents=[record[1] for record in batch],
            metadatas=[record[2] for record in batch],
            embeddings=vectors[start : start + len(batch)],
        )
    write_ms = (time.perf_counter() - write_started) * 1000
    return {
        "embedding_input_count": len(records),
        "embedding_api_requests": math.ceil(len(records) / EMBED_BATCH_SIZE),
        "embedding_ms": round(embedding_ms, 2),
        "local_write_ms": round(write_ms, 2),
        "total_ms": round(embedding_ms + write_ms, 2),
    }


def read_cache_rows(collection) -> list[dict]:
    """Read all persisted vectors for exact in-memory cosine ranking."""
    result = collection.get(include=["embeddings", "documents", "metadatas"])
    return [
        {"embedding": vector, "text": text, "metadata": metadata}
        for vector, text, metadata in zip(
            result["embeddings"], result["documents"], result["metadatas"]
        )
    ]


def rank_rows(query_vector: list[float], rows: list[dict], limit: int) -> list[dict]:
    """Rank patent rows by exact cosine similarity, keeping the best abstract per source."""
    best_by_source = {}
    for row in rows:
        metadata = row["metadata"]
        source_id = metadata["source_id"]
        score = cosine(query_vector, row["embedding"])
        current = best_by_source.get(source_id)
        if current is None or score > current["score"]:
            best_by_source[source_id] = {
                "source_id": source_id,
                "title": metadata["title"],
                "summary": row["text"][:800],
                "url": metadata.get("source_url") or "",
                "score": score,
            }
    return sorted(
        best_by_source.values(), key=lambda item: (-item["score"], item["source_id"])
    )[:limit]


def determine_label_source(candidates: list[dict]) -> str:
    """Identify AI-drafted labels from their explicit candidate notes."""
    ai_draft_count = sum(
        row.get("note", "").startswith("AI 초안") for row in candidates
    )
    if ai_draft_count == len(candidates) and candidates:
        return "assistant_title_abstract_prelabel"
    if ai_draft_count:
        return "mixed_or_partially_reviewed"
    return "human_or_unmarked"


def to_search_document(patent: PatentDocument) -> SearchDocument:
    """Convert a patent abstract into a lexical shortlist document."""
    return SearchDocument(
        chunk_id=f"{patent.patent_id}_abstract_0",
        source_id=patent.patent_id,
        source_type="patent",
        title=patent.title,
        content=patent.abstract.strip(),
        metadata={"source_url": patent.source_url},
    )


def run_experiment(limit: int = 150, resume: bool = False) -> dict:
    """Collect an expanded corpus and compare full cached search with a one-batch shortlist."""
    patents, collection_report = (
        load_experiment_corpus(limit) if resume else collect_corpus(limit)
    )
    if len(patents) <= NO_INDEX_CANDIDATE_CAP:
        raise RuntimeError(
            f"only {len(patents)} abstract patents; need more than {NO_INDEX_CANDIDATE_CAP}"
        )

    collection = local_collection(rebuild=not resume)
    if resume and index_matches_corpus(collection, patents):
        if INDEX_BUILD_PATH.exists():
            build_report = json.loads(INDEX_BUILD_PATH.read_text(encoding="utf-8"))
        else:
            build_report = {
                "embedding_input_count": len(patents),
                "embedding_api_requests": None,
                "embedding_ms": None,
                "local_write_ms": None,
                "total_ms": None,
            }
        build_report["reused_cached_index"] = True
    else:
        build_report = build_cached_index(patents, collection)
        INDEX_BUILD_PATH.write_text(
            json.dumps(build_report, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
    cases = [case for case in load_cases() if case.get("technology_area_id") == AREA_ID]
    if not cases:
        raise ValueError("no SF-05 cases found in evaluation/patent_cases.json")

    cache_load_started = time.perf_counter()
    cached_rows = read_cache_rows(collection)
    cache_load_ms = (time.perf_counter() - cache_load_started) * 1000
    search_documents = [to_search_document(patent) for patent in patents]
    result_rows = []
    candidate_map = {}

    for case in cases:
        query = case["query"]

        cached_started = time.perf_counter()
        cached_query_vector = embed_texts([query])[0]
        cached_embed_ms = (time.perf_counter() - cached_started) * 1000
        cached_rank_started = time.perf_counter()
        cached_rankings = rank_rows(cached_query_vector, cached_rows, POOL_K)
        cached_rank_ms = (time.perf_counter() - cached_rank_started) * 1000

        shortlist_started = time.perf_counter()
        bm25 = bm25_scores(query, search_documents)
        shortlist = [document for document, _ in bm25[:NO_INDEX_CANDIDATE_CAP]]
        shortlist_ms = (time.perf_counter() - shortlist_started) * 1000
        on_demand_texts = [query] + [document.content for document in shortlist]
        if len(on_demand_texts) > NO_INDEX_INPUT_CAP:
            raise AssertionError("on-demand embedding input cap exceeded")
        on_demand_started = time.perf_counter()
        vectors = embed_texts(on_demand_texts)
        on_demand_embed_ms = (time.perf_counter() - on_demand_started) * 1000
        on_demand_rows = [
            {
                "embedding": vector,
                "text": document.content,
                "metadata": {
                    "source_id": document.source_id,
                    "title": document.title,
                    **document.metadata,
                },
            }
            for document, vector in zip(shortlist, vectors[1:])
        ]
        on_demand_rank_started = time.perf_counter()
        on_demand_rankings = rank_rows(vectors[0], on_demand_rows, POOL_K)
        on_demand_rank_ms = (time.perf_counter() - on_demand_rank_started) * 1000
        on_demand_total_ms = shortlist_ms + on_demand_embed_ms + on_demand_rank_ms

        for result in cached_rankings:
            result_rows.append(
                {"case_id": case["case_id"], "method": "preindexed_full", **result}
            )
        for result in on_demand_rankings:
            result_rows.append(
                {"case_id": case["case_id"], "method": "on_demand_bm25_99", **result}
            )

        pool = {item["source_id"]: item for item in cached_rankings}
        pool.update({item["source_id"]: item for item in on_demand_rankings})
        for source_id, item in pool.items():
            url = item.get("url") or kipris_application_search_url(source_id) or ""
            candidate_map[(case["case_id"], source_id)] = {
                "case_id": case["case_id"],
                "query": query,
                "technical_element": case["technical_element"],
                "source_id": source_id,
                "title": item["title"],
                "summary": item.get("summary") or item.get("text", "")[:800],
                "url": url,
                "relevant": "",
                "note": "",
            }

        case["_measurements"] = {
            "preindexed": {
                "candidate_count": len(patents),
                "query_embedding_input_count": 1,
                "query_embedding_api_requests": 1,
                "query_ms": round(cached_embed_ms + cached_rank_ms, 2),
                "top20": cached_rankings,
            },
            "on_demand": {
                "candidate_count": len(shortlist),
                "embedding_input_count": len(on_demand_texts),
                "embedding_api_requests": math.ceil(
                    len(on_demand_texts) / EMBED_BATCH_SIZE
                ),
                "bm25_shortlist_ms": round(shortlist_ms, 2),
                "embedding_ms": round(on_demand_embed_ms, 2),
                "ranking_ms": round(on_demand_rank_ms, 2),
                "query_ms": round(on_demand_total_ms, 2),
                "top20": on_demand_rankings,
            },
            "top5_overlap_count": len(
                {item["source_id"] for item in cached_rankings[:TOP_K]}
                & {item["source_id"] for item in on_demand_rankings}
            ),
        }

    output_cases = [
        {key: value for key, value in case.items() if key != "_measurements"}
        | {"measurements": case["_measurements"]}
        for case in cases
    ]
    output_dir = OUTPUT_DIR
    output_dir.mkdir(parents=True, exist_ok=True)
    with CANDIDATES_PATH.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CANDIDATE_FIELDS)
        writer.writeheader()
        writer.writerows(candidate_map[key] for key in sorted(candidate_map))

    summary = {
        "status": "awaiting_human_labels",
        "area_id": AREA_ID,
        "embedding_model": EMBEDDING_MODEL,
        "fixed_query_batch_input_cap": NO_INDEX_INPUT_CAP,
        "on_demand_candidate_cap": NO_INDEX_CANDIDATE_CAP,
        "preindex_candidates_per_query": len(patents),
        "index_build": build_report,
        "cache_load_ms": round(cache_load_ms, 2),
        "collection": collection_report,
        "candidate_pool_count": len(candidate_map),
        "candidate_file": str(CANDIDATES_PATH.relative_to(ROOT_DIR)),
        "unlabeled_candidate_count": len(candidate_map),
        "case_file_sha256": sha256(CASE_PATH),
        "note": "Quality metrics await human labels. On-demand uses BM25 top-99 plus query in one embedding batch; pre-index searches all patents.",
        "queries": output_cases,
        "ranked_results": result_rows,
    }
    RESULTS_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def score_experiment() -> dict:
    """Calculate pooled-label metrics for full pre-index and constrained on-demand search."""
    results = json.loads(RESULTS_PATH.read_text(encoding="utf-8"))
    with CANDIDATES_PATH.open(encoding="utf-8-sig", newline="") as file:
        candidates = list(csv.DictReader(file))
    pending = [
        row for row in candidates if row.get("relevant", "").strip() not in {"0", "1"}
    ]
    if pending:
        raise ValueError(f"{len(pending)} candidate labels remain pending")
    label_source = determine_label_source(candidates)
    relevant_by_case = {}
    candidates_by_case = {}
    for row in candidates:
        candidates_by_case.setdefault(row["case_id"], set()).add(row["source_id"])
        if row["relevant"].strip() == "1":
            relevant_by_case.setdefault(row["case_id"], set()).add(row["source_id"])

    report = []
    for case in results["queries"]:
        relevant = relevant_by_case.get(case["case_id"], set())
        for method, config_key, ranking_key in (
            ("preindexed_full", "preindexed", "top20"),
            ("on_demand_bm25_99", "on_demand", "top20"),
        ):
            retrieved = [
                item["source_id"]
                for item in case["measurements"][config_key][ranking_key]
            ]
            report.append(
                {
                    "case_id": case["case_id"],
                    "method": method,
                    "label_source": label_source,
                    "judged_pool_count": len(
                        candidates_by_case.get(case["case_id"], set())
                    ),
                    "unjudged_corpus_count": max(
                        0,
                        results["collection"]["abstract_candidate_count"]
                        - len(candidates_by_case.get(case["case_id"], set())),
                    ),
                    "judged_pool_relevant_count": len(relevant),
                    "hit_at_5": hit_at_k(retrieved, relevant, TOP_K),
                    "recall_at_5": recall_at_k(retrieved, relevant, TOP_K),
                    "precision_at_5": precision_at_k(retrieved, relevant, TOP_K),
                    "mrr_at_5": reciprocal_rank(retrieved, relevant, TOP_K),
                    "ndcg_at_5": ndcg_at_k(retrieved, relevant, TOP_K),
                }
            )
    METRICS_PATH.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    results["status"] = "scored"
    results["label_source"] = label_source
    results["unlabeled_candidate_count"] = 0
    results["metrics_file"] = str(METRICS_PATH.relative_to(ROOT_DIR))
    RESULTS_PATH.write_text(
        json.dumps(results, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return {"status": "scored", "metrics": report, "path": str(METRICS_PATH)}


def main() -> None:
    parser = argparse.ArgumentParser(
        description="사전색인 전체 후보와 배치 제한 무색인 후보 비교"
    )
    subparsers = parser.add_subparsers(dest="command", required=True)
    run_parser = subparsers.add_parser(
        "run", help="KIPRIS에서 SF-05 자료를 수집해 비교"
    )
    run_parser.add_argument(
        "--limit", type=int, default=150, help="검색어당 KIPRIS 최대 결과"
    )
    run_parser.add_argument(
        "--resume",
        action="store_true",
        help="저장된 코퍼스와 일치하는 로컬 색인을 재사용해 비교를 재개",
    )
    subparsers.add_parser("score", help="후보의 사람 관련도 라벨로 품질 지표 계산")
    args = parser.parse_args()
    report = (
        run_experiment(args.limit, resume=args.resume)
        if args.command == "run"
        else score_experiment()
    )
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
