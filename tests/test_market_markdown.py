from src.generation.market_markdown import SECTION_TITLE, market_report_to_markdown
from src.schemas import (
    MarketClaim,
    MarketDimensionResult,
    MarketEvidence,
    MarketReport,
)


def make_evidence(citation_id, title="협동로봇 도입 기사", url="https://example.com/a"):
    return MarketEvidence(
        citation_id=citation_id,
        source_id=f"NEWS-{citation_id}",
        source_type="news",
        title=title,
        publisher="테스트일보",
        quote="중소 제조사 A사가 협동로봇을 도입했다.",
        url=url,
        published_at=20261006,
        reliability="medium",
        recency="high",
        directness="medium",
        evidence_nature="business_signal",
    )


REPORT = MarketReport(
    status="completed",
    search_scope="테스트 범위",
    data_as_of=20261027,
    evidence=[make_evidence(1), make_evidence(2, title="가격 | 구독형", url=None)],
    dimensions=[
        MarketDimensionResult(
            dimension="demand",
            verdict="signal_only",
            claims=[
                MarketClaim(
                    statement="A사가 협동로봇을 도입했다.",
                    claim_type="fact",
                    citation_ids=[1],
                ),
                MarketClaim(
                    statement="인력난 공장에서 수요가 있을 가능성이 있다.",
                    claim_type="ai_hypothesis",
                ),
            ],
        ),
        MarketDimensionResult(
            dimension="price",
            verdict="unverified",
            next_check="공급사 견적으로 가격대 확인",
        ),
    ],
    unknowns=["가격 근거 미확인"],
)


def test_completed_report_markdown():
    markdown = market_report_to_markdown(REPORT)

    assert markdown.startswith(f"## {SECTION_TITLE}\n")
    assert "- 분석 기준일: 2026-10-27" in markdown
    assert "| 수요 | 신호만 확인 | M:1 |" in markdown
    assert "| 가격 | 미확인 | - |" in markdown
    assert "### 수요: 신호만 확인" in markdown
    assert "- [사실] A사가 협동로봇을 도입했다. [M:1]" in markdown
    assert "- [AI 가설] 인력난 공장에서 수요가 있을 가능성이 있다.\n" in markdown
    assert "- 다음 검증 과제: 공급사 견적으로 가격대 확인" in markdown
    assert "- 가격 근거 미확인" in markdown
    assert (
        "| M:1 | [협동로봇 도입 기사](https://example.com/a) | 테스트일보 | 2026-10-06"
        in markdown
    )
    assert "| M:2 | 가격 \\| 구독형 |" in markdown
    assert "사업 신호" in markdown


def test_heading_level():
    markdown = market_report_to_markdown(REPORT, heading_level=3)

    assert markdown.startswith(f"### {SECTION_TITLE}")
    assert "#### 수요: 신호만 확인" in markdown


def test_no_results_and_error_markdown():
    empty = MarketReport(
        status="no_results", search_scope="범위", unknowns=["수요 근거 미확인"]
    )
    markdown = market_report_to_markdown(empty)
    assert "시장 근거를 찾지 못해" in markdown
    assert "- 분석 기준일: 미확인" in markdown
    assert "근거 목록" not in markdown
    assert "- 수요 근거 미확인" in markdown

    error = MarketReport(status="error", search_scope="범위", error_message="API 오류")
    markdown = market_report_to_markdown(error)
    assert "- 오류: API 오류" in markdown
    assert "차원별 판정 요약" not in markdown
