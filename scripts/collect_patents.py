"""구조화된 아이디어의 검색어 계획으로 KIPRIS 특허를 수집한다."""

import argparse
from pathlib import Path

from src.ingestion.patent_processor import collect_to_jsonl, load_technology_areas
from src.retrieval.patent_search import build_patent_queries
from src.schemas import PatentSearchRequest


def main() -> None:
    parser = argparse.ArgumentParser(description="아이디어에서 특허 문헌을 수집합니다")
    parser.add_argument(
        "--request",
        type=Path,
        required=True,
        help="PatentSearchRequest JSON 파일",
    )
    parser.add_argument(
        "--field-id",
        choices=sorted(load_technology_areas()),
        help="수집 특허에 연결할 technology area ID",
    )
    parser.add_argument("--limit", type=int, default=10, help="검색어당 최대 문헌 수")
    parser.add_argument(
        "--include-claims",
        action="store_true",
        help="KIPRIS 청구항 상세 API도 조회",
    )
    args = parser.parse_args()
    if args.limit < 1:
        parser.error("--limit은 1 이상이어야 합니다.")

    request = PatentSearchRequest.model_validate_json(
        args.request.read_text(encoding="utf-8")
    )
    plan = build_patent_queries(request)
    keywords = list(
        dict.fromkeys(
            query
            for element in plan.queries
            for query in element.korean_queries + element.english_queries
        )
    )
    field_id = args.field_id or request.technology_area_id
    collected, total = collect_to_jsonl(
        keywords,
        limit=args.limit,
        technology_area_id=field_id,
        include_claims=args.include_claims,
    )
    print(f"기술 요소: {len(plan.queries)}개")
    print(f"KIPRIS 검색어: {len(keywords)}개")
    print(f"이번 수집: {collected}건 / 누적: {total}건")


if __name__ == "__main__":
    main()
