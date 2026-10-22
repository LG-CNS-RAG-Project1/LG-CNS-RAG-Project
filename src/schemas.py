from typing import Literal
from pydantic import BaseModel, Field, model_validator


# 1. 사용자 아이디어
class StructuredIdea(BaseModel):
    title: str
    problem: str
    technology: str
    customers: str = ""
    difference: str = ""
    revenue: str = ""
    technical_components: list[str] = Field(default_factory=list)


# 2. 특허 검색 요청
class PatentSearchRequest(BaseModel):
    idea: StructuredIdea
    top_k: int = Field(default=5, ge=1, le=5)


# 3. 정제된 특허 문서
class PatentDocument(BaseModel):
    patent_id: str
    title: str
    abstract: str
    claims: str = ""

    application_number: str | None = None
    publication_number: str | None = None
    registration_number: str | None = None

    applicant: str | None = None
    application_date: str | None = None

    source: str = "KIPRIS Plus"
    source_url: str | None = None


# 4. 임베딩 대상 청크
class PatentChunk(BaseModel):
    chunk_id: str
    patent_id: str
    section: Literal["abstract", "claims"]
    text: str = Field(min_length=1)
    chunk_index: int = Field(ge=0)


# 5. 검색 근거
class PatentEvidence(BaseModel):
    citation_id: int = Field(ge=1)
    patent_id: str
    title: str

    section: Literal["abstract", "claims"]
    quote: str = Field(min_length=1)

    similarity: float | None = Field(default=None, ge=0, le=1)
    source_url: str | None = None


# 6. 기술 비교 결과
class PatentComparison(BaseModel):
    citation_id: int = Field(ge=1)
    similarity: str
    difference: str
    uncertainty: str


# 7. 최종 특허 RAG 결과
class PatentReport(BaseModel):
    status: Literal["completed", "no_results", "error"]

    evidence: list[PatentEvidence] = Field(default_factory=list)
    comparisons: list[PatentComparison] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)

    search_scope: str
    error_message: str | None = None

    @model_validator(mode="after")
    def validate_citations(self):
        ids = [e.citation_id for e in self.evidence]

        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate citation IDs")

        for comparison in self.comparisons:
            if comparison.citation_id not in ids:
                raise ValueError("Comparison references unknown citation")

        if len(self.evidence) > 5:
            raise ValueError("Maximum 5 patent evidences")

        return self
