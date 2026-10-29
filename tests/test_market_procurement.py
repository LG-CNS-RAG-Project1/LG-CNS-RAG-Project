import json
from datetime import date

import pytest

from src.generation.market_markdown import (
    format_won,
    market_report_to_markdown,
    procurement_rows,
    procurement_stats,
    procurement_summary,
)
from src.ingestion.procurement_client import (
    fetch_bid_notices,
    load_procurement_config,
)
from src.schemas import (
    MarketProcurement,
    MarketReport,
    MarketSearchRequest,
    MarketSearchTrend,
    StructuredIdea,
)
from src.services import market_service
from src.services.market_procurement import (
    attach_procurement,
    build_procurement,
    buyer_type,
    judge_relevant,
    period_text,
    procurement_hits,
    recent_months,
    title_key,
    unique_notices,
)

CONFIG = load_procurement_config()
IDEA = StructuredIdea(
    title="협동로봇 턴키 자동화",
    problem="인력 부족",
    technology="협동로봇",
    customers="중소 제조사",
)


def raw(no, title, buyer, day, ord_="000", budget="40000000", kind="물품", **extra):
    return {
        "bidNtceNo": no,
        "bidNtceOrd": ord_,
        "bidNtceNm": title,
        "bidNtceDt": f"2026-{day} 10:00:00",
        "ntceKindNm": "등록공고",
        "dminsttNm": buyer,
        "asignBdgtAmt": budget,
        "presmptPrce": "",
        "dtilPrdctClsfcNoNm": "산업용로봇",
        "bidNtceDtlUrl": f"https://www.g2b.go.kr/link/?bidPbancNo={no}",
        "kind": kind,
        **extra,
    }


def all_relevant(system, user):
    notices = json.loads(user)["notices"]
    return {"judgments": [{"id": n["id"], "relevant": True} for n in notices]}


def test_recent_months_excludes_current_month():
    assert recent_months(date(2026, 10, 29), 3) == ["202607", "202608", "202609"]
    assert recent_months(date(2026, 2, 1), 3) == ["202511", "202512", "202601"]


def test_buyer_type_by_institution_name():
    assert buyer_type("주식회사 유엔디", CONFIG) == "민간 기업"
    assert buyer_type("한국과학기술원", CONFIG) == "대학·학교"
    assert buyer_type("서강대학교산학협력단", CONFIG) == "대학·학교"
    assert buyer_type("한국생산기술연구원", CONFIG) == "연구기관"
    assert buyer_type("서울교통공사", CONFIG) == "공공기관"


def test_unique_notices_drops_older_rounds_renotices_and_cancellations():
    notices = unique_notices(
        [
            raw("A", "협동 로봇 구매", "인하대학교", "08-28"),
            raw("A", "협동 로봇 구매", "인하대학교", "08-29", ord_="001"),
            raw("B", "국립창원대학교 협동 로봇 구매", "국립창원대학교", "09-02"),
            raw(
                "C", "국립창원대학교 협동 로봇 구매 (재공고)", "국립창원대학교", "09-17"
            ),
            raw("D", "[52251](글로컬)6축 협동 로봇", "포항공과대학교", "08-20"),
            raw("E", "협동로봇 구매", "한국기계연구원", "09-01", ntceKindNm="취소공고"),
        ],
        CONFIG,
    )

    assert [(n.notice_no, n.notice_date) for n in notices] == [
        ("C-000", 20260917),
        ("A-001", 20260829),
        ("D-000", 20260820),
    ]
    assert title_key("수의)(재)협동로봇 구매") == "협동로봇구매"
    assert notices[0].budget == 40000000 and notices[0].buyer_type == "대학·학교"


