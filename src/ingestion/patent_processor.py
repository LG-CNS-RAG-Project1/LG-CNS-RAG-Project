"""KIPRIS 특허 검색 결과를 내부 문서 및 검색 청크로 변환한다."""

import argparse
import re
from pathlib import Path

import yaml

from src.schemas import PatentChunk, PatentClaim, PatentDocument
from src.ingestion.kipris_client import (
    KiprisAPIError,
    fetch_patent_claims,
    search_patents as search_kipris_patents,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_PATH = ROOT_DIR / "data" / "patents" / "processed" / "patent_docs.jsonl"
AREAS_PATH = ROOT_DIR / "configs" / "technology_areas.yaml"
CLAIM_HEADING = re.compile(
    r"(?:^|\n)\s*(?:【\s*청구항\s*(\d+)\s*】|청구항\s*(\d+)\s*[.:：]?)",
    re.IGNORECASE,
)
CLAIM_REFERENCE = re.compile(r"(?:제\s*(\d+)\s*항|청구항\s*(\d+)\s*항?)", re.IGNORECASE)
DEPENDENT_CLAIM_REFERENCE = re.compile(
    r"(?:제\s*\d+\s*항|청구항\s*\d+\s*항?).{0,24}에\s*있어서",
    re.IGNORECASE,
)
DELETED_CLAIM = re.compile(r"^(?:\d+\s*[.．:]\s*)?(?:삭제|취하|폐지)\s*[.]?$", re.I)


def structure_claims(
    claims: str | list[dict], version_id: str | None = None
) -> list[PatentClaim]:
    """번호가 포함된 청구항 원문을 독립항·종속항 및 인용 관계로 정리한다."""
    if isinstance(claims, list):
        items = claims
    else:
        matches = list(CLAIM_HEADING.finditer(claims))
        items = []
        for index, match in enumerate(matches):
            number = next((int(value) for value in match.groups() if value), None)
            start = match.end()
            end = (
                matches[index + 1].start() if index + 1 < len(matches) else len(claims)
            )
            text = claims[start:end].strip()
            if number and text:
                items.append({"claim_number": number, "text": text})

    output = []
    seen_numbers = set()
    for item in items:
        try:
            number = int(item["claim_number"])
        except (KeyError, TypeError, ValueError):
            continue
        text = str(item.get("text") or "").strip()
        if (
            number < 1
            or not text
            or DELETED_CLAIM.fullmatch(text)
            or number in seen_numbers
        ):
            continue
        seen_numbers.add(number)
        refs = set()
        for first, last in re.findall(
            r"제\s*(\d+)\s*항\s*내지\s*제?\s*(\d+)\s*항", text
        ):
            low, high = sorted((int(first), int(last)))
            refs.update(range(low, high + 1))
        for match in CLAIM_REFERENCE.finditer(text):
            refs.add(int(match.group(1) or match.group(2)))
        refs.discard(number)
        ordered_refs = sorted(ref for ref in refs if ref > 0)
        explicit_relation = bool(DEPENDENT_CLAIM_REFERENCE.search(text) or ordered_refs)
        output.append(
            PatentClaim(
                claim_number=number,
                text=text,
                claim_type=("dependent" if explicit_relation else "independent"),
                depends_on=ordered_refs,
                version_id=item.get("version_id") or version_id,
            )
        )
    return sorted(output, key=lambda claim: claim.claim_number)


def to_patent_document(raw: dict) -> PatentDocument:
    """KIPRIS 검색 결과를 PatentDocument로 변환한다."""
    application_number = raw.get("application_number")

    if not application_number or not str(application_number).strip():
        raise ValueError("출원번호가 없는 특허는 변환할 수 없습니다.")

    application_number = str(application_number).strip()

    raw_claims = raw.get("claims") or ""
    version_id = (
        raw.get("claim_version_id")
        or raw.get("publication_number")
        or raw.get("registration_number")
    )
    claim_items = structure_claims(raw.get("claim_items") or raw_claims, version_id)
    claims_text = (
        raw_claims
        if isinstance(raw_claims, str)
        else "\n".join(c.text for c in claim_items)
    )
    return PatentDocument(
        patent_id=application_number,
        application_number=application_number,
        title=raw.get("title") or "",
        abstract=raw.get("abstract") or "",
        claims=claims_text,
        claim_items=claim_items,
        claim_version_id=version_id,
        applicant=raw.get("applicant"),
        application_date=raw.get("application_date"),
        publication_date=raw.get("publication_date"),
        public_date=raw.get("public_date"),
        publication_number=raw.get("publication_number"),
        registration_number=raw.get("registration_number"),
        source=raw.get("source") or "KIPRIS Plus",
        source_url=raw.get("source_url"),
        technology_area_ids=sorted(set(raw.get("technology_area_ids") or [])),
    )


def load_technology_areas(path: Path = AREAS_PATH) -> dict[str, dict]:
    """표준 기술 분야 설정을 ID 기준으로 반환한다."""
    with open(path, encoding="utf-8") as file:
        entries = yaml.safe_load(file).get("technology_areas", [])
    return {entry["id"]: entry for entry in entries}


def build_chunks(patents: list[PatentDocument]) -> list[PatentChunk]:
    """특허 문서의 초록과 청구항을 검색용 청크로 변환한다."""
    chunks = []

    for patent in patents:
        if patent.abstract.strip():
            chunks.append(
                PatentChunk(
                    chunk_id=f"{patent.patent_id}_abstract_0",
                    patent_id=patent.patent_id,
                    section="abstract",
                    text=patent.abstract.strip(),
                    chunk_index=0,
                )
            )
        claims = patent.claim_items or structure_claims(
            patent.claims, patent.claim_version_id
        )
        if not claims and patent.claims.strip():
            chunks.append(
                PatentChunk(
                    chunk_id=f"{patent.patent_id}_claims_0",
                    patent_id=patent.patent_id,
                    section="claims",
                    text=patent.claims.strip(),
                    chunk_index=0,
                    claim_type="unclassified",
                    version_id=patent.claim_version_id,
                )
            )
        for index, claim in enumerate(claims):
            chunks.append(
                PatentChunk(
                    chunk_id=f"{patent.patent_id}_claim_{claim.claim_number}",
                    patent_id=patent.patent_id,
                    section="claims",
                    text=claim.text,
                    chunk_index=index,
                    claim_number=claim.claim_number,
                    claim_type=claim.claim_type,
                    depends_on=claim.depends_on,
                    version_id=claim.version_id or patent.claim_version_id,
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
        previous = merged.get(patent.patent_id)
        if previous:
            patent = patent.model_copy(
                update={
                    "technology_area_ids": sorted(
                        set(previous.technology_area_ids)
                        | set(patent.technology_area_ids)
                    )
                }
            )
        merged[patent.patent_id] = patent

    with open(path, "w", encoding="utf-8") as f:
        for patent in merged.values():
            f.write(patent.model_dump_json() + "\n")

    return path


def collect_to_jsonl(
    keyword: str | list[str],
    limit: int = 20,
    technology_area_id: str | None = None,
    include_claims: bool = False,
    claim_fetcher=fetch_patent_claims,
) -> tuple[int, int]:
    """KIPRIS 검색 결과와 확보된 청구항을 문헌 JSONL로 누적 저장한다."""
    raw_patents = collect_patents(keyword, limit=limit)

    for raw in raw_patents:
        if technology_area_id:
            raw["technology_area_ids"] = [technology_area_id]
        if include_claims:
            application_number = str(raw.get("application_number") or "").strip()
            if application_number:
                try:
                    raw["claim_items"] = claim_fetcher(application_number)
                except KiprisAPIError as exc:
                    print(f"청구항 미확보 ({application_number}): {exc}")

    documents = build_documents(raw_patents)
    save_documents(documents, path=OUTPUT_PATH)
    all_documents = [
        PatentDocument.model_validate_json(line)
        for line in OUTPUT_PATH.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    return len(documents), len(all_documents)


def build_patent_index(
    technology_area_id: str | None = None,
    docs_path: Path | None = None,
) -> tuple[int, int]:
    """저장된 특허 JSONL을 청크화해 Chroma에 증분 색인한다."""
    from src.retrieval.market_search import embed_texts
    from src.retrieval.patent_store import build_index, get_collection

    docs_path = docs_path or OUTPUT_PATH
    all_documents = [
        PatentDocument.model_validate_json(line)
        for line in docs_path.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
    if technology_area_id:
        all_documents = [
            patent
            for patent in all_documents
            if technology_area_id in patent.technology_area_ids
        ]

    all_chunks = build_chunks(all_documents)
    collection = get_collection()
    indexed_count = build_index(
        chunks=all_chunks,
        patents=all_documents,
        collection=collection,
        embed_fn=embed_texts,
    )
    return len(all_documents), indexed_count


def run_pipeline(
    keyword: str | list[str],
    limit: int = 20,
    technology_area_id: str | None = None,
    include_claims: bool = False,
    claim_fetcher=fetch_patent_claims,
) -> tuple[int, int, int]:
    """특허를 수집·저장한 뒤 로컬 Chroma에 증분 색인한다."""
    collected_count, total_count = collect_to_jsonl(
        keyword=keyword,
        limit=limit,
        technology_area_id=technology_area_id,
        include_claims=include_claims,
        claim_fetcher=claim_fetcher,
    )
    _, indexed_count = build_patent_index()

    return collected_count, total_count, indexed_count


def main() -> None:
    """KIPRIS 특허를 수집·전처리하고 JSONL 및 ChromaDB에 저장한다."""
    parser = argparse.ArgumentParser(description="KIPRIS 특허 수집 및 전처리")
    parser.add_argument(
        "--keyword",
        action="append",
        help="특허 검색 키워드 (여러 번 지정 가능; --field-id와 함께 사용 가능)",
    )
    parser.add_argument(
        "--field-id",
        choices=sorted(load_technology_areas()),
        help="configs/technology_areas.yaml의 기술 분야 ID",
    )
    parser.add_argument(
        "--include-claims",
        action="store_true",
        help="분야 설정의 검색어로 수집할 때 청구항 원문도 조회",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=20,
        help="키워드당 최대 수집 건수 (1~500)",
    )

    args = parser.parse_args()

    if args.field_id:
        area = load_technology_areas()[args.field_id]
        keywords = args.keyword or area["patent_keywords"]
    elif args.keyword:
        keywords = args.keyword
    else:
        parser.error("--keyword 또는 --field-id 중 하나가 필요합니다.")

    collected, total, indexed = run_pipeline(
        keyword=keywords,
        limit=args.limit,
        technology_area_id=args.field_id,
        include_claims=args.include_claims,
    )

    print(f"이번 수집: {collected}건")
    print(f"전체 누적 특허: {total}건")
    print(f"신규·변경 색인 청크: {indexed}개")
    print(f"저장 경로: {OUTPUT_PATH}")


if __name__ == "__main__":
    main()
