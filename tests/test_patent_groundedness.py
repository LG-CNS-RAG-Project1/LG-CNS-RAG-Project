import csv
import json

import pytest

from evaluation.patent_groundedness import CSV_FIELDS, export_report, score_review
from src.schemas import (
    PatentComponentComparison,
    PatentDocumentReview,
    PatentEvidence,
    PatentReport,
)


def report():
    return PatentReport(
        status="completed",
        search_scope="mock patent search",
        evidence=[
            PatentEvidence(
                citation_id=1,
                patent_id="P1",
                title="비전 검사 장치",
                section="claims",
                quote="센서를 포함하는 검사 장치.",
                claim_number=1,
                claim_type="independent",
                version_id="KR123B1",
                source_url="https://example.test/patent",
            )
        ],
        patent_reviews=[
            PatentDocumentReview(
                patent_id="P1",
                title="비전 검사 장치",
                citation_ids=[1],
                component_comparisons=[
                    PatentComponentComparison(
                        component_id="C1",
                        idea_component="센서 검사",
                        status="partial",
                        citation_ids=[1],
                        overlap="센서를 포함함",
                        difference="검사 대상은 추가 확인 필요",
                        uncertainty="전체 청구항 검토 필요",
                        matched_text="센서를 포함하는 검사 장치.",
                    )
                ],
            )
        ],
    )


def test_export_report_creates_blinded_human_review_context(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(report().model_dump_json(), encoding="utf-8")
    output_path = tmp_path / "review.csv"

    result_path = export_report(report_path, output_path)

    with result_path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    assert result_path == output_path
    assert len(rows) == 1
    assert set(rows[0]) == set(CSV_FIELDS)
    assert rows[0]["groundedness"] == ""
    assert "센서를 포함하는 검사 장치." in rows[0]["citation_contexts"]
    with pytest.raises(FileExistsError):
        export_report(report_path, output_path)


def test_score_review_requires_complete_human_labels_and_saves_hashes(tmp_path):
    report_path = tmp_path / "report.json"
    report_path.write_text(report().model_dump_json(), encoding="utf-8")
    labels_path = export_report(report_path, tmp_path / "review.csv")

    with pytest.raises(ValueError, match="missing or invalid"):
        score_review(labels_path, tmp_path / "result.json")

    with labels_path.open(encoding="utf-8-sig", newline="") as file:
        rows = list(csv.DictReader(file))
    rows[0]["groundedness"] = "partially_supported"
    with labels_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)

    output_path = tmp_path / "result.json"
    result = score_review(labels_path, output_path)

    assert result["groundedness_counts"] == {"partially_supported": 1}
    assert len(result["report_sha256"]) == 1
    assert json.loads(output_path.read_text(encoding="utf-8"))["status"] == "completed"