def test_judge_relevant_batches_and_keeps_only_true():
    notices = unique_notices(
        [raw(str(i), f"공고 {i}", f"기관{i}", "09-01") for i in range(5)], CONFIG
    )
    calls = []

    def judge(system, user):
        batch = json.loads(user)["notices"]
        calls.append(len(batch))
        return {
            "judgments": [
                {"id": n["id"], "relevant": n["title"] in ("공고 1", "공고 3")}
                for n in batch
            ]
            + [{"id": 99, "relevant": True}, "잘못된 값"]
        }

    kept = judge_relevant(IDEA, notices, judge, batch_size=2)

    assert calls == [2, 2, 1]
    assert sorted(n.title for n in kept) == ["공고 1", "공고 3"]
    assert judge_relevant(IDEA, [], judge) == []


def test_build_procurement_queries_each_keyword_kind_and_month():
    queried = []

    def fake_fetch(keyword, kind, month):
        queried.append((keyword, kind, month))
        if (keyword, kind, month) == ("협동로봇", "물품", "202609"):
            return [raw("A", "협동로봇 구매", "인하대학교", "09-01")]
        return []

    config = {**CONFIG, "months": 2}
    result = build_procurement(
        IDEA, ["협동로봇", "코봇"], 20261029, fake_fetch, all_relevant, config
    )

    assert len(queried) == 2 * 2 * 2
    assert result.status == "completed"
    assert result.period == "2026-08 ~ 2026-09"
    assert result.searched_count == 1 and len(result.notices) == 1
    assert "민간 고객 수요의 근거가 아니며" in result.note


def test_build_procurement_without_keywords_or_on_error():
    def failing(keyword, kind, month):
        raise RuntimeError(
            "나라장터 입찰공고 오류 30: SERVICE_KEY_IS_NOT_REGISTERED_ERROR"
        )

    assert build_procurement(IDEA, [], 20261029).status == "no_keywords"
    failed = build_procurement(IDEA, ["협동로봇"], 20261029, failing, all_relevant)
    assert failed.status == "error" and "30" in failed.error_message


class Response:
    def __init__(self, payload, status_code=200):
        self.payload, self.status_code = payload, status_code

    def json(self):
        return self.payload


def page(items, total):
    return {
        "response": {
            "header": {"resultCode": "00", "resultMsg": "정상"},
            "body": {"items": items, "totalCount": total},
        }
    }


def test_fetch_bid_notices_pages_caches_and_drops_personal_fields(
    tmp_path, monkeypatch
):
    personal = {
        "ntceInsttOfclNm": "홍길동",
        "ntceInsttOfclTelNo": "02-000-0000",
        "ntceInsttOfclEmailAdrs": "person@example.com",
        "exctvNm": "홍길동",
    }
    pages = [
        page([raw("A", "협동로봇", "인하대학교", "09-01", **personal)], 2),
        page([raw("B", "코봇", "서강대학교", "09-02")], 2),
    ]
    calls = []

    def fake_get(url, params, timeout):
        calls.append((url.rsplit("/", 1)[-1], params["pageNo"], params["inqryBgnDt"]))
        return Response(pages[params["pageNo"] - 1])

    monkeypatch.setattr("src.ingestion.procurement_client.requests.get", fake_get)
    monkeypatch.setattr(
        "src.ingestion.procurement_client._service_key", lambda: "secret"
    )
    monkeypatch.setattr("src.ingestion.procurement_client.time.sleep", lambda s: None)
    config = {**CONFIG, "api": {**CONFIG["api"], "num_of_rows": 1}}

    first = fetch_bid_notices("협동로봇", "물품", "202609", config, tmp_path)
    again = fetch_bid_notices("협동로봇", "물품", "202609", config, tmp_path)

    assert calls == [
        ("getBidPblancListInfoThngPPSSrch", 1, "202609010000"),
        ("getBidPblancListInfoThngPPSSrch", 2, "202609010000"),
    ]
    assert first == again and [n["bidNtceNo"] for n in first] == ["A", "B"]
    assert first[0]["kind"] == "물품"
    cached = next(tmp_path.iterdir()).read_text(encoding="utf-8")
    for value in ("홍길동", "02-000-0000", "person@example.com"):
        assert value not in json.dumps(first, ensure_ascii=False)
        assert value not in cached


