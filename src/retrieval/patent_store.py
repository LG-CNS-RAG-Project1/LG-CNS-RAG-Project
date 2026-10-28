"""특허 문서를 ChromaDB에 저장하고 관리한다."""

from pathlib import Path

from chromadb.api import ClientAPI
from src.retrieval.chroma_client import connect_chroma

from typing import Callable
from src.schemas import PatentChunk, PatentDocument
from src.retrieval.adapters import patent_to_search_document

ROOT_DIR = Path(__file__).resolve().parents[2]
CHROMA_DIR = ROOT_DIR / "data" / "patents" / "chroma"
COLLECTION_NAME = "patents"


def get_collection(
    chroma_dir: Path = CHROMA_DIR,
    name: str = COLLECTION_NAME,
    client: ClientAPI | None = None,
):
    """cosine 거리를 사용하는 특허 컬렉션을 반환한다."""

    if client is None:
        client = connect_chroma(chroma_dir)

    return client.get_or_create_collection(
        name=name,
        metadata={"hnsw:space": "cosine"},
        embedding_function=None,
    )


EmbedFn = Callable[[list[str]], list[list[float]]]


def to_chroma_record(
    chunk: PatentChunk,
    patent: PatentDocument,
) -> tuple[str, str, dict]:
    """특허 청크를 ChromaDB 레코드로 변환한다."""

    document = patent_to_search_document(chunk, patent)

    metadata = {
        "source_id": document.source_id,
        "source_type": document.source_type,
        "title": document.title,
        **document.metadata,
    }
    metadata.update({f"area_{area_id}": True for area_id in patent.technology_area_ids})

    # ChromaDB 메타데이터에는 None을 저장하지 않는다.
    metadata = {
        key: (
            ",".join(str(value) for value in value)
            if isinstance(value, list)
            else value
        )
        for key, value in metadata.items()
        if value is not None
    }

    return document.chunk_id, document.content, metadata


def build_index(chunks, patents, collection, embed_fn):
    """신규·변경 청크만 ChromaDB에 색인한다."""
    patent_map = {p.patent_id: p for p in patents}

    records = [to_chroma_record(chunk, patent_map[chunk.patent_id]) for chunk in chunks]

    if not records:
        return 0

    ids = [record[0] for record in records]

    existing = collection.get(
        ids=ids,
        include=["documents", "metadatas"],
    )

    existing_map = {
        chunk_id: (document, metadata)
        for chunk_id, document, metadata in zip(
            existing["ids"],
            existing["documents"],
            existing["metadatas"],
        )
    }

    changed_records = [
        (chunk_id, content, metadata)
        for chunk_id, content, metadata in records
        if chunk_id not in existing_map or existing_map[chunk_id] != (content, metadata)
    ]

    if not changed_records:
        return 0

    metadata_only_records = [
        (chunk_id, metadata)
        for chunk_id, content, metadata in changed_records
        if chunk_id in existing_map and existing_map[chunk_id][0] == content
    ]
    metadata_only_ids = {chunk_id for chunk_id, _ in metadata_only_records}
    content_records = [
        record for record in changed_records if record[0] not in metadata_only_ids
    ]

    if metadata_only_records:
        collection.update(
            ids=[record[0] for record in metadata_only_records],
            metadatas=[record[1] for record in metadata_only_records],
        )

    if content_records:
        collection.upsert(
            ids=[record[0] for record in content_records],
            documents=[record[1] for record in content_records],
            metadatas=[record[2] for record in content_records],
            embeddings=embed_fn([record[1] for record in content_records]),
        )

    return len(changed_records)
