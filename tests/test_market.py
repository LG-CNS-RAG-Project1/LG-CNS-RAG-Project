import pytest
from pydantic import ValidationError

from src.schemas import (
    MarketClaim,
    MarketDimensionResult,
    MarketDocument,
    MarketEvidence,
    MarketReport,
)


def make_document(**overrides):
    data = dict(
        source_id="NEWS-0001",
        source_type="news",
        title="테스트용 가상 기사",
        publisher="테스트 언론사",
        text="중소 제조사의 협동로봇 도입이 늘고 있다.",
        published_at=20260502,
        collected_at=20261022,
        reliability="medium",
        evidence_nature="business_signal",
        idea_ids=["SF-01"],
    )
    data.update(overrides)
    return MarketDocument(**data)


def make_evidence(citation_id=1, nature="business_signal", source_type="news"):
    return MarketEvidence(
        citation_id=citation_id,
        source_id=f"SRC-{citation_id}",
        source_type=source_type,
        title="테스트 근거",
        publisher="테스트",
        quote="테스트 인용문",
        published_at=20260502,
        reliability="medium",
        recency="high",
        directness="low",
        evidence_nature=nature,
    )


def test_document_to_chroma_metadata():
    meta = make_document().to_chroma_metadata()

    assert "text" not in meta
    assert meta["idea_ids"] == "SF-01"
    assert all(isinstance(v, (str, int, float, bool)) for v in meta.values())


def test_document_invalid_date():
    with pytest.raises(ValidationError):
        make_document(published_at=20261345)


def test_direct_demand_only_for_customer_validation():
    with pytest.raises(ValidationError):
        make_document(evidence_nature="direct_demand")


def test_valid_market_report():
    report = MarketReport(
        status="completed",
        search_scope="스마트팩토리 사전 수집 뉴스·공시",
        data_as_of=20261022,
        evidence=[make_evidence(1)],
        dimensions=[
            MarketDimensionResult(
                dimension="demand",
                verdict="signal_only",
                claims=[
                    MarketClaim(
                        statement="도입 사례 기사 확인",
                        claim_type="fact",
                        citation_ids=[1],
                    )
                ],
            ),
            MarketDimensionResult(
                dimension="price",
                verdict="unverified",
                next_check="고객 인터뷰로 지불 의사 확인",
            ),
        ],
    )

    assert report.status == "completed"
    assert len(report.dimensions) == 2


def test_demand_confirmed_requires_direct_evidence():
    with pytest.raises(ValidationError):
        MarketReport(
            status="completed",
            search_scope="테스트",
            evidence=[make_evidence(1, nature="business_signal")],
            dimensions=[
                MarketDimensionResult(
                    dimension="demand",
                    verdict="confirmed",
                    claims=[
                        MarketClaim(
                            statement="수요 확인", claim_type="fact", citation_ids=[1]
                        )
                    ],
                )
            ],
        )


def test_unknown_citation():
    with pytest.raises(ValidationError):
        MarketReport(
            status="completed",
            search_scope="테스트",
            evidence=[],
            dimensions=[
                MarketDimensionResult(
                    dimension="competition",
                    verdict="signal_only",
                    claims=[
                        MarketClaim(
                            statement="경쟁사 존재",
                            claim_type="fact",
                            citation_ids=[99],
                        )
                    ],
                )
            ],
        )


def test_unverified_requires_next_check():
    with pytest.raises(ValidationError):
        MarketDimensionResult(dimension="buyer", verdict="unverified")


def test_fact_requires_citation():
    with pytest.raises(ValidationError):
        MarketClaim(statement="근거 없는 사실", claim_type="fact")


def test_no_results():
    report = MarketReport(status="no_results", search_scope="스마트팩토리 시장")

    assert report.evidence == []
    assert report.dimensions == []
