import pytest
from pydantic import ValidationError

from src.schemas import (
    PatentChunk,
    PatentDocument,
    MarketChunk,
    MarketDocument,
)
from src.retrieval.schemas import SearchDocument, RetrievalResult
from src.retrieval.adapters import (
    patent_to_search_document,
    market_to_search_document,
)


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


# 6. 시장 청크 → 공통 검색 문서 변환
def test_market_to_search_document():
    market = MarketDocument(
        source_id="M001",
        source_type="news",
        title="스마트팩토리 도입 확대",
        publisher="테스트 언론사",
        text="중소기업의 스마트팩토리 도입이 증가하고 있다.",
        published_at=20261020,
        collected_at=20261021,
        reliability="medium",
        evidence_nature="indirect_demand",
    )

    chunk = MarketChunk(
        chunk_id="M001#0",
        source_id="M001",
        text=market.text,
        chunk_index=0,
        section="본문",
    )

    result = market_to_search_document(chunk, market)

    assert isinstance(result, SearchDocument)
    assert result.chunk_id == "M001#0"
    assert result.source_id == "M001"
    assert result.source_type == "market"
    assert result.title == market.title
    assert result.content == chunk.text
    assert result.metadata["source_type"] == "news"
    assert result.metadata["publisher"] == "테스트 언론사"
    assert result.metadata["published_at"] == 20261020
    assert result.metadata["section"] == "본문"
    assert result.metadata["reliability"] == "medium"


# 7. 시장 문서와 청크의 출처 ID 불일치 검증
def test_market_source_id_mismatch():
    market = MarketDocument(
        source_id="M001",
        source_type="news",
        title="스마트팩토리 도입 확대",
        publisher="테스트 언론사",
        text="스마트팩토리 관련 시장 자료",
        published_at=20261020,
        collected_at=20261021,
        reliability="medium",
        evidence_nature="indirect_demand",
    )

    chunk = MarketChunk(
        chunk_id="M002#0",
        source_id="M002",
        text="다른 시장 자료의 청크",
        chunk_index=0,
    )

    with pytest.raises(ValueError, match="Market source ID mismatch"):
        market_to_search_document(chunk, market)
