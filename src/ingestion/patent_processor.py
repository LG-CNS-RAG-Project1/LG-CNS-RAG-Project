"""KIPRIS 특허 검색 결과를 내부 문서 및 검색 청크로 변환한다."""

from src.schemas import PatentChunk, PatentDocument
from pathlib import Path
from src.ingestion.kipris_client import search_patents as search_kipris_patents

import argparse

ROOT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_PATH = ROOT_DIR / "data" / "patents" / "processed" / "patent_docs.jsonl"


def to_patent_document(raw: dict) -> PatentDocument:
    """KIPRIS 검색 결과를 PatentDocument로 변환한다."""
    application_number = raw.get("application_number")

    if not application_number or not str(application_number).strip():
        raise ValueError("출원번호가 없는 특허는 변환할 수 없습니다.")

    application_number = str(application_number).strip()

    return PatentDocument(
        patent_id=application_number,
        application_number=application_number,
        title=raw.get("title") or "",
        abstract=raw.get("abstract") or "",
        claims=raw.get("claims") or "",
        applicant=raw.get("applicant"),
        application_date=raw.get("application_date"),
        publication_number=raw.get("publication_number"),
        registration_number=raw.get("registration_number"),
        source=raw.get("source") or "KIPRIS Plus",
    )


def build_chunks(patents: list[PatentDocument]) -> list[PatentChunk]:
    """특허 문서의 초록과 청구항을 검색용 청크로 변환한다."""
    chunks = []

    for patent in patents:
        sections = {
            "abstract": patent.abstract,
            "claims": patent.claims,
        }

        for section, text in sections.items():
            if not text or not text.strip():
                continue

            chunks.append(
                PatentChunk(
                    chunk_id=f"{patent.patent_id}_{section}_0",
                    patent_id=patent.patent_id,
                    section=section,
                    text=text.strip(),
                    chunk_index=0,
                )
            )

    return chunks


def build_documents(records: list[dict]) -> list[PatentDocument]:
    """KIPRIS 검색 결과를 출원번호 기준으로 중복 제거하고 문서로 변환한다."""
    documents = []
    seen = set()

    for record in records:
        application_number = str(record.get("application_number") or "").strip()

        if not application_number or application_number in seen:
            continue

        document = to_patent_document(record)
        documents.append(document)
        seen.add(application_number)

    return documents


def save_documents(
    documents: list[PatentDocument],
    path: Path = OUTPUT_PATH,
) -> Path:
    """특허 문서를 JSONL로 저장한다. 기존 파일은 덮어쓴다."""
    path.parent.mkdir(parents=True, exist_ok=True)

    with open(path, "w", encoding="utf-8") as f:
        for document in documents:
            f.write(document.model_dump_json() + "\n")

    return path


def collect_and_process(keyword: str, limit: int = 20):
    """KIPRIS 특허를 수집·전처리하고 JSONL로 저장한다."""
    raw_patents = search_kipris_patents(keyword, limit=limit)
    documents = build_documents(raw_patents)
    chunks = build_chunks(documents)

    save_documents(documents)

    return documents, chunks


def main() -> None:
    """KIPRIS 특허를 수집·전처리하고 JSONL로 저장한다."""
    parser = argparse.ArgumentParser(description="KIPRIS 특허 수집 및 전처리")
    parser.add_argument(
        "--keyword",
        required=True,
        help="특허 검색 키워드",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="최대 수집 건수 (1~500)",
    )

    args = parser.parse_args()

    documents, chunks = collect_and_process(
        keyword=args.keyword,
        limit=args.limit,
    )

    print(f"수집·변환 문서: {len(documents)}건")
    print(f"생성 청크: {len(chunks)}개")
    print(f"저장 경로: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
