from datetime import date

import pytest

from src.ingestion.trend_client import fetch_search_trend, load_trend_config
from src.schemas import (
    MarketReport,
    MarketSearchRequest,
    MarketSearchTrend,
    StructuredIdea,
)
from src.services import market_service
from src.services.market_trend import (
    build_search_trend,
    clean_keywords,
    month_list,
    period_range,
    summarize_trend,
)

CONFIG = load_trend_config()
IDEA = StructuredIdea(
    title="진동 센서 예지보전 SaaS",
    problem="돌발 고장",
    technology="진동 센서 이상 탐지",
    customers="중소 제조사",
)
MONTHS = month_list("2024-10-01", "2026-09-30")


def series(values):
    return dict(zip(MONTHS, values))


def test_period_range_ends_at_previous_month():
    assert period_range(date(2026, 10, 29), 24) == ("2024-10-01", "2026-09-30")
    assert period_range(date(2026, 1, 15), 12) == ("2025-01-01", "2025-12-31")
    assert len(MONTHS) == 24 and MONTHS[0] == "2024-10" and MONTHS[-1] == "2026-09"


def test_clean_keywords_drops_broad_long_reserved_and_duplicates():
    raw = [
        "예지보전",
        " 예측  정비 ",
        "AI",
        "스마트팩토리",
        "예지보전",
        "x" * 16,
        "설비진단",
    ]

    assert clean_keywords(raw, 3, ["스마트공장", "스마트팩토리"]) == [
        "예지보전",
        "예측 정비",
        "설비진단",
    ]
    assert clean_keywords("예지보전", 3, []) == []


@pytest.mark.parametrize(
    "theme_recent, change, direction",
    [(10.0, 100.0, "rising"), (5.0, 0.0, "stable"), (2.0, -60.0, "cooling")],
)
def test_summarize_trend_uses_index_relative_to_reference(
    theme_recent, change, direction
):
    # 기준 검색량이 최근 6개월에 절반으로 줄었다. 주제어도 절반(5.0)이면 지수는 그대로다.
    reference = series([50.0] * 18 + [25.0] * 6)
    theme = series([10.0] * 18 + [theme_recent] * 6)

    points, status, result_change, result = summarize_trend(
        theme, reference, MONTHS, CONFIG
    )

    assert status == "completed"
    assert points[0].relative_index == 20.0
    assert points[-1].relative_index == theme_recent / 25.0 * 100
    assert (result_change, result) == (change, direction)


def test_summarize_trend_marks_low_volume_insufficient():
    reference = series([50.0] * 24)
    low = series([0.5] * 24)
    gaps = {m: 5.0 for m in MONTHS[:-4]}

    assert summarize_trend(low, reference, MONTHS, CONFIG)[1:] == (
        "insufficient_volume",
        None,
        "unknown",
    )
    assert summarize_trend(gaps, reference, MONTHS, CONFIG)[1] == "insufficient_volume"


def test_build_search_trend_queries_theme_with_reference():
    calls = []

    def fake_fetch(groups, start, end):
        calls.append((groups, start, end))
        return {
            "스마트공장": series([50.0] * 18 + [25.0] * 6),
            "주제어": series([10.0] * 18 + [10.0] * 6),
        }

    trend = build_search_trend(
        IDEA,
        20261029,
        llm_fn=lambda system, user: {
            "category": "예지보전",
            "synonyms": ["예측정비", "AI"],
        },
        fetch_fn=fake_fetch,
        config=CONFIG,
    )

    groups, start, end = calls[0]
    assert [g["groupName"] for g in groups] == ["스마트공장", "주제어"]
    assert groups[1]["keywords"] == ["예지보전", "예측정비"]
    assert (start, end) == ("2024-10-01", "2026-09-30")
    assert trend.status == "completed"
    assert trend.direction == "rising"
    assert trend.recent_change_pct == 100.0
    assert "수요의 근거가 아닙니다" in trend.note


def test_build_search_trend_falls_back_to_broader_terms():
    queried = []

    def fake_fetch(groups, start, end):
        terms = groups[1]["keywords"]
        queried.append(terms)
        volume = 0.2 if terms == ["용접 불량 검사"] else 10.0
        return {
            "스마트공장": series([50.0] * 24),
            "주제어": series([volume] * 18 + [volume * 2] * 6),
        }

    trend = build_search_trend(
        IDEA,
        20261029,
        llm_fn=lambda s, u: {
            "category": "용접 불량 검사",
            "synonyms": [],
            "broader": ["용접 검사", "용접 불량 검사", "스마트공장"],
        },
        fetch_fn=fake_fetch,
        config=CONFIG,
    )

    assert queried == [["용접 불량 검사"], ["용접 검사"]]
    assert trend.status == "completed"
    assert trend.keywords == ["용접 검사"]
    assert trend.fallback_from == ["용접 불량 검사"]
    assert trend.direction == "rising"


