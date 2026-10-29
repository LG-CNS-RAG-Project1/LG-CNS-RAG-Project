import math
import uuid
from collections import Counter

import chromadb
import pytest
from chromadb.config import Settings

from src.retrieval.market_search import build_index, get_collection
from src.schemas import (
    MarketDocument,
    MarketReport,
    MarketSearchRequest,
    StructuredIdea,
)
from src.services import market_network, market_service
from src.services.market_network import (
    build_keyword_network,
    extract_terms,
    layout_graph,
    load_network_config,
    select_graph,
    separate_points,
)

CONFIG = load_network_config()
VOCAB = ["협동로봇", "중소기업", "비용", "검사"]


def fake_tokenize(text):
    """'/'로 이어 쓴 말은 붙은 형태소, 공백은 띄어쓰기로 보는 가짜 형태소 분석기.

    예: '협동/로봇 도입' → 협동(NNG,0) 로봇(NNG,2) 도입(NNG,5). 'TAG:형태'로 품사를 지정한다.
    """
    tokens, pos = [], 0
    for word in text.replace("\n", " ").split(" "):
        for part in word.split("/"):
            tag, form = part.split(":") if ":" in part else ("NNG", part)
            tokens.append((form, tag, pos, len(form)))
            pos += len(form)
        pos += 1
    return tokens


def fake_embed(texts):
    return [[1.0 if w in t else 0.0 for w in VOCAB] + [0.01] for t in texts]


def test_extract_terms_merges_attached_nouns_and_english_phrases():
    text = (
        "협동/로봇 SN:2/NNB:차/전지 자동/XSN:화 SL:LS SL:ELECTRIC 기자 SN:2026 VV:늘다"
    )

    terms = extract_terms(text, CONFIG, fake_tokenize)

    assert terms == {"협동로봇", "2차전지", "자동화", "LS ELECTRIC"}


def test_select_graph_prefers_terms_distinctive_to_the_idea():
    documents = [{"협동로봇", "중소기업", "도입"}] * 6 + [
        {"협동로봇", "비용", "도입"}
    ] * 4
    corpus = Counter({"협동로봇": 20, "중소기업": 10, "비용": 8, "도입": 900})

    nodes, edges = select_graph(
        documents, {**CONFIG, "max_document_share": 1.0}, 1000, corpus
    )

    assert "도입" not in nodes  # 전체 뉴스에도 흔해 lift가 낮다
    assert nodes == Counter({"협동로봇": 10, "중소기업": 6, "비용": 4})
    assert ("중소기업", "협동로봇", 6) in edges and ("비용", "협동로봇", 4) in edges


def test_layout_graph_groups_and_positions_are_stable():
    nodes = Counter({"a": 9, "b": 8, "c": 7, "x": 6, "y": 5, "z": 4})
    edges = [
        ("a", "b", 5),
        ("b", "c", 5),
        ("a", "c", 4),
        ("x", "y", 5),
        ("y", "z", 5),
        ("x", "z", 4),
        ("c", "x", 1),
    ]

    first = layout_graph(nodes, edges)
    second = layout_graph(nodes, edges)

    cluster, coords, groups = first
    assert groups == [["a", "b", "c"], ["x", "y", "z"]]
    assert cluster["a"] == 0 and cluster["z"] == 1
    assert first == second
    assert all(-1.01 <= v <= 1.01 for xy in coords.values() for v in xy)


def test_separate_points_pushes_close_points_apart_and_rescales():
    points = {"a": (0.0, 0.0), "b": (0.01, 0.0), "c": (0.5, 0.5), "d": (-2.0, 0.0)}

    spread = separate_points(points, min_distance=0.2)

    ax, ay = spread["a"]
    bx, by = spread["b"]
    assert math.hypot(bx - ax, by - ay) > 0.05  # 처음 0.01이던 거리가 벌어짐
    assert max(abs(v) for p in spread.values() for v in p) == pytest.approx(1.0)
    assert separate_points(points, min_distance=0.2) == spread


