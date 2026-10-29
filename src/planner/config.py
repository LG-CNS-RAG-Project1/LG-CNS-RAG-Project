"""사업기획 근거 비교 프로필과 질문 은행을 읽고 검증한다.

프로필(`configs/planner/{area}.yaml`)은 구매 기준 사전·초기 질의·범위 규칙·가정 템플릿·예산을,
질문 은행(`configs/planner/question_bank.json`)은 질문 ID·템플릿·필수 필드·분기를 정의한다.
모델은 gpt-4o-mini만 허용한다.
"""

import json
import re
from pathlib import Path
from typing import Literal

import yaml
from pydantic import BaseModel, Field, model_validator

from src.planner.store import canonical_json, sha256_hex

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT_DIR / "configs" / "planner"
QUESTION_BANK_PATH = CONFIG_DIR / "question_bank.json"
ALLOWED_MODEL = "gpt-4o-mini"
ENTITY_SLOTS = {"supplier", "adopter", "actor", "channel_actor", "event"}
_SLOT_RE = re.compile(r"\{([a-z_]+)\}")


class Question(BaseModel):
    id: str
    decision: str
    question: str
    parent_id: str | None = None
    next_question: str | None = None
    required_fields: list[str]
    query_template: str = ""
    news_answerability: Literal["partial", "conditional", "user_input", "mixed"]
    acceptance_rule: str = ""
    missing_or_conflict_action: str = ""
    decision_effect: str = ""


class QuestionBank(BaseModel):
    version: str
    stop_reasons: list[str]
    questions: list[Question]

    @model_validator(mode="after")
    def check_links(self):
        ids = [q.id for q in self.questions]
        if len(ids) != len(set(ids)):
            raise ValueError("question id 중복")
        known = set(ids)
        for q in self.questions:
            for ref in (q.parent_id, q.next_question):
                if ref and ref not in known:
                    raise ValueError(f"{q.id}: 알 수 없는 연결 질문 {ref}")
        return self

    def by_id(self) -> dict[str, Question]:
        return {q.id: q for q in self.questions}


class Budget(BaseModel):
    max_articles: int = Field(gt=0, le=80)
    initial_articles: int = Field(gt=0)
    followup_batch: int = Field(ge=0)
    max_followup_rounds: int = Field(ge=0)
    max_api_requests: int = Field(gt=0)
    display_per_request: int = Field(gt=0, le=100)
    max_pages_per_query: int = Field(gt=0, le=10)
    max_candidates: int = Field(gt=0)
    api_retries: int = Field(ge=0, le=1)
    max_body_fetches: int = Field(ge=0)
    llm_retry_per_article: int = Field(ge=0, le=1)
    llm_retry_total: int = Field(ge=0)
    llm_input_chars: int = Field(gt=0)
    queries_per_question: int = Field(gt=0)
    date_from: int
    sort: Literal["sim", "date"] = "sim"

    @model_validator(mode="after")
    def check_total(self):
        if (
            self.initial_articles + self.followup_batch * self.max_followup_rounds
            > self.max_articles
        ):
            raise ValueError("초기 + 후속 배분이 고유 기사 총량을 넘는다")
        return self


class InitialQuery(BaseModel):
    question_id: str
    query: str


class AllocationGroup(BaseModel):
    group: str
    label: str
    articles: int = Field(gt=0)
    queries: list[InitialQuery] = Field(min_length=1)


class Scope(BaseModel):
    include_any: list[str] = Field(min_length=1)
    vision_terms: list[str] = Field(default_factory=list)
    exclude_any: list[str] = Field(default_factory=list)
    industry_direct: list[str] = Field(default_factory=list)


class Criterion(BaseModel):
    id: str
    label: str
    decision_id: str
    strong: list[str] = Field(min_length=1)
    weak: list[str] = Field(default_factory=list)
    next_question: dict[Literal["explicit", "partial", "unknown", "conflicting"], str]


