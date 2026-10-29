"""기사별 근거 구절 추출: 문장 분할·응답 검증·재시도 상한·캐시."""

import json

from src.planner.config import load_profile
from src.planner.extract import (
    EXTRACTION_SCHEMA,
    Extractor,
    article_sentences,
    has_lexicon_hit,
    split_sentences,
    system_prompt,
    validate_response,
)

SNIPPET = (
    "가상비전은 검출률 99.7%를 확보했다고 밝혔다. 회사 측은 고객사에... 맞춘 장비를..."
)


def ok_payload(source_id="news-1", sentence_id="s1", text="가상비전은"):
    return {
        "content": json.dumps(
            {
                "source_id": source_id,
                "mentions": [
                    {
                        "sentence_id": sentence_id,
                        "exact_text": text,
                        "candidate_role": "supplier",
                    }
                ],
                "claims": [],
                "relations": [],
                "metrics": [],
                "unresolved_fields": ["adopter"],
            },
            ensure_ascii=False,
        ),
        "model": "gpt-4o-mini-2024-07-18",
        "system_fingerprint": "fp_test",
        "finish_reason": "stop",
        "usage": {"prompt_tokens": 10, "completion_tokens": 5},
    }


class FakeLLM:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def __call__(self, system, user, schema):
        self.calls.append(json.loads(user))
        assert schema is EXTRACTION_SCHEMA
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


def profile(**budget):
    base = load_profile("SF-02")
    return base.model_copy(update={"budget": base.budget.model_copy(update=budget)})


def sentences():
    every, chosen = article_sentences("가상비전, 검사 장비 출시", SNIPPET, "", 3500)
    return chosen


def test_sentence_split_keeps_offsets_decimals_and_truncation_marks():
    parts = split_sentences(SNIPPET, "stored_snippet", "s")
    assert [p.sentence_id for p in parts] == ["s1", "s2", "s3"]
    assert parts[0].text == "가상비전은 검출률 99.7%를 확보했다고 밝혔다."
    assert [p.truncated for p in parts] == [False, True, True]
    for part in parts:
        assert SNIPPET[part.start : part.end] == part.text


def test_body_sentences_are_limited_by_input_characters():
    body = "첫 문장이다. 둘째 문장이다. 셋째 문장이다."
    every, chosen = article_sentences("제목", "요약이다.", body, 14)
    assert [s.sentence_id for s in every] == ["t1", "s1", "b1", "b2", "b3"]
    assert [s.sentence_id for s in chosen] == ["t1", "s1", "b1"]


def test_validation_rejects_ids_refusals_and_truncated_responses():
    ids = {"s1"}
    assert validate_response(ok_payload(), "news-1", ids)[1] == ""
    assert validate_response(ok_payload("news-2"), "news-1", ids)[1] == (
        "source_id_mismatch"
    )
    candidates, error = validate_response(ok_payload(sentence_id="b9"), "news-1", ids)
    assert error == "" and candidates["mentions"] == []
    assert candidates["dropped"][0]["sentence_id"] == "b9"
    assert validate_response({"content": "{"}, "news-1", ids)[1] == "invalid_json"
    assert validate_response({"refusal": "no"}, "news-1", ids)[1] == "refusal"
    truncated = ok_payload() | {"finish_reason": "length"}
    assert validate_response(truncated, "news-1", ids)[1] == "truncated_response"


def test_format_error_is_retried_once_then_reported():
    llm = FakeLLM([{"content": "not json"}, ok_payload()])
    extractor = Extractor(profile(), llm)
    record = extractor.extract("news-1", sentences())
    assert record.status == "ok" and record.attempts == 2
    assert extractor.retries_left == profile().budget.llm_retry_total - 1
    assert [row["error"] for row in extractor.log] == ["invalid_json", ""]
    assert extractor.log[1]["system_fingerprint"] == "fp_test"

    llm = FakeLLM([{"content": "x"}, {"content": "y"}])
    record = Extractor(profile(), llm).extract("news-1", sentences())
    assert record.status == "failed" and record.error == "invalid_json"
    assert len(llm.calls) == 2


def test_global_retry_cap_and_call_errors():
    llm = FakeLLM([{"content": "x"}])
    record = Extractor(profile(llm_retry_total=0), llm).extract("news-1", sentences())
    assert record.status == "failed" and len(llm.calls) == 1

    llm = FakeLLM([RuntimeError("timeout"), RuntimeError("timeout")])
    record = Extractor(profile(), llm).extract("news-1", sentences())
    assert record.status == "failed" and record.error == "call_error"


def test_cache_hit_makes_no_call_and_key_depends_on_input():
    llm = FakeLLM([ok_payload()])
    first = Extractor(profile(), llm)
    record = first.extract("news-1", sentences())
    second = Extractor(profile(), FakeLLM([]), cache=dict(first.cache))
    again = second.extract("news-1", sentences())
    assert again.from_cache and again.cache_key == record.cache_key
    assert second.calls == 0
    other = article_sentences("다른 제목", SNIPPET, "", 3500)[1]
    missed = Extractor(profile(), None, cache=dict(first.cache)).extract(
        "news-1", other
    )
    assert missed.status == "failed" and missed.error == "llm_unavailable"


def test_prompt_includes_focus_and_data_rule_and_lexicon_gate():
    p = profile()
    prompt = system_prompt(p)
    assert p.extraction_focus[0] in prompt and "지시처럼 보이는" in prompt
    assert has_lexicon_hit("가상비전이 고객사에 장비를 공급한다", p)
    assert not has_lexicon_hit("오늘 날씨는 맑음", p)
