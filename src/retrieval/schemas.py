from typing import Literal
from pydantic import BaseModel, Field


# 공통 스키마
class SearchDocument(BaseModel):
    chunk_id: str = Field(min_length=1)
    source_id: str = Field(min_length=1)
    source_type: Literal["patent", "market"]
    title: str
    content: str = Field(min_length=1)
    metadata: dict = Field(default_factory=dict)


class RetrievalResult(BaseModel):
    document: SearchDocument

    dense_score: float | None = None
    bm25_score: float | None = None
    rrf_score: float | None = None
    rerank_score: float | None = None

    dense_rank: int | None = Field(default=None, ge=1)
    bm25_rank: int | None = Field(default=None, ge=1)
    final_rank: int | None = Field(default=None, ge=1)


# 특허 검색 스키마
class PatentSearchQuery(BaseModel):
    """하나의 기술 요소에 대한 특허 검색어."""

    technical_element: str = Field(min_length=1)
    korean_queries: list[str] = Field(min_length=1)
    english_queries: list[str] = Field(min_length=1)


class PatentQueryPlan(BaseModel):
    """기술 요소별 특허 검색어 목록."""

    queries: list[PatentSearchQuery] = Field(min_length=1)
