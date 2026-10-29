from src.schemas import PatentChunk, PatentDocument
from src.retrieval.schemas import SearchDocument


def patent_to_search_document(
    chunk: PatentChunk,
    patent: PatentDocument,
) -> SearchDocument:
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
            "source_url": patent.source_url,
            "collected_at": patent.collected_at,
        },
    )


from src.schemas import MarketChunk, MarketDocument


def market_to_search_document(
    chunk: MarketChunk,
    market: MarketDocument,
) -> SearchDocument:
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
