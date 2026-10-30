import csv
import json

import pytest

from evaluation.patent_domain_experiment import (
    score_experiment,
    preserve_candidate_labels,
)


def test_preserve_candidate_labels_keeps_matching_human_review(tmp_path):
    path = tmp_path / "candidates.csv"
    with path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file,
            fieldnames=[
                "case_id",
                "corpus_id",
                "source_id",
                "relevant",
                "note",
                "review_status",
                "label_source",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "case_id": "Q1",
                "corpus_id": "A",
                "source_id": "P1",
                "relevant": "1",
                "note": "독립항 확인",
                "review_status": "reviewed",
                "label_source": "human",
            }
        )
    candidates = {
        ("Q1", "A", "P1"): {
            "relevant": "",
            "note": "",
            "review_status": "to_review",
            "label_source": "unreviewed",
        },
        ("Q1", "A", "P2"): {
            "relevant": "",
            "note": "",
            "review_status": "to_review",
            "label_source": "unreviewed",
        },
    }

    preserve_candidate_labels(candidates, path)

    assert candidates[("Q1", "A", "P1")]["relevant"] == "1"
    assert candidates[("Q1", "A", "P1")]["review_status"] == "reviewed"
    assert candidates[("Q1", "A", "P1")]["label_source"] == "human"
    assert candidates[("Q1", "A", "P2")]["review_status"] == "to_review"


def write_score_inputs(output_dir, *, review_status="reviewed", label_source="human"):
    output_dir.mkdir(parents=True, exist_ok=True)
    fields = [
        "case_id",
        "corpus_id",
        "source_id",
        "relevant",
        "review_status",
        "label_source",
    ]
    with (output_dir / "candidates.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.DictWriter(file, fieldnames=fields)
        writer.writeheader()
        writer.writerows(
            [
                {
                    "case_id": "Q1",
                    "corpus_id": "A",
                    "source_id": "P1",
                    "relevant": "1",
                    "review_status": review_status,
                    "label_source": label_source,
                },
                {
                    "case_id": "Q1",
                    "corpus_id": "A",
                    "source_id": "P2",
                    "relevant": "0",
                    "review_status": "reviewed",
                    "label_source": "human",
                },
            ]
        )
    with (output_dir / "rankings.csv").open(
        "w", encoding="utf-8-sig", newline=""
    ) as file:
        writer = csv.DictWriter(
            file,
            fieldnames=["case_id", "corpus_id", "mode", "rank", "source_id"],
        )
        writer.writeheader()
        writer.writerows(
            [
                {
                    "case_id": "Q1",
                    "corpus_id": "A",
                    "mode": "dense",
                    "rank": 1,
                    "source_id": "P2",
                },
                {
                    "case_id": "Q1",
                    "corpus_id": "A",
                    "mode": "dense",
                    "rank": 2,
                    "source_id": "P1",
                },
            ]
        )


def test_score_reports_pool_recall_only_after_human_review(tmp_path):
    write_score_inputs(tmp_path)

    report = score_experiment(tmp_path)

    assert report["status"] == "scored"
    result = report["summary"][0]
    assert result["ndcg_at_5"] == pytest.approx(0.6309, rel=1e-3)
    assert result["recall_at_pool_k"] == 1.0
    assert result["judged_candidate_count"] == 2
    assert json.loads((tmp_path / "metrics.json").read_text(encoding="utf-8"))


def test_score_rejects_ai_draft_as_ground_truth(tmp_path):
    write_score_inputs(tmp_path, review_status="to_review", label_source="ai_draft")

    with pytest.raises(ValueError, match="human-reviewed"):
        score_experiment(tmp_path)
