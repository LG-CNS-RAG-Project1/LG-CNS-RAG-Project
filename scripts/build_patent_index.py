"""저장된 특허 JSONL 문서를 로컬 Chroma에 사전 색인한다."""

import argparse

from src.ingestion.patent_processor import build_patent_index, load_technology_areas


def main() -> None:
    parser = argparse.ArgumentParser(description="특허 JSONL을 Chroma에 색인합니다")
    parser.add_argument(
        "--field-id",
        choices=sorted(load_technology_areas()),
        help="지정한 technology area의 특허만 색인",
    )
    args = parser.parse_args()
    documents, chunks = build_patent_index(technology_area_id=args.field_id)
    print(f"대상 특허 문헌: {documents}건")
    print(f"신규·변경 색인 청크: {chunks}개")


if __name__ == "__main__":
    main()
