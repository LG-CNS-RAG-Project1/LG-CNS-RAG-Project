import uuid

import chromadb
import pytest
from chromadb.config import Settings

from src.retrieval.market_search import (
    DART_TOP_K,
    build_dimension_queries,
    build_index,
    build_where,
    get_collection,
    load_all_documents,
    search_by_dimensions,
    search_market,
    to_chroma_record,
)
from src.schemas import MarketDocument, MarketSearchRequest, StructuredIdea

VOCAB = ["협동로봇", "비전", "예지보전", "FEMS", "가격", "도입"]


def fake_embed(texts):
    """어휘 등장 여부로 만든 결정적 임베딩. API 없이 검색 순서를 검증한다."""
    return [[1.0 if word in text else 0.0 for word in VOCAB] + [0.01] for text in texts]


def make_document(source_id, text, **overrides):
    data = dict(
        source_id=source_id,
        source_type="news",
        title=text,
        publisher="example.com",
        text=text,
        published_at=20261020,
        collected_at=20261022,
        reliability="medium",
        evidence_nature="business_signal",
        dup_group=source_id,
        idea_ids=["SF-01"],
    )
    data.update(overrides)
    return MarketDocument(**data)


@pytest.fixture
def collection():
    client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
    return get_collection(name=f"test-{uuid.uuid4().hex}", client=client)


@pytest.fixture
def indexed(collection):
    documents = [
        make_document("news-a", "협동로봇 도입 확대"),
        make_document("news-b", "협동로봇 비전 검사 도입", dup_group="news-a"),
        make_document("news-c", "예지보전 솔루션", idea_ids=["SF-03"]),
        make_document("news-d", "FEMS 가격", published_at=20240105),
    ]
    build_index(documents, collection, embed_fn=fake_embed)
    return collection


def test_to_chroma_record_adds_idea_flags():
    record_id, text, meta = to_chroma_record(
        make_document("news-a", "협동로봇", idea_ids=["SF-01", "SF-02"])
    )

    assert record_id == "news-a#0"
    assert text == "협동로봇"
    assert meta["idea_SF-01"] is True and meta["idea_SF-02"] is True
    assert meta["chunk_index"] == 0


def test_build_index_skips_existing(indexed):
    added = build_index(
        [make_document("news-a", "협동로봇 도입 확대")], indexed, embed_fn=fake_embed
    )

    assert added == 0
    assert indexed.count() == 4


def test_build_index_reembeds_changed_text_and_updates_metadata(indexed):
    added = build_index(
        [
            make_document("news-a", "협동로봇 도입 확대", reliability="high"),
            make_document("news-c", "예지보전 솔루션 가격", idea_ids=["SF-03"]),
        ],
        indexed,
        embed_fn=fake_embed,
    )
    stored = indexed.get(
        ids=["news-a#0", "news-c#0"], include=["documents", "metadatas"]
    )
    by_id = dict(zip(stored["ids"], zip(stored["documents"], stored["metadatas"])))

    assert added == 1
    assert by_id["news-a#0"][1]["reliability"] == "high"
    assert by_id["news-c#0"][0] == "예지보전 솔루션 가격"


def test_build_index_prunes_stale_ids_after_upsert(indexed):
    def failing_embed(texts):
        raise RuntimeError("quota")

    with pytest.raises(RuntimeError):
        build_index(
            [make_document("news-new", "FEMS")],
            indexed,
            embed_fn=failing_embed,
            prune=True,
        )
    assert indexed.count() == 4

    build_index(
        [
            make_document("news-a", "협동로봇 도입 확대"),
            make_document("news-new", "FEMS"),
        ],
        indexed,
        embed_fn=fake_embed,
        prune=True,
    )
    assert sorted(indexed.get(include=[])["ids"]) == ["news-a#0", "news-new#0"]


def test_build_where():
    assert build_where() is None
    assert build_where(idea_id="SF-01") == {"idea_SF-01": True}
    assert build_where(idea_id="SF-01", date_from=20250101) == {
        "$and": [{"idea_SF-01": True}, {"published_at": {"$gte": 20250101}}]
    }


def test_search_market_orders_and_formats(indexed):
    hits = search_market("예지보전", collection=indexed, embed_fn=fake_embed, top_k=2)

    assert hits[0]["source_id"] == "news-c"
    assert hits[0]["distance"] <= hits[1]["distance"]
    assert set(hits[0]) == {
        "source_id",
        "text",
        "source_type",
        "publisher",
        "title",
        "url",
        "published_at",
        "period",
        "section",
        "reliability",
        "evidence_nature",
        "distance",
        "bm25_score",
        "rrf_score",
        "rerank_score",
        "search_ms",
        "rerank_ms",
    }


