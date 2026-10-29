"""사람 라벨 검토를 위해 로컬 특허 원문 문맥을 묶어 저장한다."""

import argparse
import csv
import hashlib
import json
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parents[1]
CANDIDATES_PATH = ROOT_DIR / "evaluation" / "labels" / "patent_candidates.csv"
PATENTS_PATH = ROOT_DIR / "data" / "patents" / "processed" / "patent_docs.jsonl"
OUTPUT_PATH = (
    ROOT_DIR / "data" / "patents" / "processed" / "patent_eval_review_context.jsonl"
)


def build_review_context(candidates: list[dict], patents: list[dict]) -> list[dict]:
    """평가 후보를 로컬 원문·청구항과 문헌 식별자 기준으로 연결한다."""
    by_application = {
        str(patent.get("application_number") or patent.get("patent_id") or ""): patent
        for patent in patents
    }
    output = []
    for candidate in candidates:
        source_id = candidate.get("source_id", "").strip()
        patent = by_application.get(source_id)
        claims = (patent or {}).get("claim_items") or []
        claim_number = candidate.get("claim_number", "").strip()
        available_claim_numbers = {
            str(claim.get("claim_number", "")) for claim in claims
        }
        output.append(
            {
                "case_id": candidate.get("case_id", ""),
                "idea_id": candidate.get("idea_id", ""),
                "technical_element": candidate.get("technical_element", ""),
                "query": candidate.get("query", ""),
                "source_id": source_id,
                "title": candidate.get("title", ""),
                "candidate_summary": candidate.get("summary", ""),
                "candidate_claim_number": claim_number,
                "version_id": candidate.get("version_id", ""),
                "source_url": candidate.get("url", ""),
                "relevant": candidate.get("relevant", ""),
                "note": candidate.get("note", ""),
                "verification": {
                    "local_record_found": patent is not None,
                    "application_number_matches_source_id": (
                        str((patent or {}).get("application_number", "")) == source_id
                    ),
                    "title_matches_local_record": bool(
                        patent
                        and patent.get("title", "").strip()
                        == candidate.get("title", "").strip()
                    ),
                    "candidate_claim_number_found": (
                        claim_number in available_claim_numbers
                        if claim_number
                        else None
                    ),
                },
                "abstract": (patent or {}).get("abstract", ""),
                "claims": claims,
                "claims_text": (patent or {}).get("claims", ""),
                "claim_version_id": (patent or {}).get("claim_version_id", ""),
                "publication_number": (patent or {}).get("publication_number", ""),
                "registration_number": (patent or {}).get("registration_number", ""),
                "applicant": (patent or {}).get("applicant", ""),
                "application_date": (patent or {}).get("application_date", ""),
                "publication_date": (patent or {}).get("publication_date", ""),
            }
        )
    return output


def create_review_context(
    candidates_path: Path = CANDIDATES_PATH,
    patents_path: Path = PATENTS_PATH,
    output_path: Path = OUTPUT_PATH,
) -> dict:
    """검토용 JSONL을 생성하고 원문 대조 통계를 반환한다."""
    with candidates_path.open(encoding="utf-8-sig", newline="") as file:
        candidates = list(csv.DictReader(file))
    patents = [
        json.loads(line)
        for line in patents_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    rows = build_review_context(candidates, patents)
    payload = "".join(
        json.dumps(row, ensure_ascii=False, sort_keys=True) + "\n" for row in rows
    ).encode("utf-8")
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_bytes(payload)

    title_matches = sum(
        row["verification"]["title_matches_local_record"] for row in rows
    )
    claim_rows = [row for row in rows if row["candidate_claim_number"]]
    claim_matches = sum(
        row["verification"]["candidate_claim_number_found"] is True
        for row in claim_rows
    )
    return {
        "candidate_rows": len(rows),
        "local_records_found": sum(
            row["verification"]["local_record_found"] for row in rows
        ),
        "title_matches": title_matches,
        "claim_references_checked": len(claim_rows),
        "claim_references_found": claim_matches,
        "missing_local_records": len(rows)
        - sum(row["verification"]["local_record_found"] for row in rows),
        "title_mismatches": len(rows) - title_matches,
        "claim_references_missing": len(claim_rows) - claim_matches,
        "output_path": str(output_path),
        "output_sha256": hashlib.sha256(payload).hexdigest(),
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="특허 라벨 검토 문맥 생성")
    parser.add_argument(
        "--output", type=Path, default=OUTPUT_PATH, help="검토 문맥 JSONL 저장 경로"
    )
    args = parser.parse_args()
    report = create_review_context(output_path=args.output)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
