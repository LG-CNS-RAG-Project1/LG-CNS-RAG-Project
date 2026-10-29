import json

import pytest

from src.retrieval.market_relevance import (
    MIN_SUFFICIENT,
    assess_dimensions,
    checked_nature,
    judge_hits,
    judge_input,
    judged_hit,
    parse_relevance,
    sufficiency_status,
)
from src.schemas import StructuredIdea

IDEA = StructuredIdea(
    title="협동로봇 턴키 자동화",
    problem="인력 부족",
    technology="협동로봇",
    customers="중소 제조사",
    revenue="구독",
)


def make_hit(source_id, title="제목", summary="요약"):
    return {
        "source_id": source_id,
        "title": title,
        "text": f"{title}\n{summary}",
        "distance": 0.4,
    }


def judge_by_title(relevant_titles):
    """제목이 relevant_titles에 있으면 관련으로 판정하는 가짜 LLM."""

    def judge(system_prompt, user_text):
        title = json.loads(user_text)["title"]
        label = 1 if title in relevant_titles else 0
        return {"label": label, "confidence": "high", "reason": f"{title} 판정"}

    return judge


def test_judge_input_contains_idea_dimension_and_summary():
    data = json.loads(
        judge_input(IDEA, "price", make_hit("a", "가격 기사", "월 구독료"))
    )

    assert data["idea"]["revenue"] == "구독"
    assert "technical_components" not in data["idea"]
    assert data["dimension"] == "price"
    assert "가격" in data["question"]
    assert data["title"] == "가격 기사"
    assert data["summary"] == "월 구독료"


def test_parse_relevance():
    assert parse_relevance(
        {
            "label": 1,
            "confidence": "high",
            "reason": " 가격  ",
            "evidence_nature": "purchase_signal",
        }
    ) == {
        "relevant": True,
        "relevance_confidence": "high",
        "relevance_reason": "가격",
        "article_nature": "purchase_signal",
    }
    assert parse_relevance({"label": "yes"})["relevant"] is False
    assert parse_relevance({"evidence_nature": "direct_demand"})["article_nature"] == (
        "business_signal"
    )


@pytest.mark.parametrize(
    "nature, text, expected",
    [
        ("purchase_signal", "A사, B공장에 FEMS 구축 완료", "purchase_signal"),
        ("purchase_signal", "전문가 '로봇 확산 필요'", "business_signal"),
        ("indirect_demand", "무역협회 조사에 따르면 63.0%가 응답", "indirect_demand"),
        ("indirect_demand", "중소기업 AI 도입 더뎌…전문가 진단", "business_signal"),
        ("company_claim", "자사 제품 성능 강조", "company_claim"),
    ],
)
def test_checked_nature(nature, text, expected):
    assert checked_nature(nature, text) == expected


def test_judged_hit_replaces_nature_for_news_only():
    raw = {"label": 1, "evidence_nature": "purchase_signal"}
    news = {**make_hit("a", "A사 예지보전 시스템 도입"), "source_type": "news"}
    news["evidence_nature"] = "business_signal"
    dart = {**news, "source_type": "dart", "evidence_nature": "company_claim"}

    assert judged_hit(news, raw)["evidence_nature"] == "purchase_signal"
    assert judged_hit(dart, raw)["evidence_nature"] == "company_claim"
    assert judged_hit(dart, raw)["article_nature"] == "purchase_signal"


def test_judge_hits_keeps_search_order():
    hits = [make_hit("a", "관련1"), make_hit("b", "무관"), make_hit("c", "관련2")]

    judged = judge_hits(IDEA, "demand", hits, judge_by_title({"관련1", "관련2"}))

    assert [h["source_id"] for h in judged] == ["a", "b", "c"]
    assert [h["relevant"] for h in judged] == [True, False, True]
    assert judged[0]["relevance_reason"] == "관련1 판정"
    assert judged[0]["distance"] == 0.4


@pytest.mark.parametrize(
    "relevant_count, expected",
    [(0, "insufficient"), (1, "limited"), (MIN_SUFFICIENT, "sufficient")],
)
def test_sufficiency_status(relevant_count, expected):
    judged = [{"relevant": i < relevant_count} for i in range(5)]

    assert sufficiency_status(judged) == expected


def test_sufficiency_status_no_results():
    assert sufficiency_status([]) == "no_results"


def test_assess_dimensions_marks_error_per_dimension():
    calls = {"n": 0}

    def flaky_judge(system_prompt, user_text):
        if json.loads(user_text)["dimension"] == "price":
            raise RuntimeError("API 오류")
        calls["n"] += 1
        return {"label": 1, "confidence": "high"}

    results = {
        "demand": [make_hit("a"), make_hit("b")],
        "price": [make_hit("c")],
        "buyer": [],
    }
    assessed = assess_dimensions(IDEA, results, flaky_judge)

    assert assessed["demand"]["status"] == "sufficient"
    assert assessed["demand"]["relevant_count"] == 2
    assert assessed["price"]["status"] == "error"
    assert assessed["price"]["error_message"] == "API 오류"
    assert assessed["price"]["hits"] == results["price"]
    assert assessed["buyer"]["status"] == "no_results"
    assert calls["n"] == 2
