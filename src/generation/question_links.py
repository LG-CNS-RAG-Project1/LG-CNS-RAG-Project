"""검토 질문별 시장·특허 근거 연결과 검증을 담당한다."""

import json
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field, field_validator
from src.llm_client import chat_model, get_openai_client
from src.schemas import MarketReport, PatentReport

ROOT_DIR = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT_DIR / "prompts" / "report_generation.md"
MODEL = "gpt-4o-mini"
CRITERIA = [
    "사용 맥락",
    "해결 과제",
    "기술 구성",
    "요구 성능",
    "도입 제약",
    "근거 범위",
]
LINK_ATTEMPTS = 2
HOLD_SUMMARY = "질문별 연결 결과를 생성하지 못해 판단을 보류합니다."
BOTH_SIDES_SUMMARY = "시장·특허 양쪽 근거가 연결되지 않아 통합 판단을 보류합니다."


class CriterionLink(BaseModel):
    criterion: str
    assessment: str = "미확인"
    citation_ids: list[str] = Field(default_factory=list)
    next_check: str = ""

    @field_validator("assessment", "next_check", mode="before")
    @classmethod
    def _null_text(cls, value):
        """LLM이 빈 값을 null로 돌려줘도 연결 전체를 버리지 않는다."""
        return "" if value is None else value

    @field_validator("citation_ids", mode="before")
    @classmethod
    def _null_ids(cls, value):
        return [] if value is None else value


class QuestionLink(BaseModel):
    question_id: str
    status: str = Field(pattern="^(connected|partial|hold)$")
    summary: str
    criteria: list[CriterionLink]


class LinkBatch(BaseModel):
    links: list[QuestionLink]


def hold_link(question_id: str, summary: str = HOLD_SUMMARY) -> QuestionLink:
    """6개 기준을 모두 '미확인'으로 둔 보류 연결을 만든다."""
    return QuestionLink(
        question_id=question_id,
        status="hold",
        summary=summary,
        criteria=[
            CriterionLink(
                criterion=criterion,
                assessment="미확인",
                citation_ids=[],
                next_check="시장·특허 근거 연결을 다시 실행",
            )
            for criterion in CRITERIA
        ],
    )


def call_report_llm(system_prompt: str, user_text: str) -> dict:
    response = get_openai_client().chat.completions.create(
        model=chat_model(MODEL),
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
    )
    return json.loads(response.choices[0].message.content)


def _evidence_ids(market: MarketReport, patent: PatentReport) -> tuple[set, set]:
    market_ids = {f"M:{item.citation_id}" for item in market.evidence}
    patent_ids = {f"P:{item.citation_id}" for item in patent.evidence}
    return market_ids, patent_ids


def _apply_hold_rule(link: QuestionLink, market_ids: set, patent_ids: set) -> None:
    used = {cid for criterion in link.criteria for cid in criterion.citation_ids}
    if not (market_ids and patent_ids) or not (used & market_ids and used & patent_ids):
        link.status = "hold"
        link.summary = BOTH_SIDES_SUMMARY


def _link_payload(questions: list[dict], market: MarketReport, patent: PatentReport):
    return {
        "questions": questions,
        "market": market.model_dump(),
        "patent": patent.model_dump(),
        "criteria": CRITERIA,
    }


