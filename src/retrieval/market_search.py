"""시장 근거 문서를 Chroma에 색인하고, 에이전트가 호출할 시장 근거 검색 툴을 제공한다.

- 입력: data/market/processed/market_docs.jsonl (market_processor 결과)
- 저장소: data/market/chroma/ 의 "news" 컬렉션 (cosine 거리)
- 임베딩: OpenAI text-embedding-3-small. 뉴스는 1기사 = 1청크(`{source_id}#0`)로 색인한다.
- 아이디어 필터를 위해 idea_ids를 `idea_<ID>: True` 메타데이터로도 저장한다.

사용 예:
    python -m src.retrieval.market_search build
    python -m src.retrieval.market_search search "협동로봇 도입 확대" --idea-id SF-01
"""

import argparse
import json
import os
import time
from dataclasses import replace
from pathlib import Path
from typing import Callable

from chromadb.api import ClientAPI
from src.retrieval.chroma_client import connect_chroma
from dotenv import load_dotenv

from src.schemas import (
    ALL_DIMENSIONS,
    IDEA_FIELDS,
    MarketDocument,
    MarketSearchRequest,
)
from src.retrieval.engine import RetrievalConfig, retrieve
from src.retrieval.schemas import RetrievalResult, SearchDocument

ROOT_DIR = Path(__file__).resolve().parents[2]
DOCS_PATH = ROOT_DIR / "data" / "market" / "processed" / "market_docs.jsonl"
CHROMA_DIR = ROOT_DIR / "data" / "market" / "chroma"
COLLECTION_NAME = "news"
EMBEDDING_MODEL = "text-embedding-3-small"
EMBED_BATCH_SIZE = 100
CANDIDATE_MULTIPLIER = 4

# 차원별 검색 질의 템플릿. {필드}는 StructuredIdea의 5개 항목 값으로 채우며, 빈 항목은 빠진다.
DIMENSION_QUERIES = {
    "demand": "{customers} {problem} {technology} 도입 확대 수요",
    "competition": "{difference} {technology} 경쟁 업체",
    "price": "{customers} {technology} 도입 가격 비용 {revenue}",
    "buyer": "{customers} {technology} 도입 사례",
    "adoption_barrier": "{customers} {technology} 도입 어려움 비용 부담 인력 부족",
}

EmbedFn = Callable[[list[str]], list[list[float]]]


