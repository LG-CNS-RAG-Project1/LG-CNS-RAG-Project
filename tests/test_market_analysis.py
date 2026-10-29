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
        "signal_only",
        "unverified",
    ]
    assert allowed_verdicts("demand", "sufficient", evidence) == [
        "signal_only",
        "unverified",
    ]
    purchase = [evidence[0].model_copy(update={"evidence_nature": "purchase_signal"})]
    assert allowed_verdicts("price", "sufficient", evidence + purchase) == [
        "confirmed",
        "signal_only",
        "unverified",
    ]
    assert allowed_verdicts("demand", "sufficient", purchase) == [
        "signal_only",
        "unverified",
    ]
    direct = [evidence[0].model_copy(update={"evidence_nature": "direct_demand"})]
    assert allowed_verdicts("demand", "sufficient", direct)[0] == "confirmed"
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
    certain = {
        "statement": "제조사가 주요 구매자로 확인되었다",
        "claim_type": "user_claim",
    }
    assert "확인된 사실" in claim_errors(certain, {2}, by_id, "")[0]
    hedged = {
        "statement": "사용자는 제조사가 구매자라고 본다",
        "claim_type": "user_claim",
    }
    assert claim_errors(hedged, {2}, by_id, "제조사 구매자") == []


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
    assert (
        "구매자 근거 미확인: 검색된 기사 1건이 모두 이 차원과 무관하다고 판정됨"
        in report.unknowns
    )
    assert (
        json.loads(report.model_dump_json())["dimensions"][0]["dimension"] == "demand"
    )
    by_dim = {d.dimension: d for d in report.dimensions}
    assert by_dim["demand"].evidence_status == "sufficient"
    assert by_dim["demand"].relevant_count == 2
    assert "고객 검증 자료" in by_dim["demand"].limitation
    assert by_dim["price"].limitation.startswith("관련 기사가 1건뿐")
    assert by_dim["adoption_barrier"].limitation.startswith("관련성 판정이 실패")


def test_build_evidence_uses_weaker_nature_across_dimensions():
    purchase = {**make_hit("a"), "evidence_nature": "purchase_signal"}
    assessed = make_assessed(
        buyer=("sufficient", [purchase]),
        price=("sufficient", [make_hit("a")]),
    )

    evidence, _ = build_evidence(assessed, AS_OF)

    assert evidence[0].evidence_nature == "business_signal"
    assert evidence[0].directness == "medium"


def test_confirmed_requires_fact_citing_confirming_evidence():
    purchase = {
        **make_hit("p", summary="A사 공장에 협동로봇 도입"),
        "evidence_nature": "purchase_signal",
    }
    assessed = make_assessed(buyer=("sufficient", [make_hit("a"), purchase]))
    evidence, ids = build_evidence(assessed, AS_OF)
    inputs = dimension_inputs(IDEA, assessed, evidence, ids)
    assert inputs[0]["allowed_verdicts"][0] == "confirmed"

    signal_cited = dims(
        {
            "dimension": "buyer",
            "verdict": "confirmed",
            "claims": [fact("a 기사 요약", 1)],
        }
    )
    llm = fake_llm([signal_cited])
    results, _ = generate_dimensions(IDEA, inputs, evidence, llm)
    assert "구매 신호" in llm.calls[1]["previous_errors"]["buyer"][0]
    assert results[0].verdict == "signal_only"

    purchase_cited = dims(
        {
            "dimension": "buyer",
            "verdict": "confirmed",
            "claims": [fact("A사 공장에 협동로봇 도입", 2)],
        }
    )
    results, retries = generate_dimensions(
        IDEA, inputs, evidence, fake_llm([purchase_cited])
    )
    assert retries == 0
    assert results[0].verdict == "confirmed"


def test_limitation_for_signal_only_pool():
    report = build_report(
        IDEA,
        make_assessed(
            competition=("sufficient", [make_hit("a"), make_hit("b")]),
            buyer=("no_results", []),
        ),
        "범위",
        AS_OF,
        fake_llm(
            [
                dims(
                    {
                        "dimension": "competition",
                        "verdict": "signal_only",
                        "claims": [fact("a 기사 요약", 1)],
                    },
                    {"dimension": "buyer", "verdict": "unverified", "next_check": "x"},
                )
            ]
        ),
    )
    by_dim = {d.dimension: d for d in report.dimensions}
    assert by_dim["competition"].limitation.startswith("관련 기사 2건이 모두 사업 신호")
    assert by_dim["buyer"].limitation.startswith("검색 범위에 이 차원의 기사가 없음")


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


