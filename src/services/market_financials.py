"""시장 검색에서 고른 DART 기업의 최근 3개 사업연도 재무 현황(MarketCompanyFinancials)을 만든다.

1. 차원별 검색에 들어온 DART 기업명을 configs/dart_companies.yaml의 종목코드로 바꾼다.
2. 기준일 직전 사업연도 사업보고서의 주요 재무 계정(OpenDART fnlttSinglAcnt)을 조회하고, 아직
   공시되지 않았으면 그 전 사업연도를 쓴다 (src/ingestion/dart_client.py).
3. 연결재무제표가 있으면 연결, 없으면 별도재무제표의 매출액·영업이익·당기순이익을 3개 연도로 정리한다.

기업 매출은 그 기업의 실적일 뿐 시장 규모·구매 수요의 근거가 아니며, 차원별 판정에 쓰지 않는다.
"""

from typing import Callable

from src.ingestion.dart_client import (
    fetch_major_accounts,
    load_corp_codes,
    load_dart_config,
)
from src.schemas import (
    DartCompanyFinancials,
    DartFinancialYear,
    MarketCompanyFinancials,
)

NOTE = (
    "DART 사업보고서의 주요 재무 계정입니다. 아이디어와 같은 사업 범주로 검색한 기업의 실적이며, "
    "시장 규모나 고객 수요의 근거가 아닙니다."
)
ACCOUNTS = {
    "매출액": "revenue",
    "영업이익": "operating_income",
    "당기순이익": "net_income",
}
# 사업보고서 계정의 당기·전기·전전기 금액 필드와 기준 사업연도로부터의 차이
PERIOD_FIELDS = [("bfefrmtrm_amount", 2), ("frmtrm_amount", 1), ("thstrm_amount", 0)]

FetchFn = Callable[[str, int], list[dict]]


def parse_amount(value) -> int | None:
    """'32,978,338,354'·'-1,234' 같은 공시 금액 문자열을 정수로 바꾼다. 비었거나 '-'면 None."""
    text = str(value or "").replace(",", "").strip()
    if not text or text == "-":
        return None
    try:
        return int(text)
    except ValueError:
        return None


def account_name(account: dict) -> str:
    """계정명에서 공백과 '(손실)' 표기를 뺀다 (당기순이익(손실) → 당기순이익)."""
    return "".join(str(account.get("account_nm", "")).split()).removesuffix("(손실)")


def summarize_accounts(
    accounts: list[dict], year: int
) -> tuple[str, str, list[DartFinancialYear]] | None:
    """주요 재무 계정 목록을 (재무제표 구분, 접수번호, 3개 연도 실적)으로 정리한다.

    연결(CFS) 계정이 있으면 연결, 없으면 별도(OFS)를 쓴다. 매출액이 없으면 None.
    """
    for fs_div, statement in (("CFS", "연결"), ("OFS", "별도")):
        rows = {
            ACCOUNTS[account_name(a)]: a
            for a in accounts
            if a.get("fs_div") == fs_div and account_name(a) in ACCOUNTS
        }
        if "revenue" not in rows:
            continue
        years = [
            DartFinancialYear(
                year=year - back,
                **{field: parse_amount(row.get(column)) for field, row in rows.items()},
            )
            for column, back in PERIOD_FIELDS
        ]
        return statement, rows["revenue"].get("rcept_no", ""), years
    return None


def build_company_financials(
    companies: list[str],
    data_as_of: int,
    fetch_fn: FetchFn = fetch_major_accounts,
    config: dict | None = None,
    corp_codes: dict | None = None,
) -> MarketCompanyFinancials:
    """DART 기업명 목록의 재무 현황을 만든다. 기업이 없으면 no_companies, 조회 실패는 error다.

    설정에 없는 기업이나 공시를 찾지 못한 기업은 missing에 사유와 함께 남긴다.
    """
    if not companies:
        return MarketCompanyFinancials(status="no_companies", note=NOTE)
    try:
        config = config or load_dart_config()
        corp_codes = corp_codes if corp_codes is not None else load_corp_codes()
        by_name = {c["name"]: c for c in config["companies"]}
        last_year = data_as_of // 10000 - 1
        results, missing = [], []
        for name in companies:
            company = by_name.get(name)
            corp = corp_codes.get(company["stock_code"]) if company else None
            if corp is None:
                missing.append(f"{name}: DART 기업 설정 없음")
                continue
            summary = None
            for year in (last_year, last_year - 1):
                summary = summarize_accounts(fetch_fn(corp["corp_code"], year), year)
                if summary:
                    break
            if summary is None:
                missing.append(f"{name}: 최근 사업보고서 재무 계정 없음")
                continue
            statement, rcept_no, years = summary
            results.append(
                DartCompanyFinancials(
                    company=name,
                    stock_code=company["stock_code"],
                    statement=statement,
                    rcept_no=rcept_no,
                    years=years,
                )
            )
    except Exception as exc:  # 재무 조회 실패는 시장 보고서 전체를 막지 않는다
        return MarketCompanyFinancials(
            status="error", error_message=str(exc), note=NOTE
        )
    return MarketCompanyFinancials(
        status="completed", companies=results, missing=missing, note=NOTE
    )