class AssumptionTemplate(BaseModel):
    id: str
    label: str
    source_field: str
    evidence: Literal[
        "our_claim_competition",
        "criterion_claims",
        "channel_edges",
        "external_adoption",
        "price_inputs",
    ]
    criterion_id: str = ""
    support_terms: list[str] = Field(default_factory=list)
    affected_choice: str
    options: list[str] = Field(default_factory=list)
    next_questions: list[str] = Field(min_length=1)


class BodyFetch(BaseModel):
    enabled: bool = True
    deny_domains: list[str] = Field(default_factory=list)


class Profile(BaseModel):
    area_id: str
    version: str
    model: str
    budget: Budget
    initial_allocation: list[AllocationGroup]
    slots: dict[str, list[str]]
    scope: Scope
    offering_terms: list[str]
    criteria: list[Criterion] = Field(min_length=1)
    extraction_focus: list[str] = Field(default_factory=list)
    assumptions: list[AssumptionTemplate]
    question_checks: dict[str, str]
    company_input: list[str] = Field(default_factory=list)
    customer_validation: list[str] = Field(default_factory=list)
    body_fetch: BodyFetch = Field(default_factory=BodyFetch)

    @model_validator(mode="after")
    def check_profile(self):
        if self.model != ALLOWED_MODEL:
            raise ValueError(f"모델은 {ALLOWED_MODEL}만 허용한다: {self.model}")
        total = sum(group.articles for group in self.initial_allocation)
        if total != self.budget.initial_articles:
            raise ValueError(
                f"초기 배분 합계 {total} ≠ initial_articles {self.budget.initial_articles}"
            )
        ids = [c.id for c in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("criterion id 중복")
        for assumption in self.assumptions:
            if assumption.evidence == "criterion_claims" and (
                assumption.criterion_id not in ids
            ):
                raise ValueError(
                    f"{assumption.id}: 알 수 없는 기준 {assumption.criterion_id}"
                )
        return self

    def criterion(self, criterion_id: str) -> Criterion:
        return next(c for c in self.criteria if c.id == criterion_id)


def template_slots(template: str) -> set[str]:
    return set(_SLOT_RE.findall(template or ""))


def load_question_bank(path: Path = QUESTION_BANK_PATH) -> QuestionBank:
    return QuestionBank.model_validate(json.loads(Path(path).read_text("utf-8")))


def validate_against_bank(profile: Profile, bank: QuestionBank) -> None:
    """프로필의 질문 ID와 후속 템플릿 슬롯이 질문 은행·슬롯 정의와 맞는지 검사한다."""
    questions = bank.by_id()
    refs = [q.question_id for g in profile.initial_allocation for q in g.queries]
    refs += list(profile.question_checks) + profile.company_input
    refs += profile.customer_validation
    refs += [qid for a in profile.assumptions for qid in a.next_questions]
    refs += [qid for c in profile.criteria for qid in c.next_question.values()]
    unknown = sorted({ref for ref in refs if ref not in questions})
    if unknown:
        raise ValueError(f"질문 은행에 없는 ID: {unknown}")
    for qid in profile.question_checks:
        missing = template_slots(questions[qid].query_template) - ENTITY_SLOTS
        missing -= set(profile.slots)
        if missing:
            raise ValueError(f"{qid} 템플릿 슬롯 값 없음: {sorted(missing)}")


def profile_path(area_id: str) -> Path:
    return CONFIG_DIR / f"{area_id}.yaml"


def available_profiles(config_dir: Path = CONFIG_DIR) -> list[str]:
    return sorted(p.stem for p in Path(config_dir).glob("*.yaml"))


def load_profile(area_id: str, bank: QuestionBank | None = None) -> Profile:
    """분야 프로필을 읽고 질문 은행과 대조한다. 파일이 없으면 FileNotFoundError."""
    raw = yaml.safe_load(profile_path(area_id).read_text("utf-8"))
    profile = Profile.model_validate(raw)
    if profile.area_id != area_id:
        raise ValueError(f"프로필 area_id 불일치: {profile.area_id} ≠ {area_id}")
    validate_against_bank(profile, bank or load_question_bank())
    return profile


def profile_hash(profile: Profile) -> str:
    return sha256_hex(canonical_json(profile))
