from evaluation.evaluate import RESULT_FIELDS, attach_run_metadata


def test_retrieval_csv_metadata_identifies_mode_model_prompt_and_commit():
    rows = attach_run_metadata([{}], "bm25", False)
    row = rows[0]
    assert row["mode"] == "bm25"
    assert row["model"] == "BM25"
    assert row["prompt"] == "n/a · retrieval"
    assert len(row["commit"]) == 40
    assert {"mode", "model", "prompt", "commit"} <= set(RESULT_FIELDS)
