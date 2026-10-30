"""Measure patent search latency with pre-indexed and on-demand embeddings."""

import argparse
import hashlib
import json
import math
import time
from pathlib import Path

import chromadb
from chromadb.config import Settings

from evaluation.patent_labeling import load_cases
from src.ingestion.patent_processor import OUTPUT_PATH, build_chunks
from src.retrieval.market_search import EMBED_BATCH_SIZE, embed_texts
from src.retrieval.patent_store import to_chroma_record
from src.schemas import PatentDocument

ROOT_DIR = Path(__file__).resolve().parents[1]
OUTPUT_DIR = ROOT_DIR / "data" / "patents" / "processed" / "domain_experiment"
CHROMA_DIR = OUTPUT_DIR / "index_effect_chroma"
RESULT_PATH = OUTPUT_DIR / "index_effect.json"
AREA_ID = "SF-05"
COLLECTION_NAME = "sf05_index_effect"
TOP_K = 5
EMBEDDING_MODEL = "text-embedding-3-small"


def sha256(path: Path) -> str:
    """Return a file fingerprint for experiment provenance."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def load_area_chunks() -> tuple[list[PatentDocument], list]:
    """Load SF-05 documents and create the same abstract/claim chunks used by indexing."""
    patents = [
        PatentDocument.model_validate_json(line)
        for line in OUTPUT_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    patents = [patent for patent in patents if AREA_ID in patent.technology_area_ids]
    return patents, build_chunks(patents)


def local_collection(rebuild: bool):
    """Open or rebuild the isolated experiment cache without remote Chroma settings."""
    CHROMA_DIR.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(
        path=str(CHROMA_DIR), settings=Settings(anonymized_telemetry=False)
    )
    patents, chunks = load_area_chunks()
    source_hash = sha256(OUTPUT_PATH)
    if rebuild and COLLECTION_NAME in [item.name for item in client.list_collections()]:
        client.delete_collection(COLLECTION_NAME)
    collection = client.get_or_create_collection(
        name=COLLECTION_NAME,
        metadata={
            "hnsw:space": "cosine",
            "technology_area_id": AREA_ID,
            "source_sha256": source_hash,
            "embedding_model": EMBEDDING_MODEL,
        },
        embedding_function=None,
    )
    metadata = collection.metadata or {}
    if collection.count() and metadata.get("source_sha256") != source_hash:
        raise RuntimeError("cached source data changed; rerun with --rebuild-cache")
    return collection, patents, chunks, source_hash


def build_cache(collection, patents: list[PatentDocument], chunks: list) -> dict:
    """Embed SF-05 chunks once and persist their vectors in the local experiment cache."""
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


def cosine(left: list[float], right: list[float]) -> float:
    """Calculate cosine similarity for two embedding vectors."""
    left_norm = math.sqrt(sum(float(value) ** 2 for value in left))
    right_norm = math.sqrt(sum(float(value) ** 2 for value in right))
    if not left_norm or not right_norm:
        return 0.0
    return sum(float(a) * float(b) for a, b in zip(left, right)) / (
        left_norm * right_norm
    )


def rank_patents(query_vector: list[float], rows: list[dict]) -> list[dict]:
    """Score all chunks and keep each patent's highest-scoring chunk."""
    best_by_patent = {}
    for row in rows:
        metadata = row["metadata"]
        score = cosine(query_vector, row["embedding"])
        source_id = metadata["source_id"]
        current = best_by_patent.get(source_id)
        if current is None or score > current["score"]:
            best_by_patent[source_id] = {
                "source_id": source_id,
                "title": metadata["title"],
                "summary": row["text"][:500],
                "score": score,
            }
    return sorted(
        best_by_patent.values(), key=lambda item: (-item["score"], item["source_id"])
    )[:TOP_K]


def read_cached_rows(collection) -> list[dict]:
    """Read all cached chunk vectors and texts for exact cosine ranking."""
    data = collection.get(include=["embeddings", "documents", "metadatas"])
    return [
        {"embedding": embedding, "text": text, "metadata": metadata}
        for embedding, text, metadata in zip(
            data["embeddings"], data["documents"], data["metadatas"]
        )
    ]


