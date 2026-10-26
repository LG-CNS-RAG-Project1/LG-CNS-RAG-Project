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
            "application_number": patent.application_number,
            "publication_number": patent.publication_number,
            "source_url": patent.source_url,
        },
    )
