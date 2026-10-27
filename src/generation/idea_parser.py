"""아이디어 한 문장을 5개 항목(문제·기술·고객·차별점·수익모델)으로 구조화하고,
빈 항목을 사용자에게 재질문한 뒤 특허·시장 검색 요청을 만든다.

흐름:
    parse_idea(text)              규칙 검사 → LLM 1회 호출로 입력 판정(input_status)과 항목 추출 → IdeaDraft
    apply_answers(draft, answers) 사용자 답변을 규칙 검사 후 병합하고 빈 항목을 다시 확인
    build_requests(draft)         완성된 아이디어로 PatentSearchRequest·MarketSearchRequest 생성

입력이 주제 이탈(off_topic)이거나 프롬프트 조작·유해 목적(unsafe)이면 status가 "rejected"이고
rejection_reason에 사용자 안내가 담긴다. rejected 초안으로는 검색 요청을 만들 수 없다.
사용자 문장은 JSON 값({"idea_text": ...})으로 넘겨 지시가 아닌 데이터로 다룬다.

재질문은 최대 MAX_FOLLOWUP_ROUNDS회다. 모름으로 답했거나 상한까지 비어 있는 항목은
field_sources가 "unknown"인 빈 값으로 확정한다.

사용 예:
    python -m src.generation.idea_parser "중소 공장에 협동로봇과 비전 검사를 턴키로 공급"
"""

import argparse
import json
import os
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

