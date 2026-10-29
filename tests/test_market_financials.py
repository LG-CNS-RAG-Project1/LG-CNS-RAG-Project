from src.generation.market_markdown import (
    company_financial_rows,
    company_financials_summary,
    market_report_to_markdown,
)
from src.ingestion.dart_client import fetch_major_accounts
from src.schemas import MarketReport, MarketSearchRequest, StructuredIdea
from src.services import market_service
from src.services.market_financials import (
    build_company_financials,
    parse_amount,
    summarize_accounts,
)

CONFIG = {
    "companies": [
        {"name": "두산로보틱스", "stock_code": "454910"},
        {"name": "엠아이큐브솔루션", "stock_code": "373170"},
        {"name": "뉴로메카", "stock_code": "348340"},
    ]
}
CORP_CODES = {
    "454910": {"corp_code": "001"},
    "373170": {"corp_code": "002"},
    "348340": {"corp_code": "003"},
}


def account(fs_div, name, current, previous, before):
    return {
        "fs_div": fs_div,
        "account_nm": name,
        "rcept_no": "20260310000001",
        "thstrm_amount": current,
        "frmtrm_amount": previous,
        "bfefrmtrm_amount": before,
    }


DOOSAN = [
    account("CFS", "매출액", "32,978,338,354", "46,829,943,837", "53,038,372,299"),
    account("CFS", "영업이익", "-59,472,307,590", "-41,202,116,246", "-"),
    account("OFS", "매출액", "1", "1", "1"),
]
SEPARATE_ONLY = [
    account("OFS", "매출액", "25,620,442,016", "20,000,000,000", ""),
    account("OFS", "영업이익", "2,562,044,201", "1,000,000,000", ""),
    account("OFS", "당기순이익(손실)", "1,000,000,000", "", ""),
]


def test_parse_amount_handles_commas_signs_and_blanks():
    assert parse_amount("32,978,338,354") == 32978338354
    assert parse_amount("-1,234") == -1234
    assert parse_amount("-") is None
    assert parse_amount("") is None
    assert parse_amount(None) is None


def test_summarize_accounts_prefers_consolidated_and_orders_years():
    statement, rcept_no, years = summarize_accounts(DOOSAN, 2025)

    assert (statement, rcept_no) == ("연결", "20260310000001")
    assert [y.year for y in years] == [2023, 2024, 2025]
    assert years[-1].revenue == 32978338354
    assert years[0].operating_income is None
    assert years[-1].net_income is None
    separate = summarize_accounts(SEPARATE_ONLY, 2025)
    assert separate[0] == "별도"
    assert separate[2][-1].net_income == 1000000000
    assert summarize_accounts([], 2025) is None


def test_build_company_financials_falls_back_to_previous_year_and_reports_missing():
    calls = []

    def fake_fetch(corp_code, year):
        calls.append((corp_code, year))
        if corp_code == "001":
            return DOOSAN if year == 2025 else []
        if corp_code == "002":
            return SEPARATE_ONLY if year == 2024 else []
        return []

    result = build_company_financials(
        ["두산로보틱스", "엠아이큐브솔루션", "뉴로메카", "없는기업"],
        20261029,
        fetch_fn=fake_fetch,
        config=CONFIG,
        corp_codes=CORP_CODES,
    )

    assert result.status == "completed"
    assert [c.company for c in result.companies] == ["두산로보틱스", "엠아이큐브솔루션"]
    assert result.companies[1].years[-1].year == 2024
    assert ("001", 2024) not in calls and ("002", 2024) in calls
    assert result.missing == [
        "뉴로메카: 최근 사업보고서 재무 계정 없음",
        "없는기업: DART 기업 설정 없음",
    ]
    assert "시장 규모나 고객 수요의 근거가 아닙니다" in result.note


def test_build_company_financials_without_companies_or_with_errors():
    def failing(corp_code, year):
        raise RuntimeError("OpenDART fnlttSinglAcnt error 020: 요청 제한")

    empty = build_company_financials([], 20261029)
    failed = build_company_financials(
        ["두산로보틱스"], 20261029, failing, CONFIG, CORP_CODES
    )

    assert empty.status == "no_companies"
    assert failed.status == "error" and "020" in failed.error_message


