import json
import uuid

import chromadb
import pytest
from chromadb.config import Settings

from src.retrieval import market_relevance
from src.retrieval.market_relevance import (
    choose_dart_companies,
    dart_company_profiles,
    search_with_relevance,
)
from src.retrieval.market_search import build_index, get_collection
from src.schemas import MarketDocument, MarketSearchRequest, StructuredIdea

REQUEST = MarketSearchRequest(
    idea=StructuredIdea(
        title="AI 공정 조건 최적화 제어",
        problem="공정 조건 조정이 늦다",
        technology="공정 센서 데이터 기반 자동제어",
        customers="중견 제조사",
    )
)


def fake_embed(texts):
    return [[1.0, float(len(t) % 7), 0.01] for t in texts]


def dart_doc(source_id, company, ideas=("SF-05",)):
    return MarketDocument(
        source_id=source_id,
        source_type="dart",
        title=f"{company} 사업보고서(FY2025) 1. 사업의 개요",
        publisher=f"{company} (DART 사업보고서)",
        text=f"{company} 사업 개요",
        published_at=20260318,
        collected_at=20261029,
        reliability="high",
        evidence_nature="company_claim",
        dup_group=source_id,
        idea_ids=list(ideas),
    )


@pytest.fixture
def collection():
    client = chromadb.EphemeralClient(settings=Settings(anonymized_telemetry=False))
    col = get_collection(name=f"co-{uuid.uuid4().hex}", client=client)
    docs = [
        dart_doc("d1", "포스코DX"),
        dart_doc("d2", "엠아이큐브솔루션"),
        dart_doc("d3", "레인보우로보틱스", ideas=("SF-01",)),
        dart_doc("d4", "이삭엔지니어링"),
    ]
    build_index(docs, col, embed_fn=fake_embed)
    return col


def test_profiles_use_configured_business_descriptions(collection):
    profiles = dart_company_profiles(collection)
    sf05 = dart_company_profiles(collection, idea_id="SF-05")

    assert set(profiles) == {
        "포스코DX",
        "엠아이큐브솔루션",
        "레인보우로보틱스",
        "이삭엔지니어링",
    }
    assert "공정제어" in profiles["포스코DX"]
    assert "레인보우로보틱스" not in sf05


def test_choose_keeps_listed_names_in_order_up_to_three(collection):
    seen = {}

    def judge(system_prompt, user_text):
        seen["payload"] = json.loads(user_text)
        return {
            "companies": [
                "엠아이큐브솔루션",
                "없는기업",
                "엠아이큐브솔루션",
                "포스코DX",
                "이삭엔지니어링",
                "레인보우로보틱스",
            ]
        }

    chosen = choose_dart_companies(REQUEST, collection, judge)

    assert chosen == [
        "엠아이큐브솔루션 (DART 사업보고서)",
        "포스코DX (DART 사업보고서)",
        "이삭엔지니어링 (DART 사업보고서)",
    ]
    assert seen["payload"]["idea"]["technology"] == "공정 센서 데이터 기반 자동제어"
    assert {c["name"] for c in seen["payload"]["companies"]} == {
        "포스코DX",
        "엠아이큐브솔루션",
        "레인보우로보틱스",
        "이삭엔지니어링",
    }


def test_choose_returns_empty_list_or_none_on_failure(collection):
    def broken(system_prompt, user_text):
        raise RuntimeError("quota")

    assert (
        choose_dart_companies(REQUEST, collection, lambda s, u: {"companies": []}) == []
    )
    assert choose_dart_companies(REQUEST, collection, lambda s, u: {"label": 1}) is None
    assert choose_dart_companies(REQUEST, collection, broken) is None


def test_search_with_relevance_passes_chosen_companies(collection, monkeypatch):
    captured = {}

    def fake_search(
        request, idea_id=None, collection=None, embed_fn=None, dart_companies=None
    ):
        captured["dart_companies"] = dart_companies
        return {}

    monkeypatch.setattr(market_relevance, "search_by_dimensions", fake_search)

    search_with_relevance(
        REQUEST,
        collection=collection,
        embed_fn=fake_embed,
        judge_fn=lambda s, u: {"companies": ["포스코DX"]},
    )
    assert captured["dart_companies"] == ["포스코DX (DART 사업보고서)"]

    search_with_relevance(
        REQUEST.model_copy(update={"source_types": ["news"]}),
        collection=collection,
        embed_fn=fake_embed,
        judge_fn=lambda s, u: {"companies": ["포스코DX"]},
    )
    assert captured["dart_companies"] is None