def test_fetch_bid_notices_reports_api_errors(monkeypatch):
    error = {
        "nkoneps.com.response.ResponseError": {
            "header": {"resultCode": "07", "resultMsg": "입력범위값 초과 에러"}
        }
    }
    monkeypatch.setattr(
        "src.ingestion.procurement_client.requests.get",
        lambda url, params, timeout: Response(error),
    )
    monkeypatch.setattr(
        "src.ingestion.procurement_client._service_key", lambda: "secret"
    )

    with pytest.raises(RuntimeError, match="07: 입력범위값 초과"):
        fetch_bid_notices("협동로봇", "물품", "202609", CONFIG, None)


def test_stats_summary_rows_and_markdown():
    procurement = build_procurement(
        IDEA,
        ["협동로봇"],
        20261029,
        lambda k, kind, m: (
            [
                raw("A", "협동로봇 구매", "인하대학교", "09-01", budget="46310000"),
                raw(
                    "B",
                    "협동로봇본체 4대",
                    "주식회사 유엔디",
                    "08-01",
                    budget="88000000",
                ),
                raw(
                    "C", "실습장비", "동강대학 산학협력단", "07-08", budget="120000000"
                ),
            ]
            if (kind, m) == ("물품", "202609")
            else []
        ),
        all_relevant,
        {**CONFIG, "months": 1},
    )

    stats = procurement_stats(procurement)

    assert stats["count"] == 3
    assert (stats["median"], stats["min"], stats["max"]) == (
        88000000,
        46310000,
        120000000,
    )
    assert stats["buyer_types"] == {"대학·학교": 2, "민간 기업": 1}
    assert format_won(46310000) == "4,631만원" and format_won(120000000) == "1.2억원"
    assert "같은 제품·서비스 범주 3건" in procurement_summary(procurement)
    assert "예산 중앙값 8,800만원(4,631만원~1.2억원)" in procurement_summary(
        procurement
    )
    assert procurement_rows(procurement, 1) == [
        {
            "공고일": "2026-09-01",
            "구분": "물품",
            "수요기관": "인하대학교",
            "유형": "대학·학교",
            "공고명": "협동로봇 구매",
            "예산": "4,631만원",
            "공고": "https://www.g2b.go.kr/link/?bidPbancNo=A",
        }
    ]
    markdown = market_report_to_markdown(
        MarketReport(status="no_results", search_scope="범위", procurement=procurement)
    )
    assert "### 공공 조달 공고" in markdown
    assert "- 구매 주체: 대학·학교 2건 · 민간 기업 1건" in markdown
    assert "| 2026-09-01 | 물품 | 인하대학교(대학·학교) | [협동로봇 구매]" in markdown


def test_run_market_research_passes_trend_keywords_to_procurement(monkeypatch):
    monkeypatch.setattr(market_service, "search_scope", lambda c, i: "범위")
    monkeypatch.setattr(market_service, "search_with_relevance", lambda *a, **k: {})
    monkeypatch.setattr(
        market_service,
        "build_report",
        lambda *a: MarketReport(status="no_results", search_scope="범위"),
    )
    request = MarketSearchRequest(idea=IDEA)
    received = []

    def fake_procurement(idea, keywords, as_of):
        received.append(keywords)
        status = "completed" if keywords else "no_keywords"
        return MarketProcurement(status=status, keywords=keywords)

    def broken(idea, keywords, as_of):
        raise RuntimeError("boom")

    with_trend = market_service.run_market_research(
        request,
        collection=object(),
        data_as_of=20261029,
        trend_fn=lambda idea, as_of: MarketSearchTrend(
            status="completed", keywords=["협동로봇", "코봇"]
        ),
        procurement_fn=fake_procurement,
    )
    without_trend = market_service.run_market_research(
        request, collection=object(), procurement_fn=fake_procurement
    )
    failed = market_service.run_market_research(
        request, collection=object(), procurement_fn=broken
    )

    assert received == [["협동로봇", "코봇"], []]
    assert with_trend.procurement.status == "completed"
    assert without_trend.procurement.status == "no_keywords"
    assert failed.procurement.status == "error"


