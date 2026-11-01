import pytest

from src.retrieval import patent_store
from src.retrieval.patent_store import build_index, get_collection
from src.schemas import PatentChunk, PatentDocument


def make_records(count):
    patents = [
        PatentDocument(
            patent_id=f"P{index}",
            title=f"Patent {index}",
            abstract=f"Abstract text {index}",
        )
        for index in range(count)
    ]
    chunks = [
        PatentChunk(
            chunk_id=f"{patent.patent_id}#abstract#0",
            patent_id=patent.patent_id,
            section="abstract",
            text=patent.abstract,
            chunk_index=0,
        )
        for patent in patents
    ]
    return chunks, patents


def test_patent_index_saves_successful_batches_and_retry_skips_them(
    tmp_path, monkeypatch
):
    monkeypatch.setattr(patent_store, "EMBED_BATCH_SIZE", 2)
    collection = get_collection(chroma_dir=tmp_path / "chroma")
    chunks, patents = make_records(5)
    calls = []

    def fail_on_second_batch(texts):
        calls.append(list(texts))
        if len(calls) == 2:
            raise RuntimeError("embedding failed")
        return [[1.0, 0.0] for _ in texts]

    with pytest.raises(RuntimeError, match="embedding failed"):
        build_index(chunks, patents, collection, fail_on_second_batch)

    assert collection.count() == 2
    saved_ids = set(collection.get(include=[])["ids"])
    assert saved_ids == {"P0#abstract#0", "P1#abstract#0"}

    def retry_embed(texts):
        calls.append(list(texts))
        return [[1.0, 0.0] for _ in texts]

    assert build_index(chunks, patents, collection, retry_embed) == 3
    assert collection.count() == 5
    assert calls[2:] == [
        ["Abstract text 2", "Abstract text 3"],
        ["Abstract text 4"],
    ]
