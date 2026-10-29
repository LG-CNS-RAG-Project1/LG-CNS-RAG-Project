import json

import pytest
from pydantic import ValidationError

from src.ingestion.market_processor import (
    apply_keyword_config,
    build_documents,
    current_keyword_ideas,
    group_duplicates,
    load_raw_news,
    merge_by_source_id,
    save_documents,
)
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


def make_raw(source_id, title, published_at=20261020, **overrides):
    data = dict(
        source_id=source_id,
        title=title,
        description=f"{title} 관련 요약",
        url=f"https://www.example.com/{source_id}",
        domain="www.example.com",
        published_at=published_at,
        collected_at=20261022,
        keyword_id="cobot_adoption",
        idea_ids=["SF-01"],
    )
    data.update(overrides)
    return data


def test_merge_by_source_id_unions_idea_ids():
    merged = merge_by_source_id(
        [
            make_raw("news-a", "협동로봇 도입 확대"),
            make_raw(
                "news-a",
                "협동로봇 도입 확대",
                keyword_id="smart_factory",
                idea_ids=["SF-02"],
            ),
        ]
    )

    assert len(merged) == 1
    assert merged[0]["idea_ids"] == {"SF-01", "SF-02"}
    assert merged[0]["keyword_ids"] == {"cobot_adoption", "smart_factory"}


def test_apply_keyword_config_uses_current_ideas_and_drops_legacy():
    records = apply_keyword_config(
        [
            make_raw("news-a", "스마트공장 확산", keyword_id="smart_factory"),
            make_raw("news-b", "생산현장 음성 AI", keyword_id="factory_voice_ai"),
        ],
        {"smart_factory": ["SF-01", "SF-05"]},
    )

    assert [r["source_id"] for r in records] == ["news-a"]
    assert records[0]["idea_ids"] == ["SF-01", "SF-05"]


def test_current_keyword_ideas_excludes_legacy_keywords():
    keyword_ideas = current_keyword_ideas()

    assert keyword_ideas["process_control_demand"] == ["SF-05"]
    assert "SF-05" in keyword_ideas["smart_factory"]
    assert "factory_voice_ai" not in keyword_ideas


def test_group_duplicates_by_title_and_date():
    records = merge_by_source_id(
        [
            make_raw("news-a", "두산로보틱스, 협동로봇 신제품 출시", 20261020),
            make_raw("news-b", "두산로보틱스 협동로봇 신제품 출시", 20261021),
            make_raw("news-c", "두산로보틱스, 협동로봇 신제품 출시", 20261001),
            make_raw("news-d", "LS일렉트릭 FEMS 사업 확대", 20261020),
        ]
    )
    groups = {frozenset(r["source_id"] for r in g) for g in group_duplicates(records)}

    assert frozenset({"news-a", "news-b"}) in groups
    assert frozenset({"news-c"}) in groups
    assert frozenset({"news-d"}) in groups


def test_build_documents_keeps_representative():
    documents = build_documents(
        [
            make_raw("news-a", "두산로보틱스, 협동로봇 신제품 출시", 20261021),
            make_raw(
                "news-b",
                "두산로보틱스 협동로봇 신제품 출시",
                20261020,
                idea_ids=["SF-02"],
            ),
        ]
    )

    assert len(documents) == 1
    doc = documents[0]
    assert doc.source_id == "news-b"
    assert doc.dup_group == "news-b"
    assert doc.idea_ids == ["SF-01", "SF-02"]
    assert doc.publisher == "example.com"
    assert doc.reliability == "medium"
    assert doc.evidence_nature == "business_signal"
    assert doc.text.startswith("두산로보틱스 협동로봇 신제품 출시\n")


def test_build_documents_without_description():
    documents = build_documents([make_raw("news-a", "스마트공장 보급", description="")])

    assert documents[0].text == "스마트공장 보급"


def test_processor_roundtrip(tmp_path):
    raw_dir = tmp_path / "raw"
    raw_dir.mkdir()
    payload = {"items": [make_raw("news-a", "예지보전 솔루션 도입")]}
    (raw_dir / "news_test_20261022.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8"
    )

    path = save_documents(
        build_documents(load_raw_news(raw_dir)), tmp_path / "docs.jsonl"
    )
    lines = path.read_text(encoding="utf-8").splitlines()

    assert len(lines) == 1
    assert MarketDocument.model_validate_json(lines[0]).source_id == "news-a"
