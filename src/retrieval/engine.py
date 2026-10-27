"""Dense, BM25, hybrid 및 rerank 결과를 공통 검색 스키마로 결합한다."""

import re
import time
import math
from collections import Counter
from dataclasses import dataclass
from typing import Callable, Iterable

from src.retrieval.schemas import RetrievalResult, SearchDocument


@dataclass(frozen=True)
class RetrievalConfig:
    candidate_k: int = 50
    top_k: int = 5
    rrf_k: int = 60
    deduplicate_by_source: bool = False
    source_type: str | None = None
    metadata_filters: dict | None = None

    def __post_init__(self):
        if min(self.candidate_k, self.top_k, self.rrf_k) < 1:
            raise ValueError("candidate_k, top_k, rrf_k must be positive")


@dataclass
class RetrievalResponse:
    results: list[RetrievalResult]
    search_ms: float
    rerank_ms: float = 0.0


def tokenize(text: str) -> list[str]:
    """한국어 공백 토큰과 문자 bigram을 함께 사용해 의존성 없는 토큰화를 제공한다."""
    words = re.findall(r"[\w]+", text.lower())
    tokens = list(words)
    for word in words:
        compact = re.sub(r"\s+", "", word)
        tokens.extend(compact[i : i + 2] for i in range(len(compact) - 1))
    return tokens


def bm25_scores(query: str, documents: list[SearchDocument], k1=1.5, b=0.75):
    """표준 BM25 점수를 계산해 (문서, 점수) 목록을 내림차순으로 반환한다."""
    query_terms = set(tokenize(query))
    if not documents or not query_terms:
        return []
    tokenized = [tokenize(d.title + " " + d.content) for d in documents]
    lengths = [len(tokens) for tokens in tokenized]
    average_length = sum(lengths) / len(lengths) or 1
    frequencies = [Counter(tokens) for tokens in tokenized]
    df = {term: sum(term in freq for freq in frequencies) for term in query_terms}
    scored = []
    for index, freq in enumerate(frequencies):
        score = 0.0
        for term in query_terms:
            tf = freq[term]
            if not tf:
                continue
            idf = math.log1p((len(documents) - df[term] + 0.5) / (df[term] + 0.5))
            norm = tf + k1 * (1 - b + b * lengths[index] / average_length)
            score += idf * tf * (k1 + 1) / norm
        scored.append((documents[index], score))
    return sorted(scored, key=lambda item: item[1], reverse=True)


def _matches(document: SearchDocument, config: RetrievalConfig) -> bool:
    if config.source_type and document.source_type != config.source_type:
        return False
    return all(
        document.metadata.get(key) == value
        for key, value in (config.metadata_filters or {}).items()
    )


def _deduplicate(results: list[RetrievalResult], by_source: bool):
    seen = set()
    unique = []
    for result in results:
        key = result.document.source_id if by_source else result.document.chunk_id
        if key not in seen:
            seen.add(key)
            unique.append(result)
    return unique


def retrieve(
    query: str,
    documents: Iterable[SearchDocument],
    dense_results: list[RetrievalResult] | None = None,
    *,
    mode: str = "hybrid",
    config: RetrievalConfig | None = None,
    reranker: Callable[[str, list[SearchDocument]], list[float]] | None = None,
) -> RetrievalResponse:
    """문서 후보에 BM25·dense·RRF를 적용하고 선택적으로 cross-encoder로 재정렬한다.

    dense_results는 기존 벡터 백엔드가 반환한 결과이며 해당 검색 순위·점수를 보존한다.
    reranker는 (query, documents) -> score 목록 인터페이스를 받는다.
    """
    if mode not in {"dense", "bm25", "hybrid"}:
        raise ValueError("mode must be dense, bm25, or hybrid")
    config = config or RetrievalConfig()
    started = time.perf_counter()
    candidates = [doc for doc in documents if _matches(doc, config)]
    dense = [r for r in (dense_results or []) if _matches(r.document, config)]
    if mode == "dense" and not dense:
        raise ValueError("dense mode requires results from the existing vector backend")
    bm25 = bm25_scores(query, candidates)
    bm25_rank = {doc.chunk_id: rank for rank, (doc, _) in enumerate(bm25, 1)}
    bm25_score = {doc.chunk_id: score for doc, score in bm25}
    dense_rank = {r.document.chunk_id: rank for rank, r in enumerate(dense, 1)}
    dense_by_id = {r.document.chunk_id: r for r in dense}
    candidate_by_id = {document.chunk_id: document for document in candidates}
    ids = list(candidate_by_id)
    ids.extend(chunk_id for chunk_id in dense_by_id if chunk_id not in candidate_by_id)
    output = []
    for chunk_id in ids:
        base = dense_by_id.get(chunk_id)
        document = base.document if base else candidate_by_id[chunk_id]
        dr, br = dense_rank.get(chunk_id), bm25_rank.get(chunk_id)
        if mode == "dense" and dr is None:
            continue
        if mode == "bm25" and br is None:
            continue
        rrf = (1 / (config.rrf_k + dr) if dr else 0) + (
            1 / (config.rrf_k + br) if br else 0
        )
        output.append(
            RetrievalResult(
                document=document,
                dense_score=base.dense_score if base else None,
                bm25_score=bm25_score.get(chunk_id),
                rrf_score=rrf if mode == "hybrid" else None,
                dense_rank=dr,
                bm25_rank=br,
            )
        )
    if mode == "dense":
        output.sort(key=lambda r: r.dense_rank or 10**9)
    elif mode == "bm25":
        output.sort(key=lambda r: r.bm25_rank or 10**9)
    else:
        output.sort(
            key=lambda r: (r.rrf_score or 0, r.dense_score or 0, r.bm25_score or 0),
            reverse=True,
        )
    output = _deduplicate(output, config.deduplicate_by_source)[: config.candidate_k]
    search_ms = (time.perf_counter() - started) * 1000
    rerank_ms = 0.0
    if reranker and output:
        rerank_started = time.perf_counter()
        scores = reranker(query, [result.document for result in output])
        if len(scores) != len(output):
            raise ValueError("reranker must return one score per document")
        output = [
            result.model_copy(update={"rerank_score": float(score)})
            for result, score in zip(output, scores)
        ]
        output.sort(key=lambda result: result.rerank_score or 0, reverse=True)
        rerank_ms = (time.perf_counter() - rerank_started) * 1000
    output = [
        result.model_copy(update={"final_rank": i})
        for i, result in enumerate(output[: config.top_k], 1)
    ]
    return RetrievalResponse(output, search_ms, rerank_ms)


def bge_reranker(
    model_name: str = "BAAI/bge-reranker-v2-m3", device: str | None = None
):
    """선택 설치된 sentence-transformers CrossEncoder를 lazy-load한다.

    반환된 함수는 모델을 첫 호출 때 로드하므로 BM25·dense 검색에는 해당 패키지가 필요 없다.
    """

    def score(query: str, documents: list[SearchDocument]) -> list[float]:
        try:
            from sentence_transformers import CrossEncoder
        except ImportError as exc:
            raise RuntimeError(
                "Cross-Encoder 사용에는 sentence-transformers 설치가 필요합니다."
            ) from exc
        if not hasattr(score, "model"):
            score.model = CrossEncoder(model_name, device=device)
        pairs = [
            (query, f"{document.title}\n{document.content}") for document in documents
        ]
        return [float(value) for value in score.model.predict(pairs)]

    return score
