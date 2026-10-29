"""예산 기반 뉴스 후보 수집: 상한별 제어, 제외 사유, 전재 처리, 무관 기사 미충족."""

import hashlib
from datetime import datetime

from src.planner.collect import (
    KST,
    Collection,
    collect_followup,
    collect_initial,
    in_scope,
)
from src.planner.config import load_profile

FIXED_NOW = datetime(2026, 10, 29, 9, 0, tzinfo=KST)


def unique_title(n):
    """제목 유사도 전재 판정에 걸리지 않도록 기사마다 다른 제목을 만든다."""
    return f"{hashlib.sha1(str(n).encode()).hexdigest()[:16]} AI 비전검사"


def item(n, title=None, desc="가나비전은 AI 비전검사 장비를 공급한다...", day=20):
    return {
        "title": title or unique_title(n),
        "description": desc,
        "originallink": f"https://news.example.com/{n}",
        "link": f"https://n.news.naver.com/{n}",
        "pubDate": f"Tue, {day} Oct 2026 09:00:00 +0900",
    }


class FakeSearch:
    def __init__(self, by_query=None, default=None, errors=None, per_query=0):
        self.per_query = per_query
        self.by_query = by_query or {}
        self.default = default or []
        self.errors = list(errors or [])
        self.calls = []

    def __call__(self, query, display, start, sort):
        self.calls.append((query, display, start, sort))
        if self.errors:
            raise self.errors.pop(0)
        items = self.by_query.get(query, self.default)
        if self.per_query:
            items = [item(f"{query}-{n}") for n in range(1, self.per_query + 1)]
        return {"total": len(items), "items": items[start - 1 : start - 1 + display]}


def profile(**budget):
    base = load_profile("SF-02")
    return base.model_copy(update={"budget": base.budget.model_copy(update=budget)})


def collection(search, **budget):
    return Collection(
        profile(**budget), search, clock=lambda: FIXED_NOW, sleep=lambda _: None
    )


def test_initial_collection_respects_group_quotas_and_records_shortfall():
    search = FakeSearch(per_query=60)
    c = collection(search)
    retained = collect_initial(c)
    assert len(retained) == 50 == len({r["source_id"] for r in retained})
    groups = {g.group: g.articles for g in c.profile.initial_allocation}
    for group, quota in groups.items():
        assert sum(r["group"] == group for r in retained) == quota
    assert c.requests_used <= c.budget.max_api_requests

    sparse = collection(FakeSearch(default=[item(n) for n in range(1, 6)]))
    assert len(collect_initial(sparse)) == 5
    assert sum(s["wanted"] - s["retained"] for s in sparse.shortfalls) == 45


def test_out_of_scope_duplicates_and_old_articles_are_excluded_with_reasons():
    pool = [
        item(1),
        item(
            2, title="가상전자 예지보전 시스템 계약", desc="설비 예지보전 솔루션 공급"
        ),
        item(3, title="부동산 시장 동향", desc="아파트 가격"),
        item(1),
        item(4, title=unique_title(1) + "!"),
        item(5, day=1) | {"pubDate": "Tue, 20 Oct 2020 09:00:00 +0900"},
    ]
    c = collection(FakeSearch(default=pool))
    query = [
        {"query_id": "q", "question_id": "C1", "query": "x", "group": "g", "round": 0}
    ]
    retained = c.collect(query, 10, "g")
    assert [r["url"] for r in retained] == ["https://news.example.com/1"]
    reasons = [row["reason"] for row in c.selection if row["decision"] == "excluded"]
    assert reasons == [
        "out_of_scope",
        "out_of_scope",
        "duplicate_url",
        "near_duplicate",
        "before_date_from",
    ]
    near = next(row for row in c.selection if row["reason"] == "near_duplicate")
    assert near["dup_group"] == retained[0]["dup_group"]
    assert c.shortfalls == [{"label": "g", "wanted": 10, "retained": 1}]


def test_scope_rule_allows_exclusion_terms_only_with_vision_terms():
    p = load_profile("SF-02")
    assert not in_scope("예지보전 검사 장비 계약", p)
    assert in_scope("예지보전과 머신비전 검사장비 함께 공급", p)
    assert not in_scope("현대차그룹, 협력사와 전환 비전 공유", p)


def test_request_cap_and_retry_rules_are_enforced_separately():
    search = FakeSearch(
        default=[item(n) for n in range(1, 30)],
        errors=[RuntimeError("Naver news API error 429: rate")],
    )
    c = collection(
        search, max_api_requests=3, display_per_request=2, max_pages_per_query=5
    )
    query = [
        {"query_id": "q", "question_id": "C1", "query": "x", "group": "g", "round": 0}
    ]
    retained = c.collect(query, 10, "g")
    assert c.requests_used == 3 == len(search.calls)
    assert [r["status"] for r in c.raw_responses] == ["error", "ok", "ok"]
    assert len(retained) == 4
    assert "request_cap_reached" in c.stops

    blocked = FakeSearch(errors=[RuntimeError("Naver news API error 401: auth")])
    c = collection(blocked)
    assert c.collect(query, 5, "g") == []
    assert c.requests_used == 1


def test_candidate_cap_stops_processing():
    c = collection(
        FakeSearch(default=[item(n) for n in range(1, 50)]), max_candidates=7
    )
    query = [
        {"query_id": "q", "question_id": "C1", "query": "x", "group": "g", "round": 0}
    ]
    c.collect(query, 20, "g")
    assert c.candidates_seen == 7
    assert "candidate_cap_reached" in c.stops


def test_same_responses_give_same_selection():
    a = collection(FakeSearch(per_query=30))
    b = collection(FakeSearch(per_query=30))
    assert collect_initial(a) == collect_initial(b)
    assert a.selection == b.selection


def test_followup_round_uses_batch_and_remaining_budget():
    c = collection(FakeSearch(per_query=60))
    collect_initial(c)
    for round_no in (1, 2, 3):
        picks = [
            {
                "question_id": "G3",
                "queries": [f"장비사 공급 {round_no}", f"SI {round_no}"],
            }
        ]
        new = collect_followup(c, picks, round_no)
        assert len(new) == 10 and {r["round"] for r in new} == {round_no}
    assert len(c.retained) == 80
    assert collect_followup(c, picks, 4) == []
    assert "budget_exhausted" in c.stops
