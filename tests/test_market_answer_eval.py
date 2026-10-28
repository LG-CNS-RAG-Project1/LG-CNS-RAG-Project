"""시장 답변 평가(evaluation/market_answer_eval.py) 테스트. API·색인 없이 가짜 함수로 확인한다."""

import json

from evaluation.market_answer_eval import (
    agreement,
    baseline_answer,
    claim_rows,
    collect_answers,
    corrected_accuracy,
    hits_to_sources,
    judge_claims,
    review_sample,
    summarize,
    unsourced_number,
)
from src.schemas import (
    MarketDimensionResult,
    MarketEvidence,
    MarketReport,
    StructuredIdea,
)

IDEA = StructuredIdea(
    title="협동로봇 턴키",
    problem="인력 부족",
    technology="협동로봇",
    customers="중소 제조사",
    difference="설치 일괄 제공",
    revenue="설치비",
)
IDEAS = {"SF-01": {"idea_id": "SF-01", "idea": IDEA.model_dump()}}
CASE = {
    "case_id": "SF-01-demand",
    "idea_id": "SF-01",
    "dimension": "demand",
    "question": "수요 근거가 있는가?",
    "relevant_source_ids": ["news-1"],
    "judged_source_ids": ["news-1", "news-2"],
}
SOURCES = [
    {
        "citation_id": 1,
        "source_id": "news-1",
        "title": "협동로봇 도입 30% 증가",
        "summary": "중소 제조사 도입 확대",
        "published_at": 20260315,
    }
]


def test_baseline_answer_normalizes_llm_output():
    raw = {
        "verdict": "maybe",
        "claims": [
            {"statement": "a  b", "claim_type": "fact", "citation_ids": [1, 9]},
            {"statement": "c", "claim_type": "guess"},
            {"statement": ""},
            {"statement": "d", "claim_type": "ai_hypothesis"},
            {"statement": "e", "claim_type": "fact"},
        ],
    }
    answer = baseline_answer(CASE, IDEA, SOURCES, lambda s, u: raw)
    assert answer["verdict"] == "unverified"
    assert [c["statement"] for c in answer["claims"]] == ["a b", "c", "d"]
    assert answer["claims"][0]["citation_ids"] == [1]
    assert answer["claims"][1]["claim_type"] == "fact"


def test_unsourced_number_checks_cited_text_and_date():
    assert not unsourced_number("2026년 3월 도입 30% 증가", SOURCES, "")
    assert unsourced_number("도입 45% 증가", SOURCES, "")
    assert unsourced_number("도입 30% 증가", [], "")
    assert not unsourced_number("도입이 늘고 있다", [], "")


def test_claim_rows_keep_only_cited_sources():
    answer = {
        "verdict": "signal_only",
        "claims": [
            {"statement": "도입 30% 증가", "claim_type": "fact", "citation_ids": [1]},
            {
                "statement": "수요 추정",
                "claim_type": "ai_hypothesis",
                "citation_ids": [],
            },
        ],
    }
    rows = claim_rows(CASE, "naive_rag", answer, SOURCES, "")
    assert [r["citation_ids"] for r in rows] == ["1", ""]
    assert json.loads(rows[0]["sources"])[0]["title"] == "협동로봇 도입 30% 증가"
    assert [r["source_relevance"] for r in rows] == ["1", ""]
    assert rows[0]["unsourced_number"] == 0
    assert rows[1]["claim_index"] == 2


def test_judge_and_summarize_by_arm():
    claims = [
        {
            "case_id": "SF-01-demand",
            "arm": arm,
            "claim_type": "fact",
            "statement": statement,
            "citation_ids": ids,
            "sources": json.dumps(SOURCES if ids else []),
            "source_relevance": relevance,
            "unsourced_number": number,
            "judge_label": "",
            "judge_error_type": "",
            "judge_reason": "",
        }
        for arm, statement, ids, relevance, number in [
            ("llm_only", "시장 규모 1조 원", "", "", 1),
            ("naive_rag", "도입 확대", "1", "1", 0),
            ("naive_rag", "업계 전체 수요 확인", "1", "0;?", 0),
        ]
    ]
    labels = {"도입 확대": "supported", "업계 전체 수요 확인": "partial"}
    inputs = []

    def judge_fn(system, user):
        inputs.append(json.loads(user))
        return {
            "label": labels[inputs[-1]["statement"]],
            "error_type": "overgeneralization",
            "reason": "r",
        }

    judge_claims(claims, judge_fn)
    assert claims[0]["judge_label"] == ""
    assert "question" not in inputs[0]
    assert "source_id" not in inputs[0]["sources"][0]
    answers = [
        {"arm": "llm_only", "dimension": "demand", "verdict": "confirmed"},
        {"arm": "naive_rag", "dimension": "demand", "verdict": "signal_only"},
    ]
    by_arm = {row["arm"]: row for row in summarize(answers, claims)}
    assert by_arm["llm_only"]["uncited_fact_rate"] == 1.0
    assert by_arm["llm_only"]["demand_confirmed"] == 1
    assert by_arm["llm_only"]["citation_accuracy"] is None
    assert by_arm["llm_only"]["unsourced_numbers"] == 1
    assert by_arm["naive_rag"]["citation_accuracy"] == 0.5
    assert by_arm["naive_rag"]["partial_rate"] == 0.5
    assert by_arm["naive_rag"]["error_types"] == "overgeneralization:1"
    assert by_arm["naive_rag"]["cited_relevance_rate"] == 0.5
    assert by_arm["naive_rag"]["cited_unlabeled"] == 1
    assert "idealens" not in by_arm