def test_market_commercial_analysis_retains_only_known_citations():
    from pydantic import ValidationError
    from src.schemas import MarketCommercialAnalysis, MarketReport, MarketEvidence

    evidence = MarketEvidence(
        citation_id=1,
        source_id="x",
        source_type="news",
        title="title",
        publisher="pub",
        quote="quote",
        published_at=20261001,
        reliability="medium",
        recency="high",
        directness="low",
        evidence_nature="business_signal",
    )
    with pytest.raises(ValidationError, match="unknown citation"):
        MarketReport(
            status="completed",
            evidence=[evidence],
            search_scope="test",
            commercial_analysis=MarketCommercialAnalysis(
                buyer="미확인", citation_ids=[9]
            ),
        )


def test_market_hypothesis_is_separate_and_rejects_unknown_citations():
    from pydantic import ValidationError
    from src.schemas import (
        MarketAnalyticalHypothesis,
        MarketCommercialAnalysis,
        MarketEvidence,
        MarketReport,
    )

    evidence = MarketEvidence(
        citation_id=1,
        source_id="x",
        source_type="news",
        title="title",
        publisher="pub",
        quote="quote",
        published_at=20261001,
        reliability="medium",
        recency="high",
        directness="low",
        evidence_nature="business_signal",
    )
    hypothesis = MarketAnalyticalHypothesis(
        question="누가 구매하는가?",
        hypothesis="생산기술 조직이 검토자일 수 있음",
        basis="뉴스는 산업 신호만 제공하고 구매 주체를 명시하지 않음",
        citation_ids=[1],
        validation_target="제조사 생산기술 담당자",
        validation_method="구매 절차 인터뷰",
        success_criterion="구매 결정자와 예산 부서 확인",
    )
    report = MarketReport(
        status="completed",
        evidence=[evidence],
        search_scope="test",
        commercial_analysis=MarketCommercialAnalysis(hypotheses=[hypothesis]),
    )
    assert report.commercial_analysis.hypotheses[0].citation_ids == [1]
    with pytest.raises(ValidationError, match="hypothesis references unknown citation"):
        MarketReport(
            status="completed",
            evidence=[evidence],
            search_scope="test",
            commercial_analysis=MarketCommercialAnalysis(
                hypotheses=[hypothesis.model_copy(update={"citation_ids": [9]})]
            ),
        )


def test_market_numeric_hypothesis_requires_basis():
    from pydantic import ValidationError
    from src.schemas import (
        MarketAnalyticalHypothesis,
        MarketCommercialAnalysis,
        MarketEvidence,
        MarketReport,
    )

    with pytest.raises(ValidationError, match="require a stated basis"):
        MarketAnalyticalHypothesis(
            question="가격?",
            hypothesis="가설",
            basis="근거 부족",
            validation_target="구매자",
            validation_method="인터뷰",
            success_criterion="예산 확인",
            numeric_value=100000,
            numeric_unit="KRW",
        )

    value = MarketAnalyticalHypothesis(
        question="가격?",
        hypothesis="예시 수치",
        basis="검색 자료에 나온 숫자를 검토용으로 옮김",
        citation_ids=[1],
        validation_target="구매자",
        validation_method="인터뷰",
        success_criterion="예산 확인",
        numeric_value=1234,
        numeric_unit="KRW",
        numeric_basis="인용문에 표시된 값",
    )
    evidence = MarketEvidence(
        citation_id=1,
        source_id="x",
        source_type="news",
        title="title",
        publisher="pub",
        quote="자료에 예산 999원 표시",
        published_at=20261001,
        reliability="medium",
        recency="high",
        directness="low",
        evidence_nature="business_signal",
    )
    with pytest.raises(ValidationError, match="must match a cited source value"):
        MarketReport(
            status="completed",
            evidence=[evidence],
            search_scope="test",
            commercial_analysis=MarketCommercialAnalysis(hypotheses=[value]),
        )


def test_build_report_includes_business_approval_profile_and_citations():
    profile = {
        "commercial_analysis": {
            "user": "현장 품질 담당자",
            "buyer": "공장장",
            "budget_owner": "생산기술 예산",
            "use_case": "불량 검사 업무",
            "current_alternative": "수작업 검사",
            "switching_trigger": "검사 인력 부족",
            "purchase_process": "미확인",
            "adoption_requirements": ["기존 라인 연동"],
            "pricing_hypothesis": "미확인",
            "critical_assumptions": ["구매자 인터뷰 필요"],
            "citation_ids": [1],
            "unknowns": ["조달 기간"],
        }
    }
    report = build_report(
        IDEA, ASSESSED, "테스트 범위", AS_OF, fake_llm([VALID, profile])
    )
    assert report.commercial_analysis.buyer == "공장장"
    assert report.commercial_analysis.citation_ids == [1]
