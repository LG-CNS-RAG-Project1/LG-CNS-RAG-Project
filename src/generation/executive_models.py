"""Data contracts for the integrated executive review."""

from typing import Literal

from pydantic import BaseModel, Field, model_validator


class IntegratedFinding(BaseModel):
    """특허·시장 근거를 연결한 통합 판단 한 건."""

    label: str
    judgment: str
    business_implication: str
    evidence_ids: list[str] = Field(default_factory=list)
    kind: Literal["fact", "interpretation", "hypothesis", "unknown"]


class ApprovalGate(BaseModel):
    """결정 전에 담당자와 증거를 확인해야 하는 승인 조건."""

    question: str
    owner: str
    proof_needed: str
    consequence: str
    evidence_ids: list[str] = Field(default_factory=list)


class DomainEvidenceSummary(BaseModel):
    """영역별 원본 보고서를 공통 형식으로 보여주는 읽기 전용 요약."""

    domain: Literal["patent", "market"]
    status: Literal["completed", "partial", "no_results", "error", "skipped", "timeout"]
    finding: str
    evidence_ids: list[str] = Field(default_factory=list)
    evidence_scope: str
    evidence_count: int = Field(default=0, ge=0)
    data_as_of: str | None = None
    limitations: list[str] = Field(default_factory=list)
    next_check: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_evidence_ids(self):
        """영역별 근거 ID의 접두부와 중복 여부를 검사한다."""
        prefix = "P:" if self.domain == "patent" else "M:"
        if any(not value.startswith(prefix) for value in self.evidence_ids):
            raise ValueError(f"{self.domain} summary has a foreign evidence ID")
        if len(self.evidence_ids) != len(set(self.evidence_ids)):
            raise ValueError("Domain evidence IDs must be unique")
        return self


class ExecutiveReview(BaseModel):
    """양쪽 조사 상태·근거·제한·다음 행동을 묶은 경영진 요약."""

    recommendation: str
    scope: str
    confidence: str
    decision_summary: str
    domain_summaries: list[DomainEvidenceSummary] = Field(
        default_factory=list, max_length=2
    )
    integrated_findings: list[IntegratedFinding] = Field(default_factory=list)
    approval_gates: list[ApprovalGate] = Field(default_factory=list, max_length=3)
    next_actions: list[str] = Field(default_factory=list, max_length=3)
    limitations: list[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_domain_summaries(self):
        """특허·시장 요약이 각각 최대 한 건인지 확인한다."""
        domains = [summary.domain for summary in self.domain_summaries]
        if len(domains) != len(set(domains)):
            raise ValueError("Executive review has duplicate domain summaries")
        return self