def test_rows_markdown_and_summary():
    financials = build_company_financials(
        ["두산로보틱스", "엠아이큐브솔루션"],
        20261029,
        lambda corp, year: {"001": DOOSAN, "002": SEPARATE_ONLY}[corp],
        CONFIG,
        CORP_CODES,
    )

    rows = company_financial_rows(financials)

    assert rows[0] == {
        "기업": "두산로보틱스",
        "재무제표": "연결",
        "매출액 2023": "530",
        "매출액 2024": "468",
        "매출액 2025": "330",
        "매출 증감(전년)": "-29.6%",
        "영업이익 2025": "-595",
        "영업이익률": "-180.3%",
        "당기순이익 2025": "-",
    }
    assert rows[1]["매출액 2023"] == "-"
    assert rows[1]["매출 증감(전년)"] == "+28.1%"
    assert rows[1]["영업이익률"] == "10.0%"
    assert "2곳" in company_financials_summary(financials)

    markdown = market_report_to_markdown(
        MarketReport(
            status="no_results", search_scope="범위", company_financials=financials
        )
    )
    assert "### 인접 기업 재무 현황" in markdown
    assert "| 두산로보틱스 | 연결 | 530 | 468 | 330 | -29.6% | -595 |" in markdown


def test_fetch_major_accounts_caches_only_found_reports(tmp_path, monkeypatch):
    responses = {
        "2025": {"status": "000", "list": [{"account_nm": "매출액"}]},
        "2026": {"status": "013", "message": "조회된 데이터가 없습니다."},
        "2027": {"status": "020", "message": "요청 제한"},
    }
    calls = []

    class Response:
        def __init__(self, body):
            self.body = body

        def json(self):
            return self.body

    def fake_get(endpoint, params, timeout=60):
        calls.append(params["bsns_year"])
        return Response(responses[params["bsns_year"]])

    monkeypatch.setattr("src.ingestion.dart_client._get", fake_get)

    first = fetch_major_accounts("001", 2025, tmp_path)
    again = fetch_major_accounts("001", 2025, tmp_path)
    missing = fetch_major_accounts("001", 2026, tmp_path)

    assert first == again == [{"account_nm": "매출액"}]
    assert calls == ["2025", "2026"]
    assert missing == []
    assert not (tmp_path / "001_2026.json").exists()
    try:
        fetch_major_accounts("001", 2027, tmp_path)
    except RuntimeError as exc:
        assert "020" in str(exc)
    else:
        raise AssertionError("OpenDART 오류 응답은 RuntimeError여야 한다")


def test_run_market_research_attaches_financials_for_searched_companies(monkeypatch):
    dart_hit = {"source_type": "dart", "publisher": "두산로보틱스 (DART 사업보고서)"}
    monkeypatch.setattr(market_service, "search_scope", lambda c, i: "범위")
    monkeypatch.setattr(
        market_service,
        "search_with_relevance",
        lambda *a, **k: {"demand": {"hits": [dart_hit]}},
    )
    monkeypatch.setattr(
        market_service,
        "build_report",
        lambda *a: MarketReport(status="no_results", search_scope="범위"),
    )
    request = MarketSearchRequest(
        idea=StructuredIdea(
            title="협동로봇", problem="인력 부족", technology="협동로봇"
        )
    )
    received = []

    def fake_financials(companies, as_of):
        received.append((companies, as_of))
        return build_company_financials([], as_of)

    def broken(companies, as_of):
        raise RuntimeError("boom")

    report = market_service.run_market_research(
        request, collection=object(), data_as_of=20261029, financials_fn=fake_financials
    )
    failed = market_service.run_market_research(
        request, collection=object(), financials_fn=broken
    )

    assert received == [(["두산로보틱스"], 20261029)]
    assert report.company_financials.status == "no_companies"
    assert failed.company_financials.status == "error"
