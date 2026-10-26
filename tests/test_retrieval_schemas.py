import pytest
from pydantic import ValidationError

from src.retrieval.schemas import SearchDocument
from src.retrieval.schemas import SearchDocument, RetrievalResult


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


def test_invalid_source_type():
    with pytest.raises(ValidationError):
        SearchDocument(
            chunk_id="P001#0",
            source_id="P001",
            source_type="unknown",
            title="테스트",
            content="테스트 내용",
        )


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