def test_search_market_returns_empty_for_filter_with_no_matches(indexed):
    assert (
        search_market(
            "협동로봇",
            collection=indexed,
            embed_fn=fake_embed,
            source_types=["not-a-market-source"],
        )
        == []
    )


@pytest.mark.parametrize("mode", ["bm25", "hybrid"])
def test_search_market_supports_shared_retrieval_modes(indexed, mode):
    hits = search_market(
        "협동로봇 비전 검사",
        collection=indexed,
        embed_fn=fake_embed,
        top_k=3,
        retrieval_mode=mode,
    )

    assert hits
    assert all(hit["bm25_score"] is not None for hit in hits)
    if mode == "hybrid":
        assert all(hit["rrf_score"] is not None for hit in hits)
    assert all(hit["search_ms"] >= 0 for hit in hits)


def test_search_market_dedups_dup_group(indexed):
    hits = search_market("협동로봇 도입", collection=indexed, embed_fn=fake_embed)
    groups = [h["source_id"] for h in hits if h["source_id"] in ("news-a", "news-b")]

    assert len(groups) == 1


def test_search_market_filters(indexed):
    sf03 = search_market(
        "협동로봇", collection=indexed, embed_fn=fake_embed, idea_id="SF-03"
    )
    recent = search_market(
        "FEMS 가격", collection=indexed, embed_fn=fake_embed, date_from=20250101
    )

    assert [h["source_id"] for h in sf03] == ["news-c"]
    assert "news-d" not in [h["source_id"] for h in recent]


def test_search_market_empty_collection(collection):
    assert search_market("협동로봇", collection=collection, embed_fn=fake_embed) == []


def test_search_by_dimensions(indexed):
    request = MarketSearchRequest(
        idea=StructuredIdea(
            title="협동로봇 턴키 자동화",
            problem="인력 부족",
            technology="협동로봇 비전",
            customers="중소 제조사",
        ),
        dimensions=["demand", "price"],
        top_k=2,
    )
    queries = build_dimension_queries(request)
    results = search_by_dimensions(
        request, idea_id="SF-01", collection=indexed, embed_fn=fake_embed
    )

    assert set(queries) == {"demand", "price"}
    assert "협동로봇 비전" in queries["price"]
    assert set(results) == {"demand", "price"}
    assert all(len(hits) <= 2 for hits in results.values())


def test_search_by_dimensions_appends_dart_quota(indexed):
    dart = [
        make_document(
            f"dart-r1-1-{i}",
            f"협동로봇 사업보고서 도입 {i}",
            source_type="dart",
            dup_group=f"dart-r1-{i}",
            evidence_nature="company_claim",
        )
        for i in range(3)
    ]
    build_index(dart, indexed, embed_fn=fake_embed)
    request = MarketSearchRequest(
        idea=StructuredIdea(
            title="협동로봇", problem="인력 부족", technology="협동로봇"
        ),
        dimensions=["demand"],
        top_k=2,
    )

    hits = search_by_dimensions(
        request, idea_id="SF-01", collection=indexed, embed_fn=fake_embed
    )["demand"]

    assert [h["source_type"] for h in hits] == ["news", "news"] + ["dart"] * DART_TOP_K
    only_dart = search_by_dimensions(
        request.model_copy(update={"source_types": ["dart"]}),
        idea_id="SF-01",
        collection=indexed,
        embed_fn=fake_embed,
    )["demand"]
    assert [h["source_type"] for h in only_dart] == ["dart", "dart"]


def test_load_all_documents_requires_dart(tmp_path):
    news = tmp_path / "market_docs.jsonl"
    news.write_text(make_document("news-a", "협동로봇").model_dump_json() + "\n")

    with pytest.raises(FileNotFoundError, match="dart_client"):
        load_all_documents(news, tmp_path / "dart_docs.jsonl")

    dart = tmp_path / "dart_docs.jsonl"
    dart.write_text(
        make_document("dart-r1-1-0", "협동로봇", source_type="dart").model_dump_json()
        + "\n"
    )
    assert [d.source_type for d in load_all_documents(news, dart)] == ["news", "dart"]


def test_dimension_queries_use_idea_fields():
    queries = build_dimension_queries(
        MarketSearchRequest(
            idea=StructuredIdea(
                title="협동로봇 턴키 자동화",
                problem="숙련 인력 부족",
                technology="협동로봇 비전",
                customers="중소 제조사",
                difference="턴키 설치",
                revenue="",
            )
        )
    )

    assert "숙련 인력 부족" in queries["demand"]
    assert "턴키 설치" in queries["competition"]
    assert "중소 제조사" in queries["buyer"]
    assert "협동로봇 턴키 자동화" not in queries["demand"]
    assert all("  " not in q and q == q.strip() for q in queries.values())
