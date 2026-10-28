import json

import pytest

from evaluation.market_relevance_eval import classification_metrics, evaluate_relevance

IDEAS = {
    "SF-01": {
        "idea_id": "SF-01",
        "idea": {
            "title": "협동로봇 턴키",
            "problem": "인력 부족",
            "technology": "협동로봇",
        },
    }
}


def make_row(case_id, source_id, relevant, rank, pool="vector", source="human"):
    return {
        "case_id": case_id,
        "idea_id": "SF-01",
        "dimension": case_id.split("-", 2)[2],
        "source_id": source_id,
        "title": f"{source_id} 제목",
        "summary": "요약",
        "relevant": relevant,
        "pool": pool,
        "rank": str(rank),
        "label_source": source,
    }


def judge_ids(relevant_ids):
    """기사 제목의 source_id가 relevant_ids에 있으면 관련으로 판정하는 가짜 LLM."""

    def judge(system_prompt, user_text):
        source_id = json.loads(user_text)["title"].split()[0]
        return {"label": int(source_id in relevant_ids), "confidence": "high"}

    return judge


def test_classification_metrics():
    m = classification_metrics([True, True, False, False], [True, False, False, False])

    assert m["accuracy"] == 0.75
    assert m["precision"] == 1.0
    assert m["recall"] == 0.5
    assert m["kappa"] == pytest.approx(0.5)


def test_evaluate_relevance_uses_only_human_rows():
    rows = [
        make_row("SF-01-price", "a", "1", 1),
        make_row("SF-01-price", "b", "1", 2),
        make_row("SF-01-price", "c", "0", 3),
        make_row("SF-01-price", "d", "0", 9, pool="term"),
        make_row("SF-01-buyer", "e", "1", 1),
        make_row("SF-01-buyer", "f", "0", 2, source="llm"),
    ]

    result = evaluate_relevance(rows, IDEAS, judge_ids({"a", "e"}))

    assert {r["source_id"] for r in result["rows"]} == {"a", "b", "c", "d", "e"}
    assert result["metrics"]["n"] == 5
    assert result["metrics"]["recall"] == pytest.approx(2 / 3)
    assert result["status"] == [
        {"case_id": "SF-01-price", "gold": "sufficient", "pred": "limited"}
    ]
