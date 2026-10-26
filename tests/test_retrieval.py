import pytest
from pydantic import ValidationError

from src.schemas import PatentChunk, PatentDocument
from src.retrieval.schemas import SearchDocument, RetrievalResult
from src.retrieval.adapters import patent_to_search_document


# 1. 공통 검색 문서 생성
def test_search_document():
    document = SearchDocument(
        chunk_id="P001#0",
        source_id="P001",
        source_type="patent",
        title="설비 이상 감지 시스템",
        content="센서 데이터를 분석하여 이상을 감지한다.",
        metadata={"section": "abstract"},
    )

    assert document.source_id == "P001"
    assert document.source_type == "patent"


# 2. 잘못된 출처 유형 검증
def test_invalid_source_type():
    with pytest.raises(ValidationError):
        SearchDocument(
            chunk_id="P001#0",
            source_id="P001",
            source_type="unknown",
            title="테스트",
            content="테스트 내용",
        )


# 3. 검색 결과 및 점수 검증
def test_retrieval_result():
    document = SearchDocument(
        chunk_id="P001#0",
        source_id="P001",
        source_type="patent",
        title="설비 이상 감지 시스템",
        content="센서 데이터를 분석하여 이상을 감지한다.",
    )

    result = RetrievalResult(
        document=document,
        dense_score=0.85,
        dense_rank=1,
    )

    assert result.document.chunk_id == "P001#0"
    assert result.dense_score == 0.85
    assert result.bm25_score is None
    assert result.dense_rank == 1


# 4. 특허 청크 → 공통 검색 문서 변환
def test_patent_to_search_document():
    patent = PatentDocument(
        patent_id="P001",
        title="설비 이상 감지 시스템",
        abstract="설비 이상을 감지하는 기술",
        application_number="10-2026-000001",
    )

    chunk = PatentChunk(
        chunk_id="P001#0",
        patent_id="P001",
        section="abstract",
        text="센서 데이터를 분석하여 이상을 감지한다.",
        chunk_index=0,
    )

    result = patent_to_search_document(chunk, patent)

    assert isinstance(result, SearchDocument)
    assert result.source_id == "P001"
    assert result.source_type == "patent"
    assert result.content == chunk.text
    assert result.metadata["application_number"] == "10-2026-000001"
    assert result.metadata["section"] == "abstract"


# 5. 특허 ID 불일치 검증
def test_patent_id_mismatch():
    patent = PatentDocument(
        patent_id="P001",
        title="설비 이상 감지 시스템",
        abstract="설비 이상을 감지하는 기술",
    )

    chunk = PatentChunk(
        chunk_id="P002#0",
        patent_id="P002",
        section="abstract",
        text="센서 데이터를 분석한다.",
        chunk_index=0,
    )

    with pytest.raises(ValueError, match="Patent ID mismatch"):
        patent_to_search_document(chunk, patent)
