from src.generation.report_builder import (
    CRITERIA,
    escape_md,
    integrated_report_markdown,
    link_questions_with_retry,
    patent_location,
    safe_url,
)
from src.schemas import (
    IdeaDraft,
    MarketDimensionResult,
    MarketEvidence,
    MarketReport,
    PatentComparison,
    PatentEvidence,
    PatentReport,
)

QUESTIONS = [
    {"id": "Q1", "question": "질문1", "condition": ""},
    {"id": "Q2", "question": "질문2", "condition": ""},
]


def criteria(cids):
    return [
        {
            "criterion": c,
            "assessment": "확인",
            "citation_ids": cids,
            "next_check": "확인",
        }
        for c in CRITERIA
    ]


def reports():
    market = MarketReport(
        status="completed",
        search_scope="뉴스 | 범위",
        evidence=[
            MarketEvidence(
                citation_id=1,
                source_id="news-1",
                source_type="news",
                title="<script>x</script> 기사 | 제목 $5",
                publisher="example.com",
                url="javascript:alert(1)",
                published_at=20261001,
                quote="요약 | 내용",
                evidence_nature="business_signal",
                reliability="medium",
                recency="high",
                directness="low",
            )
        ],
        dimensions=[
            MarketDimensionResult(
                dimension="demand",
                verdict="signal_only",
                claims=[
                    {
                        "statement": "수요 신호가 있다 <b>강조</b>",
                        "claim_type": "fact",
                        "citation_ids": [1],
                    }
                ],
                next_check="고객 인터뷰",
            )
        ],
        data_as_of=20261028,
    )
    patent = PatentReport(
        status="completed",
        search_scope="KIPRIS",
        evidence=[
            PatentEvidence(
                citation_id=1,
                patent_id="1020200000001",
                title="검사 장치",
                section="claims",
                quote="청구항 원문",
                claim_number=3,
                claim_type="dependent",
                depends_on=[1],
                publication_date="20250102",
                source_url="https://example.com/p1",
            )
        ],
        comparisons=[
            PatentComparison(
                citation_id=1,
                similarity="유사",
                difference="차이",
                uncertainty="미확인",
            )
        ],
    )
    return market, patent


def test_retry_succeeds_with_feedback_on_second_attempt():
    market, patent = reports()
    calls = []

    def llm(system_prompt, user_text):
        calls.append(user_text)
        if len(calls) == 1:
            return {"links": []}
        return {
            "links": [
                {
                    "question_id": q["id"],
                    "status": "connected",
                    "summary": "s",
                    "criteria": criteria(["M:1", "P:1"]),
                }
                for q in QUESTIONS
            ]
        }

    links, warnings = link_questions_with_retry(QUESTIONS, market, patent, llm)
    assert len(calls) == 2 and "직전 응답 검증 오류" in calls[1]
    assert warnings == [] and {link.status for link in links} == {"connected"}


def test_salvage_keeps_valid_question_and_holds_the_rest():
    market, patent = reports()

    def llm(system_prompt, user_text):
        return {
            "links": [
                {
                    "question_id": "Q1",
                    "status": "connected",
                    "summary": "s",
                    "criteria": criteria(["M:1", "P:1", "P:99"]),
                }
            ]
        }

    links, warnings = link_questions_with_retry(QUESTIONS, market, patent, llm)
    by_id = {link.question_id: link for link in links}
    assert by_id["Q1"].status == "connected"
    assert all("P:99" not in c.citation_ids for c in by_id["Q1"].criteria)
    assert by_id["Q2"].status == "hold"
    assert any("Q2" in w for w in warnings)


def test_llm_call_failure_holds_all_questions():
    market, patent = reports()

    def broken(*_):
        raise ConnectionError("network")

    links, warnings = link_questions_with_retry(QUESTIONS, market, patent, broken)
    assert [link.status for link in links] == ["hold", "hold"]
    assert "ConnectionError" in warnings[0]


def test_escape_and_safe_url():
    assert escape_md("<b>x|y</b> $5") == "&lt;b&gt;x\\|y&lt;/b&gt; \\$5"
    assert escape_md("a|b", table=False) == "a|b"
    assert safe_url("javascript:alert(1)") is None
    assert safe_url("https://example.com/a?b=1") == "https://example.com/a?b=1"


def test_report_escapes_untrusted_text_and_shows_claim_location():
    market, patent = reports()
    draft = IdeaDraft(
        original_text="원문",
        title="<b>x|y</b>",
        problem="문제",
        technology="기술",
        customers="고객",
        difference="차별",
        revenue="",
        field_sources={"revenue": "unknown"},
        status="complete",
    )
    links, _ = link_questions_with_retry(
        QUESTIONS[:1],
        market,
        patent,
        lambda *_: {
            "links": [
                {
                    "question_id": "Q1",
                    "status": "connected",
                    "summary": "s",
                    "criteria": criteria(["M:1", "P:1"]),
                }
            ]
        },
    )
    md = integrated_report_markdown(
        draft.title,
        QUESTIONS[:1],
        links,
        market,
        patent,
        draft=draft,
        analyzed_on=20261028,
        market_collected_at=20261025,
    )
    assert md.startswith("# &lt;b&gt;x\\|y&lt;/b&gt;")
    assert "분석일 2026-10-28 · 시장 자료 기준 2026-10-25" in md
    assert "<script>" not in md and "javascript:" not in md
    assert "청구항 3 (종속, 인용 1항)" not in md
    assert "[원문](https://example.com/p1)" not in md
    assert "## 시장성 핵심" in md
    assert "M:1" in md and "P:1" in md
    assert len(md.splitlines()) < 45
    assert "상세 비교표·원문 인용·시장 분석은" in md


def test_patent_location_variants():
    evidence = PatentEvidence(
        citation_id=1, patent_id="p", title="t", section="abstract", quote="q"
    )
    assert patent_location(evidence) == "초록"
    evidence.section = "claims"
    assert patent_location(evidence) == "청구항(번호 미확인)"


def test_null_fields_from_llm_do_not_drop_links():
    market, patent = reports()

    def llm(system_prompt, user_text):
        return {
            "links": [
                {
                    "question_id": "Q1",
                    "status": "connected",
                    "summary": "s",
                    "criteria": [
                        {
                            "criterion": c,
                            "assessment": "확인",
                            "citation_ids": ["M:1", "P:1"] if i == 0 else None,
                            "next_check": None,
                        }
                        for i, c in enumerate(CRITERIA)
                    ],
                }
            ]
        }

    links, warnings = link_questions_with_retry(QUESTIONS[:1], market, patent, llm)
    assert warnings == [] and links[0].status == "connected"
    assert (
        links[0].criteria[1].citation_ids == []
        and links[0].criteria[0].next_check == ""
    )