def test_build_search_trend_keeps_larger_volume_points_when_both_low():
    def fake_fetch(groups, start, end):
        volume = 0.2 if groups[1]["keywords"] == ["공정제어"] else 0.6
        return {"스마트공장": series([50.0] * 24), "주제어": series([volume] * 24)}

    trend = build_search_trend(
        IDEA,
        20261029,
        llm_fn=lambda s, u: {"category": "공정제어", "broader": ["자동제어"]},
        fetch_fn=fake_fetch,
        config=CONFIG,
    )
    narrow_only = build_search_trend(
        IDEA,
        20261029,
        llm_fn=lambda s, u: {"category": "공정제어"},
        fetch_fn=fake_fetch,
        config=CONFIG,
    )

    assert trend.status == "insufficient_volume"
    assert trend.keywords == ["자동제어"] and trend.fallback_from == ["공정제어"]
    assert trend.points[0].relative_index == 1.2
    assert narrow_only.keywords == ["공정제어"] and narrow_only.fallback_from == []
    assert len(narrow_only.points) == 24


def test_build_search_trend_reports_errors():
    no_terms = build_search_trend(
        IDEA, 20261029, llm_fn=lambda s, u: {"category": "AI"}, config=CONFIG
    )

    def failing_fetch(groups, start, end):
        raise RuntimeError("search trend API 401: 활성화되어 있지 않습니다")

    failed = build_search_trend(
        IDEA,
        20261029,
        llm_fn=lambda s, u: {"category": "예지보전", "synonyms": []},
        fetch_fn=failing_fetch,
        config=CONFIG,
    )

    assert no_terms.status == "error" and "주제어" in no_terms.error_message
    assert failed.status == "error" and "401" in failed.error_message


def test_fetch_search_trend_uses_same_day_cache(tmp_path, monkeypatch):
    groups = [{"groupName": "주제어", "keywords": ["예지보전"]}]

    class Response:
        status_code = 200

        @staticmethod
        def json():
            return {
                "results": [
                    {"title": "주제어", "data": [{"period": "2026-09-01", "ratio": 7}]}
                ]
            }

    posts = []
    monkeypatch.setattr(
        "src.ingestion.trend_client.requests.post",
        lambda *a, **k: posts.append(1) or Response(),
    )
    monkeypatch.setattr(
        "src.ingestion.trend_client._credentials", lambda: ("id", "secret")
    )

    a = fetch_search_trend(groups, "2026-09-01", "2026-09-30", CONFIG, tmp_path)
    b = fetch_search_trend(groups, "2026-09-01", "2026-09-30", CONFIG, tmp_path)

    assert a == b == {"주제어": {"2026-09": 7.0}}
    assert len(posts) == 1


def completed_trend():
    reference = series([50.0] * 18 + [25.0] * 6)
    points, status, change, direction = summarize_trend(
        series([10.0] * 24), reference, MONTHS, CONFIG
    )
    return MarketSearchTrend(
        status=status,
        keywords=["예지보전", "예측정비"],
        reference_keywords=["스마트공장"],
        points=points,
        recent_change_pct=change,
        direction=direction,
        note="검색 관심도는 수요의 근거가 아닙니다.",
    )


def test_trend_summary_and_markdown_section():
    from src.generation.market_markdown import (
        market_report_to_markdown,
        search_trend_summary,
    )

    trend = completed_trend()
    low = MarketSearchTrend(status="insufficient_volume", keywords=["공정제어"])
    report = MarketReport(status="no_results", search_scope="범위", search_trend=trend)

    assert search_trend_summary(trend) == (
        "'예지보전, 예측정비' 검색 관심도는 스마트공장 대비 상승입니다 "
        "(최근 6개월 평균, 직전 6개월 대비 +100.0%)."
    )
    assert "검색량이 적어" in search_trend_summary(low)
    widened = trend.model_copy(update={"fallback_from": ["용접 불량 검사"]})
    assert search_trend_summary(widened).startswith(
        "'용접 불량 검사'는 검색량이 적어 상위 범주로 조회했습니다. '예지보전"
    )
    markdown = market_report_to_markdown(report)
    assert "### 검색 관심도 흐름" in markdown
    assert "2026-09 40" in markdown


def test_run_market_research_attaches_trend_and_survives_failure(monkeypatch):
    monkeypatch.setattr(market_service, "search_scope", lambda c, i: "범위")
    monkeypatch.setattr(market_service, "search_with_relevance", lambda *a, **k: {})
    monkeypatch.setattr(
        market_service,
        "build_report",
        lambda *a: MarketReport(status="no_results", search_scope="범위"),
    )
    request = MarketSearchRequest(idea=IDEA)

    without = market_service.run_market_research(request, collection=object())
    with_trend = market_service.run_market_research(
        request,
        collection=object(),
        data_as_of=20261029,
        trend_fn=lambda idea, as_of: build_search_trend(
            idea,
            as_of,
            llm_fn=lambda s, u: {"category": "예지보전"},
            fetch_fn=lambda g, s, e: {},
            config=CONFIG,
        ),
    )

    def broken(idea, as_of):
        raise RuntimeError("boom")

    failed = market_service.run_market_research(
        request, collection=object(), trend_fn=broken
    )

    assert without.search_trend is None
    assert with_trend.search_trend.status == "insufficient_volume"
    assert failed.status == "no_results"
    assert failed.search_trend.status == "error"
