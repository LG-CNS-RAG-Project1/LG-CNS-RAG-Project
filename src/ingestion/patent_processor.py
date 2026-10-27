"""KIPRIS 특허 검색 결과를 내부 문서 및 검색 청크로 변환한다."""

import argparse
from pathlib import Path

from src.schemas import PatentChunk, PatentDocument
from src.ingestion.kipris_client import search_patents as search_kipris_patents

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


def collect_patents(
    keywords: str | list[str],
    limit: int = 20,
) -> list[dict]:
    """하나 이상의 키워드로 KIPRIS 특허를 수집한다."""
    if isinstance(keywords, str):
        keywords = [keywords]

    if not keywords or any(
        not isinstance(keyword, str) or not keyword.strip() for keyword in keywords
    ):
        raise ValueError("검색 키워드는 비어 있을 수 없습니다.")

    if limit < 1:
        raise ValueError("limit은 1 이상이어야 합니다.")

    raw_patents = []

    # 공백 정리 및 중복 키워드 제거 (입력 순서 유지)
    unique_keywords = dict.fromkeys(keyword.strip() for keyword in keywords)

    for keyword in unique_keywords:
        results = search_kipris_patents(keyword, limit=limit)
        raw_patents.extend(results)

    return raw_patents


def save_documents(
    documents: list[PatentDocument],
    path: Path = OUTPUT_PATH,
) -> Path:
    """기존 특허를 유지하면서 출원번호 기준으로 중복 없이 JSONL에 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)

    merged = {}

    if path.exists():
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    patent = PatentDocument.model_validate_json(line)
                    merged[patent.patent_id] = patent

    for patent in documents:
        merged[patent.patent_id] = patent

    with open(path, "w", encoding="utf-8") as f:
        for patent in merged.values():
            f.write(patent.model_dump_json() + "\n")

    return path


def run_pipeline(
    keyword: str | list[str],
    limit: int = 20,
) -> tuple[int, int, int]:
    """KIPRIS 특허 수집부터 ChromaDB 증분 색인까지 실행한다."""
    from src.retrieval.market_search import embed_texts
    from src.retrieval.patent_store import build_index, get_collection

    # 1. KIPRIS 특허 수집 (단일 또는 다중 키워드)
    raw_patents = collect_patents(keyword, limit=limit)

    # 2. 문서 변환 및 중복 제거
    documents = build_documents(raw_patents)

    # 3. JSONL 누적 저장
    save_documents(documents, path=OUTPUT_PATH)

    # 4. 누적 특허 전체 로드
    all_documents = [
        PatentDocument.model_validate_json(line)
        for line in OUTPUT_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]

    # 5. 청크 생성
    all_chunks = build_chunks(all_documents)

    # 6. ChromaDB 증분 색인
    collection = get_collection()
    indexed_count = build_index(
        chunks=all_chunks,
        patents=all_documents,
        collection=collection,
        embed_fn=embed_texts,
    )

    return len(documents), len(all_documents), indexed_count


def main() -> None:
    """KIPRIS 특허를 수집·전처리하고 JSONL 및 ChromaDB에 저장한다."""
    parser = argparse.ArgumentParser(description="KIPRIS 특허 수집 및 전처리")
    parser.add_argument(
        "--keyword",
        action="append",
        required=True,
        help="특허 검색 키워드 (여러 번 지정 가능)",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="키워드당 최대 수집 건수 (1~500)",
    )

    args = parser.parse_args()

    collected, total, indexed = run_pipeline(
        keyword=args.keyword,
        limit=args.limit,
    )

    print(f"이번 수집: {collected}건")
    print(f"전체 누적 특허: {total}건")
    print(f"신규·변경 색인 청크: {indexed}개")
    print(f"저장 경로: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
