from src.ingestion.patent_processor import load_technology_areas
from src.retrieval.patent_search import search_patents
from src.retrieval.patent_store import build_index, get_collection
from src.schemas import PatentChunk, PatentDocument


def test_taxonomy_matches_requested_technology_areas():
    areas = load_technology_areas()

    assert len(areas) == 8
    assert areas["SF-02"]["name"] == "AI 비전 품질검사"
    assert areas["SF-02"]["technologies"] == ["머신비전", "딥러닝 결함 탐지"]
    assert areas["SF-05"]["name"] == "지능형 공정제어"
    assert areas["SF-05"]["technologies"] == ["공정 최적화", "자동제어"]


def test_patent_search_can_filter_preindexed_technology_area(tmp_path):
    collection = get_collection(chroma_dir=tmp_path / "chroma")
    patents = [
        PatentDocument(
            patent_id="P-VISION",
            title="AI 비전 결함검사",
            abstract="영상 딥러닝으로 표면 불량을 검출한다.",
            technology_area_ids=["SF-02"],
        ),
        PatentDocument(
            patent_id="P-CONTROL",
            title="지능형 공정제어",
            abstract="센서 피드백으로 공정 조건을 최적화한다.",
            technology_area_ids=["SF-05"],
        ),
    ]
    chunks = [
        PatentChunk(
            chunk_id=f"{patent.patent_id}_abstract_0",
            patent_id=patent.patent_id,
            section="abstract",
            text=patent.abstract,
            chunk_index=0,
        )
        for patent in patents
    ]

    def fake_embed(texts):
        return [[0.1, 0.2, 0.3] for _ in texts]

    build_index(chunks, patents, collection, fake_embed)
    results = search_patents(
        "제조 품질검사 결함",
        collection=collection,
        embed_fn=fake_embed,
        retrieval_mode="bm25",
        technology_area_id="SF-02",
    )

    assert results
    assert {result.document.source_id for result in results} == {"P-VISION"}
    assert collection.get(where={"area_SF-02": True}, include=["metadatas"])["ids"] == [
        "P-VISION_abstract_0"
    ]


def test_metadata_only_index_update_does_not_reembed_document(tmp_path):
    collection = get_collection(chroma_dir=tmp_path / "chroma")
    patent = PatentDocument(
        patent_id="P001", title="검사 장치", abstract="영상 결함을 검출한다."
    )
    chunk = PatentChunk(
        chunk_id="P001_abstract_0",
        patent_id="P001",
        section="abstract",
        text=patent.abstract,
        chunk_index=0,
    )
    embedded_texts = []

    def fake_embed(texts):
        embedded_texts.extend(texts)
        return [[0.1, 0.2, 0.3] for _ in texts]

    build_index([chunk], [patent], collection, fake_embed)
    tagged_patent = patent.model_copy(update={"technology_area_ids": ["SF-02"]})
    changed = build_index([chunk], [tagged_patent], collection, fake_embed)

    assert changed == 1
    assert embedded_texts == [patent.abstract]
    assert collection.get(where={"area_SF-02": True}, include=["metadatas"])["ids"] == [
        chunk.chunk_id
    ]
