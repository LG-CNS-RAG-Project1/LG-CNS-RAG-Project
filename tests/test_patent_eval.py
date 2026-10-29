import csv

import pytest

from evaluation.evaluate import attach_patent_run_metadata, evaluate_patents, summarize
from evaluation.patent_labeling import (
    CSV_FIELDS,
    export_candidates,
    import_labels,
)
from src.retrieval.schemas import RetrievalResult, SearchDocument

CASES = [
    {
        "case_id": "SF-01-cobot",
        "idea_id": "SF-01",
        "technical_element": "협동로봇 안전 제어",
        "query": "협동로봇 안전 제어",
        "relevant_source_ids": [],
        "judged_source_ids": [],
        "labeled": False,
    }
]


def result(source_id, title=None, content=None, claim_number=None):
    return RetrievalResult(
        document=SearchDocument(
            chunk_id=f"{source_id}_claim_{claim_number or 1}",
            source_id=source_id,
            source_type="patent",
            title=title or source_id,
            content=content or f"{source_id} claim text",
            metadata={"claim_number": claim_number, "version_id": "KR123A"},
        )
    )


def test_evaluate_patents_calculates_document_level_metrics():
    cases = [
        {
            **CASES[0],
            "labeled": True,
            "relevant_source_ids": ["patent-b"],
            "judged_source_ids": ["patent-a", "patent-b"],
        }
    ]
    rows = evaluate_patents(
        cases,
        lambda query, top_k: [
            {"source_id": "patent-a", "rerank_ms": 2.0},
            {"source_id": "patent-b", "rerank_ms": 2.0},
            {"source_id": "unjudged", "rerank_ms": 2.0},
        ],
    )

    summary = summarize(rows)["all"]
    assert rows[0]["rr"] == 0.5
    assert rows[0]["unjudged"] == 1
    assert rows[0]["rerank_ms"] == 2.0
    assert summary["mrr"] == 0.5


def test_evaluate_patents_skips_unlabeled_cases():
    assert evaluate_patents(CASES, lambda query, top_k: []) == []


def test_patent_run_metadata_records_selected_reranker():
    rows = attach_patent_run_metadata(
        [{"case_id": "case-1"}],
        "hybrid",
        True,
        reranker_model="text-embedding-3-small (bi-encoder)",
    )

    assert rows[0]["reranker_model"] == "text-embedding-3-small (bi-encoder)"
    assert rows[0]["model"] == "text-embedding-3-small (bi-encoder)"
    assert rows[0]["mode"] == "hybrid+rerank"


def test_default_patent_search_fn_passes_candidate_count_to_retriever(monkeypatch):
    from evaluation import evaluate as module

    class Collection:
        def count(self):
            return 100

    captured = {}
    monkeypatch.setattr(module, "get_patent_collection", lambda: Collection())

    def search(*args, **kwargs):
        captured.update(kwargs)
        return []

    monkeypatch.setattr(module, "search_patent_documents", search)
    search_fn = module.default_patent_search_fn("hybrid", candidate_k=40)
    search_fn("query", 5)

    assert captured["retrieval_config"].candidate_k == 40
    assert captured["retrieval_config"].top_k == 5


def test_export_candidates_unions_modes_by_patent_source(tmp_path):
    modes = {
        "dense": lambda query: [result("p1", "Patent one", claim_number=2)],
        "bm25": lambda query: [
            result("p1", "Patent one", claim_number=1),
            result("p2", "Patent two"),
        ],
        "hybrid": lambda query: [result("p2", "Patent two")],
    }
    path = tmp_path / "patent_candidates.csv"

    count = export_candidates(CASES, modes, path)

    assert count == 2
    with open(path, encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert [row["source_id"] for row in rows] == ["p1", "p2"]
    assert rows[0]["claim_number"] == "2"
    assert set(rows[0]) == set(CSV_FIELDS)
    assert not {"retrieved_by", "best_rank", "mode"} & set(rows[0])


def test_export_candidates_builds_kipris_link_when_source_url_is_missing(tmp_path):
    path = tmp_path / "patent_candidates.csv"

    export_candidates(
        CASES,
        {"dense": lambda query: [result("1020200000001")]},
        path,
    )

    with open(path, encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert rows[0]["url"] == (
        "https://www.kipris.or.kr/khome/search/searchResult.do?queryText=1020200000001"
    )


def test_import_labels_waits_until_every_candidate_is_judged(tmp_path):
    path = tmp_path / "candidates.csv"
    rows = [
        {"case_id": "SF-01-cobot", "source_id": "p1", "relevant": "1"},
        {"case_id": "SF-01-cobot", "source_id": "p2", "relevant": ""},
    ]
    with open(path, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["case_id", "source_id", "relevant"])
        writer.writeheader()
        writer.writerows(rows)

    updated, pending = import_labels(CASES, path)

    assert pending == {"SF-01-cobot": 1}
    assert updated[0]["labeled"] is False

    rows[1]["relevant"] = "0"
    with open(path, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["case_id", "source_id", "relevant"])
        writer.writeheader()
        writer.writerows(rows)
    updated, pending = import_labels(CASES, path)
    assert pending == {}
    assert updated[0]["labeled"] is True
    assert updated[0]["relevant_source_ids"] == ["p1"]
    assert updated[0]["judged_source_ids"] == ["p1", "p2"]


def test_import_rejects_non_binary_relevance_values(tmp_path):
    path = tmp_path / "patent_candidates.csv"
    with open(path, "w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=["case_id", "source_id", "relevant"])
        writer.writeheader()
        writer.writerow(
            {"case_id": "SF-01-cobot", "source_id": "p1", "relevant": "maybe"}
        )

    with pytest.raises(ValueError, match="0 or 1"):
        import_labels(CASES, path)
