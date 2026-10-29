"""특허 분석의 구성요소 주장과 인용 근거를 사람이 검토하도록 내보낸다."""

import argparse
import csv
import hashlib
import json
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.schemas import PatentReport

ROOT_DIR = Path(__file__).resolve().parents[1]
LABELS_DIR = ROOT_DIR / "evaluation" / "labels"
RESULTS_DIR = ROOT_DIR / "evaluation" / "results"
LABELS = {"supported", "partially_supported", "unsupported", "insufficient_evidence"}
CSV_FIELDS = [
    "sample_id",
    "report_sha256",
    "patent_id",
    "title",
    "component_id",
    "idea_component",
    "status",
    "claim_statement",
    "citation_ids",
    "citation_contexts",
    "groundedness",
    "note",
]


def export_review_rows(report: PatentReport, report_sha256: str) -> list[dict]:
    """보고서의 구성요소 비교별로 사람이 검토할 주장과 인용을 만든다."""
    evidence_by_id = {item.citation_id: item for item in report.evidence}
    rows = []
    for review in report.patent_reviews:
        for comparison in review.component_comparisons:
            citations = [
                evidence_by_id[citation_id]
                for citation_id in comparison.citation_ids
                if citation_id in evidence_by_id
            ]
            statement = {
                "overlap": comparison.overlap,
                "difference": comparison.difference,
                "uncertainty": comparison.uncertainty,
                "matched_text": comparison.matched_text,
            }
            identity = "|".join(
                [report_sha256, review.patent_id, comparison.component_id]
            )
            sample_id = hashlib.sha256(identity.encode("utf-8")).hexdigest()[:20]
            rows.append(
                {
                    "sample_id": sample_id,
                    "report_sha256": report_sha256,
                    "patent_id": review.patent_id,
                    "title": review.title,
                    "component_id": comparison.component_id,
                    "idea_component": comparison.idea_component,
                    "status": comparison.status,
                    "claim_statement": json.dumps(
                        statement, ensure_ascii=False, sort_keys=True
                    ),
                    "citation_ids": json.dumps(comparison.citation_ids),
                    "citation_contexts": json.dumps(
                        [
                            {
                                "citation_id": item.citation_id,
                                "section": item.section,
                                "claim_number": item.claim_number,
                                "version_id": item.version_id,
                                "quote": item.quote,
                                "source_url": item.source_url,
                            }
                            for item in citations
                        ],
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    "groundedness": "",
                    "note": "",
                }
            )
    if not rows:
        raise ValueError("report contains no patent component comparisons to review")
    return rows


def export_report(report_path: Path, output_path: Path | None = None) -> Path:
    """PatentReport JSON을 검토 CSV로 변환하고 보고서 지문을 기록한다."""
    payload = report_path.read_bytes()
    report = PatentReport.model_validate_json(payload)
    report_sha256 = hashlib.sha256(payload).hexdigest()
    rows = export_review_rows(report, report_sha256)
    if output_path is None:
        output_path = LABELS_DIR / f"patent_groundedness_{report_sha256[:12]}.csv"
    if output_path.exists():
        raise FileExistsError(
            f"refusing to overwrite existing review labels: {output_path}"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    return output_path


def score_review(path: Path, output_path: Path | None = None) -> dict:
    """완료된 사람 라벨을 검증하고 분포와 입력 지문을 저장한다."""
    with path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        missing = set(CSV_FIELDS) - set(reader.fieldnames or [])
        if missing:
            raise ValueError(f"review CSV missing fields: {', '.join(sorted(missing))}")
        rows = list(reader)
    if not rows:
        raise ValueError("review CSV contains no rows")
    invalid = [
        row["sample_id"]
        for row in rows
        if row.get("groundedness", "").strip() not in LABELS
    ]
    if invalid:
        raise ValueError(f"missing or invalid groundedness labels: {len(invalid)} rows")
    report_hashes = sorted({row["report_sha256"] for row in rows})
    counts = Counter(row["groundedness"].strip() for row in rows)
    result = {
        "status": "completed",
        "review_rows": len(rows),
        "groundedness_counts": dict(sorted(counts.items())),
        "label_csv_sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        "report_sha256": report_hashes,
        "scored_at_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "interpretation": "사람이 검토한 주장 지지 분포이며, 법률 판단이나 모집단 성능 보장이 아님",
    }
    if output_path is None:
        output_path = (
            RESULTS_DIR
            / f"patent_groundedness_{path.stem.removeprefix('patent_groundedness_')}.json"
        )
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(
        json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(description="특허 주장 근거 지지의 사람 검토 평가")
    commands = parser.add_subparsers(dest="command", required=True)
    export = commands.add_parser("export", help="PatentReport JSON에서 검토 CSV 생성")
    export.add_argument("report", type=Path, help="PatentReport JSON 경로")
    export.add_argument("--output", type=Path, help="검토 CSV 경로")
    score = commands.add_parser("score", help="사람 라벨 CSV 검증 및 결과 집계")
    score.add_argument("labels", type=Path, help="groundedness 라벨을 채운 CSV")
    score.add_argument("--output", type=Path, help="결과 JSON 경로")
    args = parser.parse_args()
    if args.command == "export":
        print(export_report(args.report, args.output))
    else:
        print(
            json.dumps(
                score_review(args.labels, args.output), ensure_ascii=False, indent=2
            )
        )


if __name__ == "__main__":
    main()
