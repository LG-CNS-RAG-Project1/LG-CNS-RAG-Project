from evaluation.patent_candidate_budget import rank_rows
from evaluation.patent_index_effect import cosine, rank_patents


def test_cosine_similarity_handles_identical_and_orthogonal_vectors():
    assert cosine([1.0, 0.0], [1.0, 0.0]) == 1.0
    assert cosine([1.0, 0.0], [0.0, 1.0]) == 0.0
    assert cosine([0.0, 0.0], [1.0, 0.0]) == 0.0


def test_rank_patents_uses_best_chunk_and_stable_tie_order():
    rows = [
        {
            "embedding": [0.8, 0.6],
            "text": "A lower scoring claim",
            "metadata": {"source_id": "A", "title": "Patent A"},
        },
        {
            "embedding": [1.0, 0.0],
            "text": "A stronger claim",
            "metadata": {"source_id": "A", "title": "Patent A"},
        },
        {
            "embedding": [1.0, 0.0],
            "text": "Patent B abstract",
            "metadata": {"source_id": "B", "title": "Patent B"},
        },
    ]

    ranked = rank_patents([1.0, 0.0], rows)

    assert [item["source_id"] for item in ranked] == ["A", "B"]
    assert ranked[0]["score"] == 1.0
    assert ranked[0]["summary"] == "A stronger claim"


def test_rank_rows_keeps_the_best_candidate_abstract_per_patent():
    rows = [
        {
            "embedding": [0.8, 0.6],
            "text": "Lower scoring abstract",
            "metadata": {"source_id": "A", "title": "Patent A"},
        },
        {
            "embedding": [1.0, 0.0],
            "text": "Best abstract",
            "metadata": {"source_id": "A", "title": "Patent A"},
        },
        {
            "embedding": [0.0, 1.0],
            "text": "Other abstract",
            "metadata": {"source_id": "B", "title": "Patent B"},
        },
    ]

    ranked = rank_rows([1.0, 0.0], rows, limit=2)

    assert [item["source_id"] for item in ranked] == ["A", "B"]
    assert ranked[0]["summary"] == "Best abstract"
