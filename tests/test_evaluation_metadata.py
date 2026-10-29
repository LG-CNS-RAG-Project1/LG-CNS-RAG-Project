from evaluation.evaluate import RESULT_FIELDS, attach_run_metadata, index_snapshot


def test_retrieval_csv_metadata_identifies_mode_model_prompt_and_commit():
    rows = attach_run_metadata(
        [{}],
        "bm25",
        False,
        evaluation_data={"cases": [{"case_id": "case-1", "label": ["p1"]}]},
        index_metadata={
            "index_documents": 2,
            "index_snapshot_sha256": "a" * 64,
        },
    )
    row = rows[0]
    assert row["mode"] == "bm25"
    assert row["model"] == "BM25"
    assert row["prompt"] == "n/a · retrieval"
    assert len(row["commit"]) == 40
    assert len(row["evaluation_data_sha256"]) == 64
    assert row["index_documents"] == 2
    assert row["index_snapshot_sha256"] == "a" * 64
    assert row["top_k"] == 5
    assert row["candidate_k"] == 20
    assert row["rrf_k"] == 60
    assert row["embedding_model"] == "n/a"
    assert row["reranker_model"] == "none"
    assert row["bm25_k1"] == 1.5
    assert row["bm25_b"] == 0.75
    assert isinstance(row["working_tree_dirty"], bool)
    assert {"mode", "model", "prompt", "commit", "evaluation_data_sha256"} <= set(
        RESULT_FIELDS
    )


def test_index_snapshot_is_independent_of_collection_iteration_order():
    class Collection:
        name = "patents"
        metadata = {"hnsw:space": "cosine"}

        def __init__(self, ids, documents, metadatas):
            self.snapshot = {
                "ids": ids,
                "documents": documents,
                "metadatas": metadatas,
            }

        def get(self, include):
            assert include == ["documents", "metadatas"]
            return self.snapshot

    first = Collection(["p2", "p1"], ["text 2", "text 1"], [{}, {"year": 2024}])
    second = Collection(["p1", "p2"], ["text 1", "text 2"], [{"year": 2024}, {}])
    assert index_snapshot(first) == index_snapshot(second)
    assert index_snapshot(first)["index_documents"] == 2