def completed_procurement():
    return build_procurement(
        IDEA,
        ["협동로봇", "코봇"],
        20261029,
        lambda k, kind, m: (
            [
                raw("A", "협동로봇 구매", "인하대학교", "09-01", budget="46310000"),
                raw(
                    "B",
                    "[지역주도형 AI대전환]협동로봇본체 4대",
                    "주식회사 유엔디",
                    "04-16",
                    budget="88000000",
                    cntrctCnclsMthdNm="일반경쟁",
                ),
                raw(
                    "C", "협동로봇 실습장비", "동강대학 산학협력단", "07-08", budget=""
                ),
                raw(
                    "D",
                    "6축 협동로봇",
                    "한국생산기술연구원",
                    "08-24",
                    budget="28765000",
                ),
                raw("E", "다관절 협동로봇", "조선대학교", "09-02", budget="42570000"),
            ]
            if (k, kind, m) == ("협동로봇", "물품", "202609")
            else []
        ),
        all_relevant,
        {**CONFIG, "months": 6},
    )


def test_procurement_hits_summary_and_private_first_notices():
    hits = procurement_hits(completed_procurement())

    assert len(hits) == 1 + 3
    summary, first, *_ = hits
    assert summary["source_type"] == "procurement"
    assert summary["evidence_nature"] == "purchase_signal"
    assert summary["period"] == "2026년 4월~2026년 9월"
    assert "관련 공고는 5건이다" in summary["text"]
    assert "배정예산 중앙값은 4,444만원" in summary["text"]
    assert first["source_id"] == "g2b-B-000"
    assert first["period"] == "2026년 4월"
    assert "주식회사 유엔디(민간 기업)가 2026년 4월 16일" in first["text"]
    assert "8,800만원(88,000,000원), 계약 방법 일반경쟁." in first["text"]
    assert all("동강대학" not in h["text"] for h in hits[1:])  # 예산 없는 공고 제외
    empty = MarketProcurement(status="completed", keywords=["협동로봇"])
    assert procurement_hits(empty) == []
    assert period_text("2026-04 ~ 2026-09") == "2026년 4월~2026년 9월"


def test_attach_procurement_adds_price_and_buyer_evidence_only():
    news = {"source_id": "n1", "relevant": True}
    assessed = {
        "demand": {"status": "limited", "relevant_count": 1, "hits": [news]},
        "price": {"status": "insufficient", "relevant_count": 0, "hits": []},
        "buyer": {"status": "error", "relevant_count": 0, "hits": []},
    }

    attached = attach_procurement(assessed, completed_procurement())

    assert attached["demand"] is assessed["demand"]
    assert attached["buyer"] is assessed["buyer"]  # 판정 실패 차원은 그대로
    assert attached["price"]["status"] == "sufficient"
    assert attached["price"]["relevant_count"] == 4
    assert assessed["price"]["hits"] == []  # 원래 결과는 바꾸지 않음
    assert attach_procurement(assessed, None) is assessed


def test_run_market_research_feeds_procurement_into_analysis(monkeypatch):
    monkeypatch.setattr(market_service, "search_scope", lambda c, i: "범위")
    monkeypatch.setattr(
        market_service,
        "search_with_relevance",
        lambda *a, **k: {"price": {"status": "no_results", "hits": []}},
    )
    seen = {}

    def fake_build_report(idea, assessed, scope, as_of, llm_fn):
        seen["price"] = assessed["price"]["status"]
        return MarketReport(status="no_results", search_scope=scope)

    monkeypatch.setattr(market_service, "build_report", fake_build_report)
    procurement = completed_procurement()

    report = market_service.run_market_research(
        MarketSearchRequest(idea=IDEA),
        collection=object(),
        data_as_of=20261029,
        trend_fn=lambda idea, as_of: MarketSearchTrend(
            status="completed", keywords=["협동로봇"]
        ),
        procurement_fn=lambda idea, keywords, as_of: procurement,
    )

    assert seen["price"] == "sufficient"
    assert report.procurement is procurement
    assert report.search_trend.keywords == ["협동로봇"]
