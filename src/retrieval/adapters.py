"""도메인 문서와 청크를 공통 검색 문서로 변환한다."""

from src.schemas import PatentChunk, PatentDocument
from src.retrieval.schemas import SearchDocument


def patent_to_search_document(
    chunk: PatentChunk,
    patent: PatentDocument,
) -> SearchDocument:
    """특허 청크 내용에 원문 추적용 번호·분류 메타데이터를 붙인다."""
    if chunk.patent_id != patent.patent_id:
        raise ValueError("Patent ID mismatch")

    return SearchDocument(
        chunk_id=chunk.chunk_id,
        source_id=patent.patent_id,
        source_type="patent",
        title=patent.title,
        content=chunk.text,
        metadata={
            "section": chunk.section,
            "chunk_index": chunk.chunk_index,
            "claim_number": chunk.claim_number,
            "claim_type": chunk.claim_type,
            "depends_on": chunk.depends_on,
            "version_id": chunk.version_id or patent.claim_version_id,
            "application_number": patent.application_number,
            "publication_number": patent.publication_number,
            "application_date": patent.application_date,
            "publication_date": patent.publication_date,
            "applicant": patent.applicant,
            "ipc_codes": patent.ipc_codes,
            "cpc_codes": patent.cpc_codes,
            "source_url": patent.source_url,
            "representative_drawing_url": patent.representative_drawing_url,
            "representative_thumbnail_url": patent.representative_thumbnail_url,
            "representative_drawing_caption": patent.representative_drawing_caption,
            "collected_at": patent.collected_at,
        },
    )


from src.schemas import MarketChunk, MarketDocument


def market_to_search_document(
    chunk: MarketChunk,
    market: MarketDocument,
) -> SearchDocument:
    """시장 청크를 출처·발행일·근거 성격이 있는 검색 문서로 바꾼다."""
    if chunk.source_id != market.source_id:
        raise ValueError("Market source ID mismatch")

    return SearchDocument(
        chunk_id=chunk.chunk_id,
        source_id=market.source_id,
        source_type="market",
        title=market.title,
        content=chunk.text,
        metadata={
            "section": chunk.section,
            "chunk_index": chunk.chunk_index,
            "source_type": market.source_type,
            "published_at": market.published_at,
            "url": market.url,
            "publisher": market.publisher,
            "reliability": market.reliability,
            "evidence_nature": market.evidence_nature,
            "dup_group": market.dup_group,
        },
    )
