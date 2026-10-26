import pytest
from pydantic import ValidationError

from src.generation.idea_parser import (
    FOLLOWUP_QUESTIONS,
    MAX_FOLLOWUP_ROUNDS,
    apply_answers,
    build_requests,
    parse_idea,
)
from src.schemas import IdeaDraft, MarketSearchRequest, PatentSearchRequest

IDEA_TEXT = (
    "중소 부품 공장에 협동로봇과 비전 카메라를 턴키로 설치해 주고 월 구독료를 받는다"
)

FULL_RESPONSE = {
    "title": "협동로봇+비전 턴키 자동화",
    "problem": "숙련 인력 부족으로 검사·적재 공정이 지연된다",
    "technology": "협동로봇과 비전 카메라",
    "customers": "중소 부품 공장",
    "difference": "턴키로 설치해 준다",
    "revenue": "월 구독료",
}


def fake_llm(response: dict):
    """고정 응답을 돌려주고, 받은 프롬프트·입력을 기록하는 가짜 LLM."""
    calls = []

    def llm(system_prompt: str, user_text: str) -> dict:
        calls.append((system_prompt, user_text))
        return response

    llm.calls = calls
    return llm


def partial_draft():
    response = {**FULL_RESPONSE, "problem": "", "revenue": ""}
    return parse_idea(IDEA_TEXT, llm_fn=fake_llm(response))


def test_parse_complete_idea():
    llm = fake_llm(FULL_RESPONSE)
    draft = parse_idea(f"  {IDEA_TEXT}  ", llm_fn=llm)

    assert draft.status == "complete"
    assert draft.missing_fields == []
    assert draft.field_sources == {f: "extracted" for f in FOLLOWUP_QUESTIONS}
    assert llm.calls[0][1] == IDEA_TEXT
    assert "JSON" in llm.calls[0][0]


def test_parse_missing_fields_asks_user():
    draft = partial_draft()

    assert draft.status == "needs_input"
    assert draft.missing_fields == ["problem", "revenue"]
    assert set(draft.questions) == {"problem", "revenue"}
    assert "problem" not in draft.field_sources


def test_parse_cleans_values_and_falls_back_title():
    response = {"title": "", "technology": "  협동로봇   비전 ", "problem": 3}
    draft = parse_idea(IDEA_TEXT, llm_fn=fake_llm(response))

    assert draft.technology == "협동로봇 비전"
    assert draft.problem == ""
    assert draft.title == IDEA_TEXT[:30]


def test_parse_empty_text():
    with pytest.raises(ValueError):
        parse_idea("   ", llm_fn=fake_llm(FULL_RESPONSE))


def test_apply_answers_completes_draft():
    draft = apply_answers(
        partial_draft(),
        {"problem": "검사 인력이 부족하다", "revenue": "장비 판매와 유지보수 계약"},
    )

    assert draft.status == "complete"
    assert draft.rounds == 1
    assert draft.revenue == "장비 판매와 유지보수 계약"
    assert draft.field_sources["problem"] == "user_answer"
    assert draft.field_sources["technology"] == "extracted"


def test_unknown_answer_is_confirmed_as_unknown():
    draft = apply_answers(
        partial_draft(), {"problem": "검사 인력이 부족하다", "revenue": "모름"}
    )

    assert draft.status == "complete"
    assert draft.revenue == ""
    assert draft.unknown_fields == ["revenue"]
    assert draft.to_structured_idea().revenue == ""


def test_followup_rounds_are_limited():
    draft = partial_draft()
    for _ in range(MAX_FOLLOWUP_ROUNDS):
        assert draft.status == "needs_input"
        draft = apply_answers(draft, {"problem": "", "revenue": ""})

    assert draft.status == "complete"
    assert draft.rounds == MAX_FOLLOWUP_ROUNDS
    assert draft.unknown_fields == ["problem", "revenue"]


def test_answer_can_correct_extracted_field():
    draft = parse_idea(IDEA_TEXT, llm_fn=fake_llm(FULL_RESPONSE))
    draft = apply_answers(draft, {"customers": "자동차 부품 2차 협력사"})

    assert draft.customers == "자동차 부품 2차 협력사"
    assert draft.field_sources["customers"] == "user_answer"
    assert draft.rounds == 0


def test_apply_answers_rejects_unknown_field():
    with pytest.raises(ValueError):
        apply_answers(partial_draft(), {"customer": "중소 공장"})


def test_build_requests_from_complete_draft():
    draft = parse_idea(IDEA_TEXT, llm_fn=fake_llm(FULL_RESPONSE))
    patent_request, market_request = build_requests(draft)

    assert isinstance(patent_request, PatentSearchRequest)
    assert isinstance(market_request, MarketSearchRequest)
    assert patent_request.idea == market_request.idea
    assert market_request.idea.customers == "중소 부품 공장"
    assert market_request.idea.title == "협동로봇+비전 턴키 자동화"


def test_build_requests_rejects_incomplete_draft():
    with pytest.raises(ValueError):
        build_requests(partial_draft())


def test_draft_status_must_match_missing_fields():
    with pytest.raises(ValidationError):
        IdeaDraft(
            original_text=IDEA_TEXT, status="complete", missing_fields=["problem"]
        )
    with pytest.raises(ValidationError):
        IdeaDraft(original_text=IDEA_TEXT, status="needs_input")
