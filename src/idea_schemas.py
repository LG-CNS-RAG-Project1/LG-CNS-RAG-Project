"""Idea input and draft contracts shared by patent and market analysis."""

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
    current_alternative: str = ""
    target_segment: str = ""
    value_hypotheses: list[str] = Field(default_factory=list)
    field_sources: dict[str, str] = Field(default_factory=dict)


IdeaField = Literal["problem", "technology", "customers", "difference", "revenue"]
FieldSource = Literal[
    "extracted",  # 입력 문장에서 LLM이 추출
    "user_answer",  # 재질문에 사용자가 직접 답변
    "ai_hypothesis",  # AI가 분석용 가설로 제안
    "unknown",  # 사용자가 모름으로 답했거나 재질문 상한까지 비어 있음
]

IDEA_FIELDS: list[IdeaField] = [
    "problem",
    "technology",
    "customers",
    "difference",
    "revenue",
]


# 1-1. 구조화 중인 아이디어 (빈 항목 재질문 단계)
class IdeaDraft(BaseModel):
    original_text: str = Field(min_length=1)
    title: str = ""
    problem: str = ""
    technology: str = ""
    customers: str = ""
    difference: str = ""
    revenue: str = ""

    field_sources: dict[str, FieldSource] = Field(default_factory=dict)
    current_alternative: str = ""
    target_segment: str = ""
    technical_components: list[str] = Field(default_factory=list)
    value_hypotheses: list[str] = Field(default_factory=list)
    unknowns: list[str] = Field(default_factory=list)
    status: Literal["needs_input", "complete", "rejected"] = "needs_input"
    missing_fields: list[IdeaField] = Field(default_factory=list)
    questions: dict[IdeaField, str] = Field(default_factory=dict)
    rounds: int = Field(default=0, ge=0)  # 재질문에 답한 횟수

    # 입력 검사 결과: off_topic(주제 이탈), unsafe(프롬프트 조작·유해 목적)이면 rejected
    input_status: Literal["ok", "off_topic", "unsafe"] = "ok"
    rejection_reason: str | None = None  # 사용자에게 보여 줄 거절 안내

    @model_validator(mode="after")
    def validate_draft(self):
        if self.status == "complete" and self.missing_fields:
            raise ValueError("complete draft must not have missing fields")
        if self.status == "needs_input" and not self.missing_fields:
            raise ValueError("needs_input draft requires missing fields")
        if (self.status == "rejected") != (self.input_status != "ok"):
            raise ValueError("rejected status must match a non-ok input_status")
        if self.status == "rejected" and not self.rejection_reason:
            raise ValueError("rejected draft requires rejection_reason")
        return self

    @property
    def unknown_fields(self) -> list[IdeaField]:
        """모름으로 확정된 항목. 해당 항목에 기대는 시장 차원은 미확인으로 판정한다."""
        return [f for f in IDEA_FIELDS if self.field_sources.get(f) == "unknown"]

    def to_structured_idea(self) -> StructuredIdea:
        """완성된 초안을 특허·시장 공통 입력으로 변환한다. 모름 항목은 빈 문자열로 남는다."""
        if self.status != "complete":
            raise ValueError(f"idea draft is incomplete: {self.missing_fields}")
        required = ["title", *IDEA_FIELDS]
        missing = [field for field in required if not str(getattr(self, field)).strip()]
        if missing:
            raise ValueError("분석 필수 항목이 비어 있습니다: " + ", ".join(missing))
        return StructuredIdea(
            title=self.title,
            **{field: getattr(self, field) for field in IDEA_FIELDS},
            current_alternative=self.current_alternative,
            target_segment=self.target_segment,
            technical_components=self.technical_components,
            value_hypotheses=self.value_hypotheses,
            field_sources=self.field_sources,
        )
