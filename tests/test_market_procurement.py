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
    build_procurement,
    buyer_type,
    judge_relevant,
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
