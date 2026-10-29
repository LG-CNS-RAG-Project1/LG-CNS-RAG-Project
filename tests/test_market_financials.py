from src.generation.market_markdown import (
    company_financial_rows,
    company_financials_summary,
    market_report_to_markdown,
)
from src.ingestion.dart_client import fetch_major_accounts
from src.ingestion.dart_processor import extract_rnd_expense
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


def account(fs_div, name, current, previous, before, rcept_no="20260310000001"):
    return {
        "fs_div": fs_div,
        "account_nm": name,
        "rcept_no": rcept_no,
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
    account("OFS", "매출액", "25,620,442,016", "20,000,000,000", "", "2"),
    account("OFS", "영업이익", "2,562,044,201", "1,000,000,000", "", "2"),
    account("OFS", "당기순이익(손실)", "1,000,000,000", "", "", "2"),
]


def table(*rows):
    return (
        "<TABLE>"
        + "".join(
            "<TR>" + "".join(f"<TD>{cell}</TD>" for cell in row) + "</TR>"
            for row in rows
        )
        + "</TABLE>"
    )


def rnd_section(body):
    return (
        "<SECTION-1><TITLE>II. 사업의 내용</TITLE>"
        "<SECTION-2><TITLE>6. 주요계약 및 연구개발활동</TITLE>"
        f"{body}</SECTION-2></SECTION-1>"
    )


# 주요계약 표가 먼저 나오고, 단위는 단위만 적은 작은 표에 있으며, 차감 전 총계와 차감 후 계가 함께 있다.
GROSS_AND_NET_XML = rnd_section(
    table(["계약 상대방", "계약금액"], ["합계", "1,000"], ["", "2,000"], ["", "3,000"])
    + table(["합계", "1,000", "2,000", "3,000"])
    + "<P>[최근 3개 사업연도 연구개발 비용 현황]</P>"
    + table(["(단위 : 백만원, %)"])
    + table(
        ["구분", "2025년 (제16기)", "2024년 (제15기)", "2023년 (제14기)"],
        ["연구개발비용 총계", "12,445", "12,714", "9,298"],
        ["(정부보조금)", "(3,937)", "(1,985)", "(1,675)"],
        ["연구개발비용 계", "8,508", "10,729", "7,623"],
        ["연구개발비 / 매출액 비율", "6%", "6%", "83%"],
    )
)
# 표 안에는 '연구개발'이 없고 바로 위 제목에만 있으며, 합계 칸에 비율이 함께 적혀 있다.
HEADING_ONLY_XML = rnd_section(
    "<P>(2) 연구개발비용 (단위:천원)</P>"
    + table(
        ["구 분", "제21기", "제20기", "제19기"],
        ["판관비", "1,016,506", "2,009,210", "1,548,313"],
        [
            "합 계 (매출액 대비 비율)",
            "1,016,506(4.0%)",
            "2,009,210(6.8%)",
            "1,548,313(6.4%)",
        ],
    )
)
NO_UNIT_XML = rnd_section(table(["연구개발비용 계", "1", "2", "3"]))
DOCUMENTS = {"20260310000001": GROSS_AND_NET_XML, "2": "<SECTION-1></SECTION-1>"}


def test_extract_rnd_expense_prefers_gross_total_and_converts_units():
    amounts, basis = extract_rnd_expense(GROSS_AND_NET_XML, 2025)
    heading_only = extract_rnd_expense(HEADING_ONLY_XML, 2025)

    assert amounts == {
        2025: 12_445_000_000,
        2024: 12_714_000_000,
        2023: 9_298_000_000,
    }
    assert basis == "사업보고서 연구개발활동 표 '연구개발비용총계' (백만원)"
    assert heading_only[0] == {
        2025: 1_016_506_000,
        2024: 2_009_210_000,
        2023: 1_548_313_000,
    }
    assert extract_rnd_expense(NO_UNIT_XML, 2025) is None
    assert extract_rnd_expense("<SECTION-1></SECTION-1>", 2025) is None


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
        document_fn=DOCUMENTS.get,
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
        DOCUMENTS.get,
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
        "연구개발비 2025": "124",
        "연구개발비 비율": "37.7%",
    }
    assert rows[1]["연구개발비 2025"] == "-"
    assert (
        financials.companies[1].rnd_basis
        == "사업보고서에서 연구개발비용 표를 찾지 못함"
    )
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
    assert "- 연구개발비 근거(두산로보틱스): 사업보고서 연구개발활동 표" in markdown
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


def test_financial_chart_rows_and_chart():
    from frontend.market_financials_view import financial_chart, financial_chart_rows

    financials = build_company_financials(
        ["두산로보틱스", "엠아이큐브솔루션"],
        20261029,
        lambda corp, year: {"001": DOOSAN, "002": SEPARATE_ONLY}[corp],
        CONFIG,
        CORP_CODES,
        DOCUMENTS.get,
    )

    rows = financial_chart_rows(financials)

    assert rows[0] == {
        "패널": "두산로보틱스 · 영업이익률 -180.3%",
        "연도": "2023",
        "매출액(억원)": 530,
        "영업이익(억원)": None,
        "영업이익": "영업이익 미제공",
    }
    assert rows[2]["영업이익"] == "영업이익 적자"
    assert [r["연도"] for r in rows if r["패널"].startswith("엠아이")] == [
        "2024",
        "2025",
    ]
    assert rows[-1]["영업이익"] == "영업이익 흑자"
    spec = financial_chart(financials, "dark").to_dict()
    assert spec["resolve"]["scale"]["y"] == "independent"
    assert financial_chart(build_company_financials([], 20261029)) is None


def test_rnd_lookup_failure_keeps_financial_accounts():
    def broken(rcept_no):
        raise RuntimeError("OpenDART document.xml HTTP 500")

    result = build_company_financials(
        ["두산로보틱스"], 20261029, lambda c, y: DOOSAN, CONFIG, CORP_CODES, broken
    )

    company = result.companies[0]
    assert result.status == "completed"
    assert company.years[-1].revenue == 32978338354
    assert company.years[-1].rnd_expense is None
    assert company.rnd_basis.startswith("사업보고서 본문 조회 실패")
