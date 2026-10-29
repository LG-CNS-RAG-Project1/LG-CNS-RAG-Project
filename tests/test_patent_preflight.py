import csv
import json

from evaluation.patent_preflight import inspect_patent_evaluation


def test_preflight_reports_complete_review_package_and_fingerprints(tmp_path):
    cases_path = tmp_path / "cases.json"
    candidates_path = tmp_path / "candidates.csv"
    cases_path.write_text(json.dumps([{"case_id": "Q1"}]), encoding="utf-8")
    with candidates_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file, fieldnames=["case_id", "source_id", "title", "url", "relevant"]
        )
        writer.writeheader()
        writer.writerow(
            {
                "case_id": "Q1",
                "source_id": "P1",
                "title": "Fixture patent",
                "url": "https://example.test/patent",
                "relevant": "",
            }
        )

    report = inspect_patent_evaluation(cases_path, candidates_path)

    assert report["status"] == "ready_for_human_review"
    assert report["candidate_count"] == 1
    assert report["pending_count"] == 1
    assert report["missing_url_count"] == 0
    assert len(report["cases_sha256"]) == 64
    assert len(report["candidates_sha256"]) == 64


def test_preflight_rejects_duplicate_candidates_and_invalid_labels(tmp_path):
    cases_path = tmp_path / "cases.json"
    candidates_path = tmp_path / "candidates.csv"
    cases_path.write_text(json.dumps([{"case_id": "Q1"}]), encoding="utf-8")
    with candidates_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(
            file, fieldnames=["case_id", "source_id", "title", "url", "relevant"]
        )
        writer.writeheader()
        row = {
            "case_id": "Q1",
            "source_id": "P1",
            "title": "Fixture patent",
            "url": "https://example.test/patent",
            "relevant": "maybe",
        }
        writer.writerow(row)
        writer.writerow(row)

    report = inspect_patent_evaluation(cases_path, candidates_path)

    assert report["status"] == "invalid"
    assert any("duplicate" in error for error in report["errors"])
    assert any("0, or 1" in error for error in report["errors"])
