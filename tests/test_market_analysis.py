import json

import pytest

from src.generation import market_analysis
from src.generation.market_analysis import (
    DEFAULT_CHECKS,
    allowed_verdicts,
    build_evidence,
    build_report,
    claim_errors,
    dimension_inputs,
    generate_dimensions,
    recency_grade,
)
from src.schemas import StructuredIdea
from src.services import market_service

AS_OF = 20261027
IDEA = StructuredIdea(
    title="협동로봇 턴키 자동화",
    problem="인력 부족",
    technology="협동로봇",
    customers="중소 제조사",
    revenue="월 구독료",
)
METRIC_FACT = "2026년 10월 보도 기준 도입 30% 증가"


def make_hit(source_id, relevant=True, summary="요약", published_at=20261001):
    return {
        "source_id": source_id,
        "source_type": "news",
        "publisher": "테스트일보",
        "title": f"{source_id} 기사",
        "text": f"{source_id} 기사\n{summary}",
        "url": f"https://example.com/{source_id}",
        "published_at": published_at,
        "period": None,
        "section": "title+description",
        "reliability": "medium",
        "evidence_nature": "business_signal",
        "distance": 0.4,
        "relevant": relevant,
        "relevance_confidence": "high",
        "relevance_reason": "테스트",
    }


def make_assessed(**dims):
    """{차원: (상태, hits)}를 search_with_relevance 반환 형식으로 바꾼다."""
    return {
        dim: {
            "status": status,
            "relevant_count": sum(h["relevant"] for h in hits),
            "hits": hits,
        }
        for dim, (status, hits) in dims.items()
    }


ASSESSED = make_assessed(
    demand=("sufficient", [make_hit("a"), make_hit("b", summary="도입 30% 증가")]),
    price=("limited", [make_hit("b", summary="도입 30% 증가"), make_hit("c", False)]),
    buyer=("insufficient", [make_hit("d", False)]),
    adoption_barrier=("error", [make_hit("e")]),
)


def fake_llm(responses):
    """호출마다 responses의 다음 응답을 돌려주고 입력을 기록하는 가짜 LLM."""
    calls = []

    def llm(system_prompt, user_text):
        calls.append(json.loads(user_text))
        return responses[min(len(calls), len(responses)) - 1]

    llm.calls = calls
    return llm


def dims(*items):
    return {"dimensions": list(items)}


def fact(statement, *ids):
    return {"statement": statement, "claim_type": "fact", "citation_ids": list(ids)}


VALID = dims(
    {
        "dimension": "demand",
        "verdict": "signal_only",
        "claims": [fact(METRIC_FACT, 2)],
    },
    {
        "dimension": "price",
        "verdict": "signal_only",
        "claims": [fact("2026년 도입 30% 증가", 2)],
    },
    {
        "dimension": "buyer",
        "verdict": "unverified",
        "claims": [],
        "next_check": "인터뷰",
    },
    {"dimension": "adoption_barrier", "verdict": "unverified", "next_check": "파일럿"},
)


def test_build_evidence_shares_citation_and_skips_irrelevant():
    evidence, ids = build_evidence(ASSESSED, AS_OF)

    assert [e.source_id for e in evidence] == ["a", "b"]
    assert ids["demand"] == [1, 2]
    assert ids["price"] == [2]
    assert ids["buyer"] == []
    assert ids["adoption_barrier"] == []
    assert evidence[1].quote == "도입 30% 증가"
    assert evidence[0].similarity == pytest.approx(0.6)


@pytest.mark.parametrize(
    "published_at, expected",
    [(20260101, "high"), (20240601, "medium"), (20220101, "low")],
)
def test_recency_grade(published_at, expected):
    assert recency_grade(published_at, AS_OF) == expected


def test_allowed_verdicts():
    evidence, _ = build_evidence(ASSESSED, AS_OF)

    assert allowed_verdicts("price", "sufficient", evidence) == [
        "confirmed",
        "signal_only",
        "unverified",
    ]
    assert allowed_verdicts("demand", "sufficient", evidence) == [
        "signal_only",
        "unverified",
    ]
    assert allowed_verdicts("price", "limited", evidence) == [
        "signal_only",
        "unverified",
    ]
    assert allowed_verdicts("buyer", "insufficient", []) == ["unverified"]
    assert allowed_verdicts("price", "sufficient", evidence, "수익모델") == [
        "unverified"
    ]


def test_missing_dependent_field_forces_unverified():
    idea = IDEA.model_copy(update={"revenue": ""})
    evidence, ids = build_evidence(ASSESSED, AS_OF)

    inputs = {
        d["dimension"]: d for d in dimension_inputs(idea, ASSESSED, evidence, ids)
    }

    assert inputs["price"]["missing_idea_field"] == "수익모델"
    assert inputs["price"]["allowed_verdicts"] == ["unverified"]
    assert "missing_idea_field" not in inputs["demand"]

    results, _ = generate_dimensions(
        idea, list(inputs.values()), evidence, fake_llm([VALID])
    )
    price = next(r for r in results if r.dimension == "price")
    assert price.verdict == "unverified"
    assert price.next_check.startswith("아이디어 수익모델 항목을 정한 뒤")


