import pytest

from src.retrieval.engine import RetrievalConfig, bm25_scores, retrieve
from src.retrieval.schemas import RetrievalResult, SearchDocument


def doc(chunk, source, content, **metadata):
    return SearchDocument(
        chunk_id=chunk,
        source_id=source,
        source_type="market",
        title=content,
        content=content,
        metadata=metadata,
    )


def test_bm25_ranks_matching_korean_document_first():
    docs = [doc("a#0", "a", "협동로봇 비전 검사"), doc("b#0", "b", "사과 가격")]

    assert bm25_scores("협동로봇 검사", docs)[0][0].source_id == "a"


def test_hybrid_fuses_rankings_and_preserves_scores():
    first, second = doc("a#0", "a", "협동로봇 비전 검사"), doc(
        "b#0", "b", "협동로봇 도입"
    )
    dense = [
        RetrievalResult(document=second, dense_score=0.9, dense_rank=1),
        RetrievalResult(document=first, dense_score=0.8, dense_rank=2),
    ]

    response = retrieve("협동로봇 비전 검사", [first, second], dense, mode="hybrid")

    by_id = {item.document.source_id: item for item in response.results}
    assert by_id["a"].dense_score == 0.8
    assert by_id["a"].bm25_rank == 1
    assert all(item.rrf_score is not None for item in response.results)
    assert response.search_ms >= 0


def test_filters_and_document_level_deduplication():
    docs = [
        doc("a#0", "a", "협동로봇 도입", year=2025),
        doc("a#1", "a", "협동로봇 검사", year=2025),
        doc("b#0", "b", "협동로봇 도입", year=2020),
    ]

    response = retrieve(
        "협동로봇",
        docs,
        mode="bm25",
        config=RetrievalConfig(
            metadata_filters={"year": 2025}, deduplicate_by_source=True
        ),
    )

    assert [item.document.source_id for item in response.results] == ["a"]


def test_reranker_reorders_and_checks_scores():
    docs = [doc("a#0", "a", "협동로봇 도입"), doc("b#0", "b", "비전 검사")]
    response = retrieve(
        "비전 검사",
        docs,
        mode="bm25",
        reranker=lambda query, items: [
            0.9 if item.source_id == "b" else 0.1 for item in items
        ],
    )
    assert response.results[0].document.source_id == "b"
    assert response.results[0].rerank_score == 0.9

    with pytest.raises(ValueError, match="one score per document"):
        retrieve("q", docs, mode="bm25", reranker=lambda query, items: [])


def test_dense_mode_requires_existing_vector_results():
    with pytest.raises(ValueError, match="dense mode requires"):
        retrieve("q", [doc("a#0", "a", "test")], mode="dense")