@pytest.fixture
def news_collection():
    client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
    collection = get_collection(name=f"net-{uuid.uuid4().hex}", client=client)
    docs = []
    for i in range(30):
        topic = "협동/로봇 중소기업 비용" if i % 2 else "협동/로봇 중소기업 인력난"
        docs.append(
            MarketDocument(
                source_id=f"news-{i}",
                source_type="news",
                title=topic,
                publisher="example.com",
                text=f"{topic}\n요약 {i}",
                published_at=20261020,
                collected_at=20261022,
                reliability="medium",
                evidence_nature="business_signal",
                dup_group=f"news-{i}",
            )
        )
    docs += [
        MarketDocument(
            source_id=f"other-{i}",
            source_type="news",
            title="검사 장비",
            publisher="example.com",
            text="검사 장비\n요약",
            published_at=20261020,
            collected_at=20261022,
            reliability="medium",
            evidence_nature="business_signal",
            dup_group=f"other-{i}",
        )
        for i in range(60)
    ]
    build_index(docs, collection, embed_fn=fake_embed)
    return collection


REQUEST = MarketSearchRequest(
    idea=StructuredIdea(
        title="협동로봇", problem="중소기업 인력난", technology="협동로봇"
    )
)


def test_build_keyword_network_from_nearest_news(news_collection, monkeypatch):
    monkeypatch.setattr(market_network, "_CORPUS_DF", {})
    config = {**CONFIG, "documents": 30, "min_documents": 10, "max_document_share": 1.0}

    network = build_keyword_network(
        REQUEST, news_collection, fake_embed, config, fake_tokenize
    )

    assert network.status == "completed"
    assert network.document_count == 30
    terms = {n.term for n in network.nodes}
    assert {"협동로봇", "중소기업", "비용", "인력난"} <= terms
    assert "검사" not in terms
    assert sum(len(g) for g in network.clusters) == len(network.nodes)
    assert "근거가 아닙니다" in network.note


def test_build_keyword_network_insufficient_and_error(news_collection, monkeypatch):
    monkeypatch.setattr(market_network, "_CORPUS_DF", {})
    few = build_keyword_network(
        REQUEST, news_collection, fake_embed, {**CONFIG, "documents": 5}, fake_tokenize
    )

    def broken_embed(texts):
        raise RuntimeError("quota")

    failed = build_keyword_network(
        REQUEST, news_collection, broken_embed, CONFIG, fake_tokenize
    )

    assert few.status == "insufficient" and few.document_count == 5
    assert failed.status == "error" and "quota" in failed.error_message


def test_kiwi_tokenize_extracts_compound_nouns():
    pytest.importorskip("kiwipiepy")

    terms = extract_terms("중소기업 협동로봇 도입 확대…2차전지 외관검사 자동화", CONFIG)

    assert {"중소기업", "협동로봇", "2차전지", "외관검사", "자동화"} <= terms


def test_run_market_research_attaches_network_and_survives_failure(monkeypatch):
    monkeypatch.setattr(market_service, "search_scope", lambda c, i: "범위")
    monkeypatch.setattr(market_service, "search_with_relevance", lambda *a, **k: {})
    monkeypatch.setattr(
        market_service,
        "build_report",
        lambda *a: MarketReport(status="no_results", search_scope="범위"),
    )
    calls = []

    def fake_network(request, collection, embed_fn):
        calls.append((request, collection, embed_fn))
        return market_network.MarketKeywordNetwork(status="insufficient")

    def broken(request, collection, embed_fn):
        raise RuntimeError("boom")

    collection = object()
    attached = market_service.run_market_research(
        REQUEST, collection=collection, embed_fn=fake_embed, network_fn=fake_network
    )
    failed = market_service.run_market_research(
        REQUEST, collection=collection, network_fn=broken
    )

    assert calls == [(REQUEST, collection, fake_embed)]
    assert attached.keyword_network.status == "insufficient"
    assert failed.keyword_network.status == "error"
    assert failed.status == "no_results"
