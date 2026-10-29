### PR충돌 때문에 따로 빼둠 추후에 test_patent.py에 병합예정

from src.retrieval.patent_search import bi_encoder_reranker, search_patents
from src.retrieval.schemas import SearchDocument
from src.retrieval.patent_store import build_index, get_collection
from src.schemas import PatentChunk, PatentDocument


def test_patent_search_supports_bm25_and_hybrid(tmp_path):
    collection = get_collection(chroma_dir=tmp_path / "chroma")
    patents = [
        PatentDocument(
            patent_id="P001", title="협동로봇 비전 검사", abstract="카메라 결함 검출"
        ),
        PatentDocument(
            patent_id="P002", title="협동로봇 제어", abstract="관절 제어 시스템"
        ),
    ]
    chunks = [
        PatentChunk(
            chunk_id=f"{patent.patent_id}#abstract#0",
            patent_id=patent.patent_id,
            section="abstract",
            text=f"{patent.title} {patent.abstract}",
            chunk_index=0,
        )
        for patent in patents
    ]

    def fake_embed(texts):
        return [[float("P001" in text), float("P002" in text), 0.1] for text in texts]

    build_index(chunks, patents, collection, fake_embed)
    bm25 = search_patents(
        "비전 결함 검출", collection, fake_embed, retrieval_mode="bm25"
    )
    hybrid = search_patents(
        "비전 결함 검출", collection, fake_embed, retrieval_mode="hybrid"
    )

    assert bm25[0].document.source_id == "P001"
    assert hybrid[0].rrf_score is not None


def test_bi_encoder_reranker_sorts_by_query_document_cosine_similarity():
    vectors = {
        "질의": [1.0, 0.0],
        "정답\n설명": [0.9, 0.1],
        "무관\n설명": [0.0, 1.0],
    }
    calls = []

    def embed(texts):
        calls.extend(texts)
        return [vectors[text] for text in texts]

    score = bi_encoder_reranker(embed)
    documents = [
        SearchDocument(
            chunk_id="1",
            source_id="P1",
            source_type="patent",
            title="정답",
            content="설명",
        ),
        SearchDocument(
            chunk_id="2",
            source_id="P2",
            source_type="patent",
            title="무관",
            content="설명",
        ),
    ]

    scores = score("질의", documents)

    assert scores[0] > scores[1]
    assert calls == ["질의", "정답\n설명", "무관\n설명"]
