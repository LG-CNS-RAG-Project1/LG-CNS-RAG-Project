import csv

import pytest
import evaluation.patent_chunk_rerank_experiment as experiment

from evaluation.patent_chunk_rerank_experiment import (
    aggregate_patent_scores,
    build_experiment_chunks,
    build_reranker_document,
    corpus_fingerprint,
    corpus_inventory,
    score_experiment,
)
from src.schemas import PatentClaim, PatentDocument


def sample_patent():
    return PatentDocument(
        patent_id="P-1",
        application_number="P-1",
        title="공정 제어 장치",
        abstract="공정 데이터를 이용해 제어 조건을 조정한다.",
        claims="독립항 원문 종속항 원문",
        claim_items=[
            PatentClaim(
                claim_number=1,
                text="공정 제어 장치.",
                claim_type="independent",
                version_id="V1",
            ),
            PatentClaim(
                claim_number=2,
                text="제1항에 있어서 센서를 포함하는 장치.",
                claim_type="dependent",
                depends_on=[1],
                version_id="V1",
            ),
        ],
        claim_version_id="V1",
        publication_number="PUB-1",
        technology_area_ids=["SF-05"],
    )


def test_inventory_tracks_claim_coverage_and_reproducible_fingerprint():
    patents = [sample_patent()]

    inventory = corpus_inventory(patents)

    assert inventory["areas"]["SF-05"]["patent_count"] == 1
    assert inventory["areas"]["SF-05"]["independent_claim_count"] == 1
    assert inventory["areas"]["SF-05"]["dependent_claim_count"] == 1
    assert inventory["areas"]["SF-02"]["patent_count"] == 0
    assert corpus_fingerprint(patents) == corpus_fingerprint(patents)


def test_independent_strategy_keeps_abstract_and_only_independent_claims():
    chunks = build_experiment_chunks([sample_patent()], "SF-05", "independent")

    assert [chunk.section for chunk in chunks] == ["abstract", "claims"]
    assert chunks[-1].claim_number == 1
    assert chunks[-1].claim_type == "independent"


def test_parent_context_adds_exact_ancestor_text_and_preserves_claim_metadata():
    chunks = build_experiment_chunks([sample_patent()], "SF-05", "parent_context")
    dependent = next(chunk for chunk in chunks if chunk.claim_number == 2)

    assert "상위 청구항 1 원문: 공정 제어 장치." in dependent.text
    assert "현재 청구항 2 원문: 제1항에 있어서 센서를 포함하는 장치." in dependent.text
    assert dependent.depends_on == [1]
    assert dependent.version_id == "V1"


def test_parent_context_ignores_missing_and_cyclic_dependency_references():
    patent = sample_patent()
    patent.claim_items[0].depends_on = [2, 99]
    chunks = build_experiment_chunks([patent], "SF-05", "parent_context")

    assert len(chunks) == 3


def test_aggregation_limits_duplicate_chunk_influence_and_preserves_evidence():
    rows = [
        {
            "patent_id": "P-1",
            "version_id": "V1",
            "chunk_id": "abstract",
            "score": 1.0,
            "section": "abstract",
            "claim_type": None,
        },
        {
            "patent_id": "P-1",
            "version_id": "V1",
            "chunk_id": "claim-1",
            "score": 0.9,
            "section": "claims",
            "claim_type": "independent",
            "claim_number": 1,
        },
        {
            "patent_id": "P-1",
            "version_id": "V1",
            "chunk_id": "claim-2",
            "score": 0.8,
            "section": "claims",
            "claim_type": "dependent",
            "claim_number": 2,
            "depends_on": [1],
        },
        {
            "patent_id": "P-1",
            "version_id": "V2",
            "chunk_id": "claim-v2",
            "score": 0.7,
            "section": "claims",
            "claim_type": "independent",
            "claim_number": 1,
        },
    ]

    maximum = aggregate_patent_scores(rows, "max")
    top_mean = aggregate_patent_scores(rows[:3], "top_n_mean", top_n=2)
    weighted = aggregate_patent_scores(rows[:3], "section_weighted")

    assert len(maximum) == 2
    assert maximum[0]["version_id"] == "V1"
    assert maximum[0]["representative_chunk_id"] == "abstract"
    assert maximum[0]["claim_numbers"] == [1, 2]
    assert maximum[0]["depends_on"]["2"] == [1]
    assert top_mean[0]["score"] == 0.95
    assert weighted[0]["matched_sections"] == ["abstract", "claims"]