def run_experiment(rebuild_cache: bool = False) -> dict:
    """Compare cached document vectors with embedding every document per query."""
    collection, patents, chunks, source_hash = local_collection(rebuild_cache)
    if collection.count() == 0:
        build = build_cache(collection, patents, chunks)
    else:
        build = {
            "embedding_input_count": 0,
            "embedding_api_requests": 0,
            "embedding_ms": None,
            "local_write_ms": None,
            "total_ms": None,
            "note": "reused existing experiment cache; use --rebuild-cache to time a fresh build",
        }

    cases = [case for case in load_cases() if case.get("technology_area_id") == AREA_ID]
    if not cases:
        raise ValueError("no SF-05 queries found in evaluation/patent_cases.json")
    cache_load_started = time.perf_counter()
    cached_rows = read_cached_rows(collection)
    cache_load_ms = (time.perf_counter() - cache_load_started) * 1000
    preindex_setup_ms = (build.get("total_ms") or 0) + cache_load_ms
    results = []
    title_by_id = {patent.patent_id: patent.title for patent in patents}
    for case in cases:
        query = case["query"]

        started = time.perf_counter()
        cached_query_vector = embed_texts([query])[0]
        cached_embed_ms = (time.perf_counter() - started) * 1000
        rank_started = time.perf_counter()
        cached_rankings = rank_patents(cached_query_vector, cached_rows)
        cached_rank_ms = (time.perf_counter() - rank_started) * 1000

        on_demand_texts = [query] + [chunk.text for chunk in chunks]
        started = time.perf_counter()
        on_demand_vectors = embed_texts(on_demand_texts)
        on_demand_embed_ms = (time.perf_counter() - started) * 1000
        on_demand_rows = [
            {
                "embedding": vector,
                "text": chunk.text,
                "metadata": {
                    "source_id": chunk.patent_id,
                    "title": title_by_id[chunk.patent_id],
                },
            }
            for chunk, vector in zip(chunks, on_demand_vectors[1:])
        ]
        rank_started = time.perf_counter()
        on_demand_rankings = rank_patents(on_demand_vectors[0], on_demand_rows)
        on_demand_rank_ms = (time.perf_counter() - rank_started) * 1000

        cached_ids = [item["source_id"] for item in cached_rankings]
        on_demand_ids = [item["source_id"] for item in on_demand_rankings]
        results.append(
            {
                "case_id": case["case_id"],
                "query": query,
                "cache": {
                    "query_embedding_ms": round(cached_embed_ms, 2),
                    "ranking_ms": round(cached_rank_ms, 2),
                    "total_query_ms": round(cached_embed_ms + cached_rank_ms, 2),
                    "embedding_input_count": 1,
                    "embedding_api_requests": 1,
                    "top5": cached_rankings,
                },
                "on_demand": {
                    "query_and_document_embedding_ms": round(on_demand_embed_ms, 2),
                    "ranking_ms": round(on_demand_rank_ms, 2),
                    "total_query_ms": round(on_demand_embed_ms + on_demand_rank_ms, 2),
                    "embedding_input_count": len(on_demand_texts),
                    "embedding_api_requests": math.ceil(
                        len(on_demand_texts) / EMBED_BATCH_SIZE
                    ),
                    "top5": on_demand_rankings,
                },
                "top5_overlap_count": len(
                    set(cached_ids[:TOP_K]) & set(on_demand_ids[:TOP_K])
                ),
                "same_top5_order": cached_ids[:TOP_K] == on_demand_ids[:TOP_K],
            }
        )

    cache_query_ms = sum(item["cache"]["total_query_ms"] for item in results) / len(
        results
    )
    on_demand_query_ms = sum(
        item["on_demand"]["total_query_ms"] for item in results
    ) / len(results)
    savings_ms = on_demand_query_ms - cache_query_ms
    summary = {
        "status": "completed_unlabeled_retrieval_comparison",
        "area_id": AREA_ID,
        "embedding_model": EMBEDDING_MODEL,
        "top_k": TOP_K,
        "patent_count": len(patents),
        "chunk_count": len(chunks),
        "preindex_build": build,
        "cache_load_ms": round(cache_load_ms, 2),
        "preindex_setup_total_ms": round(preindex_setup_ms, 2),
        "cache_query_ms_avg": round(cache_query_ms, 2),
        "on_demand_query_ms_avg": round(on_demand_query_ms, 2),
        "query_latency_saving_ms_avg": round(savings_ms, 2),
        "break_even_queries_estimate": (
            math.ceil(preindex_setup_ms / savings_ms)
            if build.get("total_ms") is not None and savings_ms > 0
            else None
        ),
        "input_data_sha256": source_hash,
        "case_file_sha256": sha256(ROOT_DIR / "evaluation" / "patent_cases.json"),
        "note": "Single-run wall-clock sample; ranking metrics need human relevance labels. API time and network variation affect latency.",
        "queries": results,
    }
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    RESULT_PATH.write_text(
        json.dumps(summary, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return summary


def main() -> None:
    parser = argparse.ArgumentParser(description="SF-05 사전색인 효과 비교")
    parser.add_argument(
        "--rebuild-cache",
        action="store_true",
        help="실험용 로컬 캐시를 새로 만들고 색인 시간을 측정",
    )
    args = parser.parse_args()
    print(json.dumps(run_experiment(args.rebuild_cache), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
