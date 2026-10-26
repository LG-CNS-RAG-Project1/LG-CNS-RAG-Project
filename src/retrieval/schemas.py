from typing import Literal
from pydantic import BaseModel, Field


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