def test_claim_errors():
    evidence, _ = build_evidence(ASSESSED, AS_OF)
    by_id = {e.citation_id: e for e in evidence}

    assert claim_errors(fact(METRIC_FACT, 2), {1, 2}, by_id, "") == []
    assert "기준 연도" in claim_errors(fact("도입 30% 증가", 2), {1, 2}, by_id, "")[0]
    dated_quote = by_id[2].model_copy(update={"quote": "도입비용 2000만원"})
    assert (
        "기준 연도"
        in claim_errors(fact("도입비용 2000만원", 2), {2}, {2: dated_quote}, "")[0]
    )
    assert (
        claim_errors(fact("5G 기반 협동로봇 출시", 2), {2}, by_id, "5G 협동로봇") == []
    )
    assert "숫자" in claim_errors(fact("2026년 도입 45% 증가", 2), {1, 2}, by_id, "")[0]
    assert (
        "핵심 표현"
        in claim_errors(fact("해외 수출량이 급증", 2), {2}, {2: by_id[2]}, "")[0]
    )
    assert "인용" in claim_errors(fact("근거 없음"), {1, 2}, by_id, "")[0]
    assert "근거에 없는 인용" in claim_errors(fact("다른 차원", 1), {2}, by_id, "")[0]
    hypothesis = {"statement": "약 10% 절감 가능", "claim_type": "ai_hypothesis"}
    assert claim_errors(hypothesis, {2}, by_id, "")


def test_generate_retries_with_errors_then_passes():
    evidence, ids = build_evidence(ASSESSED, AS_OF)
    inputs = dimension_inputs(IDEA, ASSESSED, evidence, ids)
    invalid = dims(
        {
            "dimension": "demand",
            "verdict": "confirmed",
            "claims": [fact(METRIC_FACT, 2)],
        },
        *VALID["dimensions"][1:],
    )
    llm = fake_llm([invalid, VALID])

    results, retries = generate_dimensions(IDEA, inputs, evidence, llm)

    assert retries == 1
    assert "demand" in llm.calls[1]["previous_errors"]
    assert "previous_errors" not in llm.calls[0]
    assert [r.verdict for r in results] == [
        "signal_only",
        "signal_only",
        "unverified",
        "unverified",
    ]


def test_generate_drops_failed_claims_after_retries():
    evidence, ids = build_evidence(ASSESSED, AS_OF)
    inputs = dimension_inputs(IDEA, ASSESSED, evidence, ids)
    fabricated = dims(
        {
            "dimension": "demand",
            "verdict": "signal_only",
            "claims": [fact("시장 5조원", 1)],
        },
        *VALID["dimensions"][1:3],
    )
    llm = fake_llm([fabricated])

    results, retries = generate_dimensions(IDEA, inputs, evidence, llm)

    assert len(llm.calls) == market_analysis.MAX_RETRIES + 1
    assert retries == market_analysis.MAX_RETRIES
    demand, barrier = results[0], results[3]
    assert demand.verdict == "unverified"
    assert demand.claims == []
    assert demand.next_check == DEFAULT_CHECKS["demand"]
    assert barrier.next_check == DEFAULT_CHECKS["adoption_barrier"]


def test_build_report_completed():
    report = build_report(IDEA, ASSESSED, "테스트 범위", AS_OF, fake_llm([VALID]))

    assert report.status == "completed"
    assert len(report.evidence) == 2
    assert "아이디어 차별점 항목 미입력" in report.unknowns
    assert "구매자 근거 미확인" in report.unknowns
    assert (
        json.loads(report.model_dump_json())["dimensions"][0]["dimension"] == "demand"
    )


def test_build_report_no_results_and_error():
    empty = make_assessed(demand=("no_results", []), price=("no_results", []))
    assert build_report(IDEA, empty, "범위", AS_OF, fake_llm([VALID])).status == (
        "no_results"
    )

    def broken_llm(system_prompt, user_text):
        raise RuntimeError("API 오류")

    report = build_report(IDEA, ASSESSED, "범위", AS_OF, broken_llm)
    assert report.status == "error"
    assert "API 오류" in report.error_message
    assert len(report.evidence) == 2


def test_run_market_research_reports_search_error(monkeypatch):
    def failing_search(*args, **kwargs):
        raise RuntimeError("index missing")

    monkeypatch.setattr(market_service, "search_scope", lambda c, i: "범위")
    monkeypatch.setattr(market_service, "search_with_relevance", failing_search)

    report = market_service.run_market_research(
        market_service.MarketSearchRequest(idea=IDEA),
        collection=object(),
        data_as_of=AS_OF,
    )

    assert report.status == "error"
    assert "index missing" in report.error_message