def test_reranker_profiles_select_controlled_text_and_record_input_sections():
    patent = sample_patent()

    combined = build_reranker_document(patent, "title_abstract_independent")
    claims_only = build_reranker_document(patent, "claims_only")

    assert "공정 제어 장치" in combined.content
    assert "공정 데이터를 이용해 제어 조건을 조정한다." in combined.content
    assert "독립항 1" in combined.content
    assert "현재 청구항" not in claims_only.content
    assert "청구항 1 (independent)" in claims_only.content
    assert "청구항 2 (dependent)" in claims_only.content
    assert combined.metadata["input_sections"] == [
        "title",
        "abstract",
        "independent_claims",
    ]
    assert claims_only.metadata["input_sections"] == ["claims"]
    assert combined.metadata["version_id"] == "V1"


def test_score_requires_human_labels_and_reports_candidate_pool_metrics(tmp_path):
    candidates = [
        {
            "case_id": "SF-05-process-control",
            "technology_area_id": "SF-05",
            "source_id": "P-1",
            "relevant": "1",
            "review_status": "reviewed",
            "label_source": "human",
        },
        {
            "case_id": "SF-05-process-control",
            "technology_area_id": "SF-05",
            "source_id": "P-2",
            "relevant": "0",
            "review_status": "reviewed",
            "label_source": "human",
        },
    ]
    rankings = [
        {
            "case_id": "SF-05-process-control",
            "technology_area_id": "SF-05",
            "run_id": "baseline_max",
            "rank": str(rank),
            "source_id": source_id,
            "search_ms": "3.0",
            "model_load_ms": "0",
            "rerank_ms": "0",
        }
        for rank, source_id in enumerate(["P-1", "P-2"], 1)
    ]
    for name, rows in [("candidates.csv", candidates), ("rankings.csv", rankings)]:
        with (tmp_path / name).open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=rows[0].keys())
            writer.writeheader()
            writer.writerows(rows)

    result = score_experiment(tmp_path)

    assert result["status"] == "scored"
    assert result["human_judged_candidate_count"] == 2
    assert result["per_query"][0]["candidate_recall_at_k"] == 1.0
    assert result["per_query"][0]["precision_at_5"] == 0.5
    assert result["per_query"][0]["ndcg_at_5"] == 1.0


def test_ai_draft_labels_do_not_complete_a_judged_pool(tmp_path):
    candidate = {
        "case_id": "SF-05-process-control",
        "technology_area_id": "SF-05",
        "source_id": "P-1",
        "relevant": "1",
        "review_status": "reviewed",
        "label_source": "ai_draft",
    }
    ranking = {
        "case_id": "SF-05-process-control",
        "technology_area_id": "SF-05",
        "run_id": "baseline_max",
        "rank": "1",
        "source_id": "P-1",
        "search_ms": "1",
        "model_load_ms": "0",
        "rerank_ms": "0",
    }
    for name, row in [("candidates.csv", candidate), ("rankings.csv", ranking)]:
        with (tmp_path / name).open("w", encoding="utf-8-sig", newline="") as file:
            writer = csv.DictWriter(file, fieldnames=row.keys())
            writer.writeheader()
            writer.writerow(row)

    result = score_experiment(tmp_path)

    assert result["status"] == "awaiting_human_labels"
    assert result["human_judged_candidate_count"] == 0
    assert result["per_query"] == []


def test_experiment_refuses_to_merge_multiple_versions_with_same_patent_id(
    tmp_path, monkeypatch
):
    patent = sample_patent()
    newer = patent.model_copy(update={"claim_version_id": "V2"})
    monkeypatch.setattr(experiment, "load_patents", lambda: [patent, newer])
    monkeypatch.setattr(
        experiment, "load_cases", lambda: [{"case_id": "q", "query": "query"}]
    )

    with pytest.raises(ValueError, match="multiple document versions"):
        experiment.run_experiment(tmp_path)
