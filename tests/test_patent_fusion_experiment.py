import csv

import pytest

from evaluation.patent_fusion_experiment import _score, reciprocal_rank_fusion


def test_reciprocal_rank_fusion_rewards_consistent_high_ranks():
    ranked, scores = reciprocal_rank_fusion([["A", "B", "C"], ["A", "D", "B"]], rrf_k=1)

    assert ranked[0] == "A"
    assert scores["A"] == pytest.approx(1 / 2 + 1 / 2)
    assert scores["B"] == pytest.approx(1 / 3 + 1 / 4)


def test_reciprocal_rank_fusion_applies_configured_source_weights():
    ranked, scores = reciprocal_rank_fusion(
        [["A", "B"], ["B", "A"]], weights=[2, 0.5], rrf_k=1
    )

    assert ranked[0] == "A"
    assert scores["A"] == pytest.approx(2 / 2 + 0.5 / 3)
    assert scores["B"] == pytest.approx(2 / 3 + 0.5 / 2)


def test_reciprocal_rank_fusion_rejects_invalid_weights():
    with pytest.raises(ValueError, match="weights"):
        reciprocal_rank_fusion([["A"]], weights=[1, 2])


def test_score_keeps_ai_drafts_separate_from_complete_human_pools(tmp_path):
    candidate_path = tmp_path / "candidates.csv"
    fields = [
        "case_id",
        "technology_area_id",
        "source_id",
        "relevant",
        "review_status",
        "label_source",
    ]
    rows = [
        {
            "case_id": "SF-05-test",
            "technology_area_id": "SF-05",
            "source_id": "A",
            "relevant": "1",
            "review_status": "reviewed",
            "label_source": "human",
        },
        {
            "case_id": "SF-05-test",
            "technology_area_id": "SF-05",
            "source_id": "B",
            "relevant": "0",
            "review_status": "reviewed",
            "label_source": "human",
        },
    ]
    with candidate_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)

    result = _score(
        [
            {
                "case_id": "SF-05-test",
                "technology_area_id": "SF-05",
                "run_id": "baseline_bm25",
                "rank": 1,
                "source_id": "B",
            },
            {
                "case_id": "SF-05-test",
                "technology_area_id": "SF-05",
                "run_id": "baseline_bm25",
                "rank": 2,
                "source_id": "A",
            },
        ],
        candidate_path,
    )

    human = result["metrics_by_label_source"]["human"]
    assert human["status"] == "scored"
    assert human["macro"][0]["precision_at_5"] == 0.5
    assert human["macro"][0]["ndcg_at_5"] < 1
    assert result["metrics_by_label_source"]["ai_draft"]["status"] == "awaiting_labels"