from src.generation.input_guard import (
    MAX_ANSWER_CHARS,
    REJECTION_MESSAGES,
    InputStatus,
    screen_text,
)
from src.schemas import (
    IDEA_FIELDS,
    IdeaDraft,
    IdeaField,
    MarketSearchRequest,
    PatentSearchRequest,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT_DIR / "prompts" / "idea_parser.md"
LLM_MODEL = "gpt-4o-mini"
MAX_FOLLOWUP_ROUNDS = 2
TITLE_MAX_LENGTH = 30
UNKNOWN_ANSWERS = {"모름", "모르겠음", "모르겠습니다", "잘 모름", "미정", "?"}

FIELD_LABELS: dict[IdeaField, str] = {
    "problem": "문제",
    "technology": "기술",
    "customers": "고객",
    "difference": "차별점",
    "revenue": "수익모델",
}

FOLLOWUP_QUESTIONS: dict[IdeaField, str] = {
    "problem": "이 아이디어가 해결하려는 현장의 문제는 무엇인가요?",
    "technology": "어떤 기술이나 장비로 문제를 해결하나요?",
    "customers": "누가 사용하고, 누가 구매를 결정하나요?",
    "difference": "기존 방식이나 경쟁 제품과 무엇이 다른가요?",
    "revenue": "어떤 방식으로 돈을 받을 계획인가요? (예: 장비 판매, 구독료, 유지보수 계약)",
}

LLMFn = Callable[[str, str], dict]


def call_llm(system_prompt: str, user_text: str) -> dict:
    """OpenAI 채팅 API를 JSON 모드로 호출해 응답 객체를 dict로 반환한다.

    .env의 OPENAI_API_KEY가 필요하며, 없으면 RuntimeError를 발생시킨다.
    """
    from openai import OpenAI

    load_dotenv(ROOT_DIR / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set in .env")
    response = OpenAI().chat.completions.create(
        model=LLM_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
    )
    return json.loads(response.choices[0].message.content)


def load_prompt(path: Path = PROMPT_PATH) -> str:
    """아이디어 구조화 프롬프트를 읽는다."""
    return path.read_text(encoding="utf-8")


def _clean(value) -> str:
    """문자열의 연속 공백을 정리한다. 문자열이 아니면 빈 문자열로 본다."""
    return " ".join(value.split()) if isinstance(value, str) else ""


def reject(text: str, status: InputStatus, reason: str | None = None) -> IdeaDraft:
    """거절된 입력의 초안을 만든다. reason이 없으면 상태별 기본 안내를 쓴다."""
    return IdeaDraft(
        original_text=text,
        status="rejected",
        input_status=status,
        rejection_reason=reason or REJECTION_MESSAGES[status],
    )


def check_draft(draft: IdeaDraft) -> IdeaDraft:
    """빈 항목을 찾아 상태와 재질문을 갱신한다.

    재질문 상한에 닿았으면 남은 빈 항목을 모름으로 확정하고 complete로 반환한다.
    거절된 초안은 그대로 반환한다.
    """
    if draft.status == "rejected":
        return draft
    sources = dict(draft.field_sources)
    missing = [
        f for f in IDEA_FIELDS if not getattr(draft, f) and sources.get(f) != "unknown"
    ]
    if missing and draft.rounds >= MAX_FOLLOWUP_ROUNDS:
        sources.update({f: "unknown" for f in missing})
        missing = []
    return IdeaDraft.model_validate(
        {
            **draft.model_dump(),
            "field_sources": sources,
            "status": "needs_input" if missing else "complete",
            "missing_fields": missing,
            "questions": {f: FOLLOWUP_QUESTIONS[f] for f in missing},
        }
    )


def parse_idea(text: str, llm_fn: LLMFn = call_llm) -> IdeaDraft:
    """아이디어 문장을 검사·항목별 추출하고 빈 항목 재질문을 준비한다.

    규칙 검사에 걸리면 LLM을 부르지 않고 거절한다. LLM이 input_status를 off_topic·unsafe로
    판정해도 거절하며, 알 수 없는 input_status는 off_topic으로 본다.
    """
    text = _clean(text)
    if not text:
        raise ValueError("idea text is empty")
    status, reason = screen_text(text)
    if status != "ok":
        return reject(text, status, reason)

    raw = llm_fn(load_prompt(), json.dumps({"idea_text": text}, ensure_ascii=False))
    status = raw.get("input_status", "ok")
    if status != "ok":
        return reject(text, status if status in REJECTION_MESSAGES else "off_topic")

    values = {f: _clean(raw.get(f)) for f in IDEA_FIELDS}
    title = _clean(raw.get("title")) or text
    draft = IdeaDraft(
        original_text=text,
        title=title[:TITLE_MAX_LENGTH],
        **values,
        field_sources={f: "extracted" for f in IDEA_FIELDS if values[f]},
        status="complete",
    )
    return check_draft(draft)


def apply_answers(draft: IdeaDraft, answers: dict[str, str]) -> IdeaDraft:
    """사용자 답변을 초안에 병합하고 다시 확인한다.

    - 빈 답변은 무시하고, UNKNOWN_ANSWERS에 해당하면 모름으로 확정한다.
    - 이미 채워진 항목도 답변으로 수정할 수 있으며 출처는 user_answer가 된다.
    - 재질문 중(needs_input)에 받은 답변이면 재질문 횟수를 1 늘린다.
    - 답변이 규칙 검사(길이 MAX_ANSWER_CHARS·프롬프트 조작 표현)에 걸리면 초안 전체를 거절한다.
    - 거절된 초안에는 답변을 받을 수 없다(ValueError).
    """
    if draft.status == "rejected":
        raise ValueError("cannot answer a rejected idea draft")
    invalid = set(answers) - set(IDEA_FIELDS)
    if invalid:
        raise ValueError(f"unknown idea fields: {sorted(invalid)}")

    update, sources = {}, dict(draft.field_sources)
    for field, answer in answers.items():
        value = _clean(answer)
        if not value:
            continue
        status, reason = screen_text(value, MAX_ANSWER_CHARS, min_chars=1)
        if status != "ok":
            return reject(draft.original_text, status, reason)
        if value in UNKNOWN_ANSWERS:
            update[field], sources[field] = "", "unknown"
        else:
            update[field], sources[field] = value, "user_answer"

    rounds = draft.rounds + (1 if draft.status == "needs_input" else 0)
    return check_draft(
        draft.model_copy(update={**update, "field_sources": sources, "rounds": rounds})
    )


def build_requests(
    draft: IdeaDraft,
) -> tuple[PatentSearchRequest, MarketSearchRequest]:
    """완성된 아이디어로 특허·시장 검색 요청을 만든다. 미완성 초안이면 ValueError."""
    idea = draft.to_structured_idea()
    return PatentSearchRequest(idea=idea), MarketSearchRequest(idea=idea)


def main() -> None:
    """아이디어 문장을 구조화하고, 빈 항목은 터미널에서 재질문한 뒤 결과를 출력한다."""
    parser = argparse.ArgumentParser(description="아이디어 5개 항목 구조화")
    parser.add_argument("text", help="아이디어 한 문장")
    args = parser.parse_args()

    draft = parse_idea(args.text)
    while draft.status == "needs_input":
        print(
            f"\n빈 항목 재질문 ({draft.rounds + 1}/{MAX_FOLLOWUP_ROUNDS}, 모르면 '모름')"
        )
        answers = {
            field: input(f"[{FIELD_LABELS[field]}] {question}\n> ")
            for field, question in draft.questions.items()
        }
        draft = apply_answers(draft, answers)

    result = draft.model_dump()
    result["unknown_fields"] = draft.unknown_fields
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
