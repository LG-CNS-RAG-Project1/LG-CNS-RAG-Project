"""실제 특허 평가의 질의·후보 파일을 API 없이 사전 점검한다."""

import argparse
import csv
import hashlib
import json
from collections import Counter
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT_DIR / "evaluation" / "patent_cases.json"
CANDIDATES_PATH = ROOT_DIR / "evaluation" / "labels" / "patent_candidates.csv"
REQUIRED_CANDIDATE_FIELDS = {
    "case_id",
    "source_id",
    "title",
    "url",
    "relevant",
}


def sha256_file(path: Path) -> str:
    """파일 원본 바이트의 SHA-256을 계산한다."""
    return hashlib.sha256(path.read_bytes()).hexdigest()


def inspect_patent_evaluation(
    cases_path: Path = CASES_PATH, candidates_path: Path = CANDIDATES_PATH
) -> dict:
    """평가 질의와 후보의 구조·라벨 진행 상태를 검사한다."""
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    with candidates_path.open(encoding="utf-8-sig", newline="") as file:
        reader = csv.DictReader(file)
        fields = set(reader.fieldnames or [])
        missing_fields = sorted(REQUIRED_CANDIDATE_FIELDS - fields)
        rows = list(reader)

    case_ids = {case["case_id"] for case in cases}
    if len(case_ids) != len(cases):
        errors = ["duplicate case_id values in patent_cases.json"]
    else:
        errors = []
    counts = Counter(row.get("case_id", "") for row in rows)
    duplicates = []
    seen = set()
    labeled = 0
    missing_urls = 0
    for row in rows:
        key = (row.get("case_id", ""), row.get("source_id", ""))
        if key in seen:
            duplicates.append(key)
        seen.add(key)
        if row.get("case_id", "") not in case_ids:
            errors.append(f"unknown case_id: {row.get('case_id', '')}")
        if not row.get("source_id", "").strip() or not row.get("title", "").strip():
            errors.append(f"missing source_id or title: {key}")
        if not row.get("url", "").strip():
            missing_urls += 1
        relevance = row.get("relevant", "").strip()
        if relevance in {"0", "1"}:
            labeled += 1
        elif relevance:
            errors.append(f"relevant must be blank, 0, or 1: {key}")

    if missing_fields:
        errors.append(f"missing CSV fields: {', '.join(missing_fields)}")
    if duplicates:
        errors.append(f"duplicate case/source rows: {len(duplicates)}")
    if missing_urls:
        errors.append(f"missing source URLs: {missing_urls}")
    missing_cases = sorted(case_ids - set(counts))
    if missing_cases:
        errors.append(f"cases without candidates: {', '.join(missing_cases)}")

    return {
        "status": (
            "invalid"
            if errors
            else (
                "ready_for_label_import"
                if labeled == len(rows)
                else "ready_for_human_review"
            )
        ),
        "case_count": len(cases),
        "candidate_count": len(rows),
        "labeled_count": labeled,
        "pending_count": len(rows) - labeled,
        "missing_url_count": missing_urls,
        "case_candidate_counts": dict(sorted(counts.items())),
        "cases_sha256": sha256_file(cases_path),
        "candidates_sha256": sha256_file(candidates_path),
        "errors": errors,
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="특허 평가 데이터 사전 점검")
    parser.add_argument("--json", action="store_true", help="결과를 JSON으로 출력")
    args = parser.parse_args()
    report = inspect_patent_evaluation()
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(f"status: {report['status']}")
        print(f"cases: {report['case_count']}")
        print(f"candidates: {report['candidate_count']}")
        print(f"labeled: {report['labeled_count']}")
        print(f"pending: {report['pending_count']}")
        print(f"missing_urls: {report['missing_url_count']}")
        print(f"cases_sha256: {report['cases_sha256']}")
        print(f"candidates_sha256: {report['candidates_sha256']}")
        for case_id, count in report["case_candidate_counts"].items():
            print(f"{case_id}: {count}")
        for error in report["errors"]:
            print(f"ERROR: {error}")
    if report["errors"]:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
