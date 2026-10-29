import json

import pytest

from evaluation.patent_fixture import load_fixture


def test_synthetic_patent_fixture_is_repeatable_and_referentially_valid():
    first, first_hash = load_fixture()
    second, second_hash = load_fixture()

    assert first["dataset_id"] == "patent-retrieval-synthetic-v1"
    assert len(first["documents"]) == 8
    assert len(first["queries"]) == 4
    assert first_hash == second_hash


def test_fixture_rejects_non_synthetic_or_unknown_relevance_ids(tmp_path):
    fixture, _ = load_fixture()
    fixture["dataset_type"] = "production"
    path = tmp_path / "fixture.json"
    path.write_text(json.dumps(fixture), encoding="utf-8")

    with pytest.raises(ValueError, match="explicitly marked synthetic"):
        load_fixture(path)

    fixture["dataset_type"] = "synthetic_pipeline_fixture"
    fixture["queries"][0]["relevant_source_ids"] = ["KR-REAL-123"]
    path.write_text(json.dumps(fixture), encoding="utf-8")
    with pytest.raises(ValueError, match="invalid relevance references"):
        load_fixture(path)
