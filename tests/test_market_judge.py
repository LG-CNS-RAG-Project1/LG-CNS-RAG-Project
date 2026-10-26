import json

import pytest

from evaluation.market_judge import (
    agreement,
    merge_llm_labels,
    parse_judgement,
    prelabel,
)

IDEAS = {"SF-01": {"idea_id": "SF-01", "idea": {"title": "협동로봇 턴키 자동화"}}}


def make_row(source_id, relevant="", case_id="SF-01-price", **extra):
    return {
        "case_id": case_id,
        "idea_id": "SF-01",
        "dimension": "price",
        "question": "가격 근거가 있는가?",
        "source_id": source_id,
        "title": f"{source_id} 제목",
        "summary": f"{source_id} 요약",
        "relevant": relevant,
        **extra,
    }


def llm_row(source_id, label, confidence="high", case_id="SF-01-price"):
    return {
        "case_id": case_id,
        "source_id": source_id,
        "llm_label": label,
        "llm_confidence": confidence,
        "llm_reason": "이유",
    }


def test_parse_judgement_normalizes_values():
    assert parse_judgement(
        {"label": 1, "confidence": "high", "reason": " 가격  정보 "}
    ) == {
        "llm_label": "1",
        "llm_confidence": "high",
        "llm_reason": "가격 정보",
    }
    assert parse_judgement({"label": "yes", "confidence": "medium"}) == {
        "llm_label": "0",
        "llm_confidence": "low",
        "llm_reason": "",
    }


def test_prelabel_skips_judged_rows_and_respects_limit():
    calls = []

    def judge(system_prompt, user_text):
        calls.append(json.loads(user_text))
        return {"label": 1, "confidence": "high", "reason": "가격"}

    rows = [make_row("a"), make_row("b"), make_row("c")]
    results = prelabel(rows, IDEAS, judge, existing=[llm_row("a", "0")], limit=1)

    assert [r["source_id"] for r in results] == ["a", "b"]
    assert len(calls) == 1
    assert calls[0]["idea"]["title"] == "협동로봇 턴키 자동화"
    assert calls[0]["dimension"] == "price"


def test_agreement_and_kappa():
    human = [
        make_row("a", "1"),
        make_row("b", "1"),
        make_row("c", "0"),
        make_row("d", "0"),
        make_row("e", ""),
        make_row("f", "1", label_source="llm"),
    ]
    llm = [llm_row(s, l) for s, l in zip("abcdef", ["1", "0", "0", "0", "1", "1"])]

    result = agreement(human, llm)

    assert result["n"] == 4
    assert result["agreement"] == 0.75
    assert result["kappa"] == pytest.approx(0.5)
    assert [d["case_id"] for d in result["disagreements"]] == ["SF-01-price"]


def test_merge_keeps_human_labels_and_flags_low_confidence():
    human = [make_row("a", "0"), make_row("b"), make_row("c"), make_row("d")]
    llm = [llm_row("a", "1"), llm_row("b", "1"), llm_row("c", "0", "low")]

    merged = {r["source_id"]: r for r in merge_llm_labels(human, llm)}

    assert merged["a"]["relevant"] == "0"
    assert merged["a"]["label_source"] == "human"
    assert merged["a"]["llm_label"] == "1"
    assert merged["b"]["relevant"] == "1"
    assert merged["b"]["label_source"] == "llm"
    assert merged["c"]["review"] == "확인"
    assert merged["d"]["relevant"] == "" and merged["d"]["label_source"] == ""


def test_merge_again_keeps_previous_values():
    first = merge_llm_labels([make_row("a")], [llm_row("a", "1")])
    first[0]["relevant"] = "0"  # 사람이 LLM 값을 고친 경우

    second = merge_llm_labels(first, [llm_row("a", "1")])

    assert second[0]["relevant"] == "0"
    assert second[0]["label_source"] == "llm"