def test_collect_answers_runs_three_arms(monkeypatch):
    monkeypatch.setattr(
        "evaluation.market_answer_eval.case_query", lambda case, ideas: "질의"
    )
    report = MarketReport(
        status="completed",
        dimensions=[
            MarketDimensionResult(
                dimension="demand",
                verdict="signal_only",
                claims=[
                    {
                        "statement": "도입 확대",
                        "claim_type": "fact",
                        "citation_ids": [1],
                    }
                ],
            )
        ],
        evidence=[
            MarketEvidence(
                citation_id=1,
                source_id="news-1",
                source_type="news",
                title="협동로봇 도입 확대",
                publisher="p",
                quote="중소 제조사 도입",
                published_at=20260315,
                reliability="medium",
                recency="high",
                directness="low",
                evidence_nature="business_signal",
            )
        ],
        search_scope="SF-01",
        data_as_of=20261028,
    )
    hits = [
        {
            "source_id": "news-2",
            "title": "기사",
            "text": "기사\n요약",
            "published_at": 20260101,
        }
    ]
    seen = []

    def answer_fn(system, user):
        seen.append(json.loads(user)["sources"])
        return {"verdict": "signal_only", "claims": [{"statement": "x"}]}

    answers, claims = collect_answers(
        [CASE],
        IDEAS,
        {"SF-01": report},
        lambda query, top_k, idea_id: hits,
        answer_fn,
    )
    assert [a["arm"] for a in answers] == ["llm_only", "naive_rag", "idealens"]
    assert sorted(len(s) for s in seen) == [0, 1]
    assert hits_to_sources(hits)[0]["summary"] == "요약"
    idealens = [c for c in claims if c["arm"] == "idealens"]
    assert idealens[0]["citation_ids"] == "1"
    assert idealens[0]["source_relevance"] == "1"


def test_review_sample_hides_judge_and_agreement():
    claims = [
        {
            "case_id": f"c{i}",
            "arm": "idealens",
            "claim_index": "1",
            "statement": "s",
            "sources": json.dumps(SOURCES),
            "judge_label": label,
        }
        for i, label in enumerate(["supported", "partial", "unsupported", ""])
    ]
    assert {r["case_id"] for r in review_sample(claims, per_arm=2)} == {"c1", "c2"}
    rows = review_sample(claims, per_arm=10)
    assert len(rows) == 3
    assert "judge_label" not in rows[0]
    for row in rows:
        row["human_label"] = "supported"
    result = agreement(rows, claims)
    assert result["n"] == 3
    assert result["agreement"] == round(1 / 3, 3)
    assert result["confusion"]["supported->supported"] == 1
    assert result["by_arm"]["idealens"]["corrected_citation_accuracy"] == 1.0


def test_corrected_accuracy_weights_reviewed_rate_by_judge_label():
    claims = [
        {
            "case_id": f"c{i}",
            "arm": "naive_rag",
            "claim_index": "1",
            "judge_label": label,
        }
        for i, label in enumerate(["supported"] * 4 + ["partial"] * 2)
    ]
    review = [
        {
            "case_id": "c0",
            "arm": "naive_rag",
            "claim_index": "1",
            "human_label": "supported",
        },
        {
            "case_id": "c1",
            "arm": "naive_rag",
            "claim_index": "1",
            "human_label": "partial",
        },
        {
            "case_id": "c4",
            "arm": "naive_rag",
            "claim_index": "1",
            "human_label": "supported",
        },
        {
            "case_id": "c5",
            "arm": "naive_rag",
            "claim_index": "1",
            "human_label": "unsupported",
        },
    ]
    arm = corrected_accuracy(review, claims)["naive_rag"]
    assert arm["judge_citation_accuracy"] == round(4 / 6, 3)
    assert arm["corrected_citation_accuracy"] == 0.5
    assert arm["reviewed"] == 4
