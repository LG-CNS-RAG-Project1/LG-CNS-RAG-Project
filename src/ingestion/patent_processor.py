"""KIPRIS 특허 검색 결과를 내부 문서 및 검색 청크로 변환한다."""

from src.schemas import PatentChunk, PatentDocument


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