def build_question_links(
    questions: list[dict],
    market: MarketReport,
    patent: PatentReport,
    llm_fn: Callable | None = None,
) -> list[QuestionLink]:
    """검토 질문을 근거와 연결한다. 양쪽 영역 중 하나라도 비면 해당 질문은 보류한다."""
    if not questions:
        return []
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    payload = _link_payload(questions, market, patent)
    batch = LinkBatch.model_validate(
        (llm_fn or call_report_llm)(prompt, json.dumps(payload, ensure_ascii=False))
    )
    wanted_ids = [item["id"] for item in questions]
    actual_ids = [link.question_id for link in batch.links]
    if set(actual_ids) != set(wanted_ids) or len(actual_ids) != len(wanted_ids):
        raise ValueError("Question evidence links must map one-to-one to questions")
    market_ids, patent_ids = _evidence_ids(market, patent)
    allowed_ids = market_ids | patent_ids
    for link in batch.links:
        if len(link.criteria) != len(CRITERIA) or {
            c.criterion for c in link.criteria
        } != set(CRITERIA):
            raise ValueError("Each question needs all six evidence criteria")
        for criterion in link.criteria:
            unknown = set(criterion.citation_ids) - allowed_ids
            if unknown:
                raise ValueError(f"Unknown integrated citation ids: {sorted(unknown)}")
        _apply_hold_rule(link, market_ids, patent_ids)
    return batch.links


def salvage_question_links(
    raw, questions: list[dict], market: MarketReport, patent: PatentReport
) -> tuple[list[QuestionLink], list[str]]:
    """검증에 실패한 LLM 응답에서 쓸 수 있는 질문 연결만 살린다.

    6개 기준을 모두 갖춘 질문은 허용되지 않은 인용 ID만 빼고 남기며, 나머지 질문은 보류한다.
    """
    market_ids, patent_ids = _evidence_ids(market, patent)
    allowed_ids = market_ids | patent_ids
    candidates = {}
    for item in (raw or {}).get("links", []) if isinstance(raw, dict) else []:
        try:
            link = QuestionLink.model_validate(item)
        except ValueError:
            continue
        candidates.setdefault(link.question_id, link)
    links, held = [], []
    for question in questions:
        link = candidates.get(question["id"])
        if link is None or {c.criterion for c in link.criteria} != set(CRITERIA):
            links.append(hold_link(question["id"]))
            held.append(question["id"])
            continue
        link.criteria = [
            next(c for c in link.criteria if c.criterion == name) for name in CRITERIA
        ]
        for criterion in link.criteria:
            criterion.citation_ids = [
                cid for cid in criterion.citation_ids if cid in allowed_ids
            ]
        _apply_hold_rule(link, market_ids, patent_ids)
        links.append(link)
    warnings = [f"질문 연결 형식 오류로 보류한 질문: {', '.join(held)}"] if held else []
    return links, warnings


def link_questions_with_retry(
    questions: list[dict],
    market: MarketReport,
    patent: PatentReport,
    llm_fn: Callable | None = None,
    attempts: int = LINK_ATTEMPTS,
) -> tuple[list[QuestionLink], list[str]]:
    """질문 연결을 검증하며 최대 attempts회 생성하고, 그래도 실패하면 질문 단위로 보류한다.

    재시도 때는 직전 검증 오류를 입력에 덧붙인다. 반환값은 (연결 목록, 경고 목록)이다.
    """
    if not questions:
        return [], []
    base_fn = llm_fn or call_report_llm
    last_raw, last_error = None, None
    for attempt in range(attempts):

        def recording_fn(system_prompt, user_text, _feedback=last_error):
            nonlocal last_raw
            if _feedback:
                user_text += (
                    f"\n\n직전 응답 검증 오류: {_feedback}\n"
                    "모든 질문 ID를 한 번씩, 6개 기준 이름 그대로, 입력에 있는 인용 ID만 써서 다시 작성하라."
                )
            last_raw = base_fn(system_prompt, user_text)
            return last_raw

        try:
            return build_question_links(questions, market, patent, recording_fn), []
        except ValueError as exc:
            last_error = str(exc)[:300]
        except Exception as exc:  # LLM 호출 실패는 재시도 없이 질문 전체를 보류한다
            return [hold_link(q["id"]) for q in questions], [
                f"질문 연결 호출 실패({type(exc).__name__})로 모든 질문을 보류했습니다."
            ]
    links, warnings = salvage_question_links(last_raw, questions, market, patent)
    return links, [f"질문 연결 검증 {attempts}회 실패: {last_error}", *warnings]