def embed_texts(texts: list[str]) -> list[list[float]]:
    """OpenAI 임베딩 API로 텍스트 목록을 배치 단위로 임베딩한다.

    .env의 OPENAI_API_KEY가 필요하며, 없으면 RuntimeError를 발생시킨다.
    """
    from openai import OpenAI

    load_dotenv(ROOT_DIR / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set in .env")
    client = OpenAI()
    vectors = []
    for start in range(0, len(texts), EMBED_BATCH_SIZE):
        batch = texts[start : start + EMBED_BATCH_SIZE]
        response = client.embeddings.create(model=EMBEDDING_MODEL, input=batch)
        vectors.extend(item.embedding for item in response.data)
    return vectors


def get_collection(
    chroma_dir: Path = CHROMA_DIR,
    name: str = COLLECTION_NAME,
    client: ClientAPI | None = None,
):
    """cosine 거리를 쓰는 시장 근거 컬렉션을 열거나 생성한다. 임베딩은 항상 직접 전달한다."""
    if client is None:
        client = connect_chroma(chroma_dir)

    return client.get_or_create_collection(
        name, metadata={"hnsw:space": "cosine"}, embedding_function=None
    )


def load_documents(path: Path = DOCS_PATH) -> list[MarketDocument]:
    """정제된 시장 문서 JSONL을 읽어 MarketDocument 목록으로 반환한다."""
    with open(path, encoding="utf-8") as f:
        return [MarketDocument.model_validate_json(line) for line in f if line.strip()]


def to_chroma_record(document: MarketDocument) -> tuple[str, str, dict]:
    """문서 1건을 Chroma 레코드(id, 텍스트, 메타데이터)로 변환한다."""
    metadata = document.to_chroma_metadata()
    metadata["chunk_index"] = 0
    metadata.update({f"idea_{idea_id}": True for idea_id in document.idea_ids})
    return f"{document.source_id}#0", document.text, metadata


def build_index(
    documents: list[MarketDocument],
    collection,
    embed_fn: EmbedFn = embed_texts,
    rebuild: bool = False,
) -> int:
    """문서를 컬렉션에 upsert하고 새로 임베딩한 건수를 반환한다.

    rebuild=False이면 이미 색인된 ID는 임베딩하지 않는다.
    """
    records = [to_chroma_record(d) for d in documents]
    if not rebuild and records:
        existing = set(collection.get(ids=[r[0] for r in records], include=[])["ids"])
        records = [r for r in records if r[0] not in existing]

    for start in range(0, len(records), EMBED_BATCH_SIZE):
        batch = records[start : start + EMBED_BATCH_SIZE]
        collection.upsert(
            ids=[r[0] for r in batch],
            documents=[r[1] for r in batch],
            metadatas=[r[2] for r in batch],
            embeddings=embed_fn([r[1] for r in batch]),
        )
    return len(records)


def build_where(
    idea_id: str | None = None,
    source_types: list[str] | None = None,
    date_from: int | None = None,
) -> dict | None:
    """아이디어·출처 유형·발행일 조건을 Chroma where 필터로 만든다. 조건이 없으면 None."""
    conditions = []
    if idea_id:
        conditions.append({f"idea_{idea_id}": True})
    if source_types:
        conditions.append({"source_type": {"$in": list(source_types)}})
    if date_from:
        conditions.append({"published_at": {"$gte": date_from}})
    if not conditions:
        return None
    return conditions[0] if len(conditions) == 1 else {"$and": conditions}


def search_market(
    query: str,
    collection=None,
    embed_fn: EmbedFn = embed_texts,
    top_k: int = 5,
    idea_id: str | None = None,
    source_types: list[str] | None = None,
    date_from: int | None = None,
    retrieval_mode: str = "dense",
    reranker=None,
    retrieval_config: RetrievalConfig | None = None,
) -> list[dict]:
    """질의와 가까운 시장 근거를 거리 오름차순으로 최대 top_k건 반환한다.

    같은 dup_group의 결과는 가장 가까운 1건만 남긴다.
    반환 항목: source_id, text, source_type, publisher, title, url, published_at,
    period, section, reliability, evidence_nature, distance(cosine, 0에 가까울수록 유사)
    """
    search_started = time.perf_counter()
    collection = collection or get_collection()
    count = collection.count()
    if count == 0:
        return []

    if retrieval_mode not in {"dense", "bm25", "hybrid"}:
        raise ValueError("retrieval_mode must be dense, bm25, or hybrid")
    config = retrieval_config or RetrievalConfig(
        candidate_k=max(top_k * CANDIDATE_MULTIPLIER, top_k),
        top_k=top_k,
    )
    config = replace(config, top_k=config.candidate_k)
    where = build_where(idea_id, source_types, date_from)
    records = collection.get(where=where, include=["documents", "metadatas"])
    if not records["ids"]:
        return []
    documents = [
        SearchDocument(
            chunk_id=chunk_id,
            source_id=meta["source_id"],
            source_type="market",
            title=meta["title"],
            content=text,
            metadata=dict(meta),
        )
        for chunk_id, text, meta in zip(
            records["ids"], records["documents"], records["metadatas"]
        )
    ]
    dense_results = []
    if retrieval_mode in {"dense", "hybrid"}:
        result = collection.query(
            query_embeddings=embed_fn([query]),
            n_results=min(config.candidate_k, count),
            where=where,
            include=["documents", "metadatas", "distances"],
        )
        by_id = {document.chunk_id: document for document in documents}
        dense_results = [
            RetrievalResult(
                document=by_id[chunk_id],
                dense_score=1.0 - distance,
                dense_rank=rank,
            )
            for rank, (chunk_id, distance) in enumerate(
                zip(result["ids"][0], result["distances"][0]), 1
            )
            if chunk_id in by_id
        ]
    response = retrieve(
        query,
        documents,
        dense_results,
        mode=retrieval_mode,
        config=config,
        reranker=reranker,
    )
    hits, seen_groups = [], set()
    total_search_ms = (time.perf_counter() - search_started) * 1000
    by_chunk = {document.chunk_id: document for document in documents}
    for result_item in response.results:
        document = result_item.document
        meta = by_chunk[document.chunk_id].metadata
        group = meta.get("dup_group") or document.source_id
        if group in seen_groups:
            continue
        seen_groups.add(group)
        hits.append(
            {
                "source_id": document.source_id,
                "text": document.content,
                "source_type": meta["source_type"],
                "publisher": meta["publisher"],
                "title": document.title,
                "url": meta.get("url"),
                "published_at": meta["published_at"],
                "period": meta.get("period"),
                "section": meta.get("section"),
                "reliability": meta["reliability"],
                "evidence_nature": meta["evidence_nature"],
                "distance": (
                    round(1.0 - result_item.dense_score, 4)
                    if result_item.dense_score is not None
                    else None
                ),
                "bm25_score": result_item.bm25_score,
                "rrf_score": result_item.rrf_score,
                "rerank_score": result_item.rerank_score,
                "search_ms": round(total_search_ms, 3),
                "rerank_ms": round(response.rerank_ms, 3),
            }
        )
    return hits[:top_k]


def build_dimension_queries(request: MarketSearchRequest) -> dict[str, str]:
    """요청 아이디어의 5개 항목으로 차원별 검색 질의를 만든다."""
    values = request.idea.model_dump(include=set(IDEA_FIELDS))
    return {
        dimension: " ".join(DIMENSION_QUERIES[dimension].format(**values).split())
        for dimension in request.dimensions
    }


def search_by_dimensions(
    request: MarketSearchRequest,
    idea_id: str | None = None,
    collection=None,
    embed_fn: EmbedFn = embed_texts,
) -> dict[str, list[dict]]:
    """차원별 질의로 시장 근거를 검색해 {차원: 결과 목록}으로 반환한다.

    idea_id를 주면 해당 아이디어 키워드로 수집된 문서로 범위를 좁힌다.
    """
    collection = collection or get_collection()
    return {
        dimension: search_market(
            query,
            collection=collection,
            embed_fn=embed_fn,
            top_k=request.top_k,
            idea_id=idea_id,
            source_types=request.source_types,
            date_from=request.date_from,
        )
        for dimension, query in build_dimension_queries(request).items()
    }


def main() -> None:
    """build: 정제 문서를 색인한다. search: 질의 1건을 검색해 결과를 출력한다."""
    parser = argparse.ArgumentParser(description="시장 근거 색인·검색")
    sub = parser.add_subparsers(dest="command", required=True)
    build = sub.add_parser("build", help="market_docs.jsonl 색인")
    build.add_argument("--rebuild", action="store_true", help="기존 ID도 다시 임베딩")
    search = sub.add_parser("search", help="질의 검색")
    search.add_argument("query")
    search.add_argument("--idea-id")
    search.add_argument("--top-k", type=int, default=5)
    args = parser.parse_args()

    collection = get_collection()
    if args.command == "build":
        added = build_index(load_documents(), collection, rebuild=args.rebuild)
        print(f"embedded {added} documents -> collection size {collection.count()}")
    else:
        hits = search_market(
            args.query, collection=collection, top_k=args.top_k, idea_id=args.idea_id
        )
        print(json.dumps(hits, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
