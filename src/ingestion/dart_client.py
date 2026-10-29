"""OpenDART에서 설정한 기업의 최신 사업보고서 원문을 내려받아 원본 파일로 저장한다.

- 기업 목록·선정 이유·관련 아이디어: configs/dart_companies.yaml
- 고유번호(corp_code) 목록은 corpCode.xml을 한 번 내려받아 data/market/raw/dart/corp_codes.json에 캐시한다.
- 기업마다 date_from 이후 접수된 사업보고서 중 최신 사업연도를 고르고, 같은 사업연도에
  기재정정 보고서가 있으면 가장 늦게 접수된 보고서를 쓴다.
- 저장: data/market/raw/dart/{rcept_no}.xml (본문) + {rcept_no}.json (기업·보고서 메타데이터)
- '사업의 내용' 추출·청크·MarketDocument 변환은 dart_processor에서 수행한다.
- 사업보고서 주요 재무 계정(fetch_major_accounts)은 data/market/raw/dart/financials/에 캐시한다.

OpenDART는 인증키를 URL 파라미터로 받으므로, 오류 메시지에 요청 URL을 넣지 않는다.

사용 예:
    python -m src.ingestion.dart_client
    python -m src.ingestion.dart_client --stock-code 454910
"""

import argparse
import io
import json
import os
import re
import time
import xml.etree.ElementTree as ET
import zipfile
from datetime import date
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

DART_API_URL = "https://opendart.fss.or.kr/api"
ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT_DIR / "configs" / "dart_companies.yaml"
RAW_DIR = ROOT_DIR / "data" / "market" / "raw" / "dart"
CORP_CODES_PATH = RAW_DIR / "corp_codes.json"
FINANCIALS_DIR = RAW_DIR / "financials"
ANNUAL_REPORT_CODE = "11011"  # 사업보고서
NO_DATA_STATUS = "013"  # 조회된 데이터 없음

# '사업보고서 (2025.12)' → 사업연도 말 '2025.12'
_PERIOD_RE = re.compile(r"\((\d{4})\.(\d{2})\)")


def load_dart_config(path: Path = CONFIG_PATH) -> dict:
    """DART 수집 설정을 읽고 기업 항목의 필수 값(stock_code·idea_ids·reason)을 확인한다."""
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    codes = [c["stock_code"] for c in config["companies"]]
    if len(codes) != len(set(codes)):
        raise ValueError("Duplicate stock_code in dart_companies.yaml")
    for company in config["companies"]:
        if not company.get("idea_ids") or not company.get("reason"):
            raise ValueError(f"{company['name']}: idea_ids and reason are required")
    return config


def _get_api_key() -> str:
    """.env의 DART_API_KEY를 읽는다. 값이 없으면 RuntimeError를 발생시킨다."""
    load_dotenv(ROOT_DIR / ".env")
    key = os.getenv("DART_API_KEY")
    if not key:
        raise RuntimeError("DART_API_KEY is not set in .env")
    return key


def _get(endpoint: str, params: dict, timeout: int = 60) -> requests.Response:
    """OpenDART 엔드포인트를 호출한다. 오류 메시지에는 URL(인증키 포함)을 넣지 않는다."""
    try:
        response = requests.get(
            f"{DART_API_URL}/{endpoint}",
            params={"crtfc_key": _get_api_key(), **params},
            timeout=timeout,
        )
    except requests.RequestException as exc:
        raise RuntimeError(
            f"OpenDART {endpoint} 요청 실패: {type(exc).__name__}"
        ) from None
    if response.status_code != 200:
        raise RuntimeError(f"OpenDART {endpoint} HTTP {response.status_code}")
    return response


def _api_error(endpoint: str, content: bytes) -> RuntimeError:
    """zip 대신 돌아온 OpenDART 오류 응답(JSON 또는 XML)을 상태 코드·메시지로 바꾼다."""
    text = content.decode("utf-8", errors="replace")
    try:
        body = json.loads(text)
        status, message = body.get("status"), body.get("message")
    except ValueError:
        status_match = re.search(r"<status>(.*?)</status>", text)
        message_match = re.search(r"<message>(.*?)</message>", text)
        status = status_match.group(1) if status_match else "?"
        message = message_match.group(1) if message_match else text[:100]
    return RuntimeError(f"OpenDART {endpoint} error {status}: {message}")


def _unzip(endpoint: str, content: bytes) -> zipfile.ZipFile:
    """zip 응답을 연다. zip이 아니면 OpenDART 오류 응답으로 보고 RuntimeError를 발생시킨다."""
    try:
        return zipfile.ZipFile(io.BytesIO(content))
    except zipfile.BadZipFile:
        raise _api_error(endpoint, content) from None


def load_corp_codes(path: Path = CORP_CODES_PATH, refresh: bool = False) -> dict:
    """상장사 종목코드 → {corp_code, corp_name} 사전을 반환한다. 캐시가 없으면 내려받아 저장한다."""
    if path.exists() and not refresh:
        return json.loads(path.read_text(encoding="utf-8"))
    archive = _unzip("corpCode.xml", _get("corpCode.xml", {}).content)
    root = ET.fromstring(archive.read(archive.namelist()[0]))
    codes = {
        e.findtext("stock_code").strip(): {
            "corp_code": e.findtext("corp_code"),
            "corp_name": e.findtext("corp_name"),
        }
        for e in root.iter("list")
        if (e.findtext("stock_code") or "").strip()
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(codes, ensure_ascii=False), encoding="utf-8")
    return codes


def report_period(report_nm: str) -> str | None:
    """보고서명에서 사업연도 말(예: '2025.12')을 꺼낸다. 없으면 None."""
    match = _PERIOD_RE.search(report_nm)
    return f"{match.group(1)}.{match.group(2)}" if match else None


def pick_latest_report(reports: list[dict]) -> dict | None:
    """공시 목록에서 최신 사업연도의 보고서를 고르고, 기재정정이 있으면 가장 늦게 접수된 것을 쓴다."""
    dated = [r for r in reports if report_period(r["report_nm"])]
    if not dated:
        return None
    latest = max(report_period(r["report_nm"]) for r in dated)
    same_period = [r for r in dated if report_period(r["report_nm"]) == latest]
    return max(same_period, key=lambda r: (r["rcept_dt"], r["rcept_no"]))


def find_latest_report(corp_code: str, date_from: int, detail_type: str) -> dict:
    """기업의 사업보고서 공시 목록을 조회해 최신 사업연도 보고서 1건을 반환한다.

    해당 기간에 보고서가 없거나 조회가 실패하면 RuntimeError를 발생시킨다.
    """
    body = _get(
        "list.json",
        {
            "corp_code": corp_code,
            "bgn_de": str(date_from),
            "pblntf_detail_ty": detail_type,
            "page_count": 100,
        },
    ).json()
    if body.get("status") != "000":
        raise RuntimeError(
            f"OpenDART list.json error {body.get('status')}: {body.get('message')}"
        )
    report = pick_latest_report(body.get("list", []))
    if report is None:
        raise RuntimeError(f"{corp_code}: 사업보고서 없음")
    return report


def download_document(rcept_no: str) -> str:
    """접수번호의 공시 원문 zip을 내려받아 본문 XML({rcept_no}.xml, 첨부 제외) 문자열을 반환한다."""
    archive = _unzip(
        "document.xml", _get("document.xml", {"rcept_no": rcept_no}, 120).content
    )
    names = archive.namelist()
    main = (
        f"{rcept_no}.xml"
        if f"{rcept_no}.xml" in names
        else max(names, key=lambda n: archive.getinfo(n).file_size)
    )
    return archive.read(main).decode("utf-8", errors="replace")


def fetch_major_accounts(
    corp_code: str, year: int, cache_dir: Path | None = FINANCIALS_DIR
) -> list[dict]:
    """사업연도 사업보고서의 주요 재무 계정(fnlttSinglAcnt) 목록을 반환한다. 공시가 없으면 빈 목록.

    받은 목록은 {corp_code}_{year}.json으로 캐시해 다시 호출하지 않는다. 빈 목록은 캐시하지 않는다.
    OpenDART 오류 응답은 상태 코드·메시지로 RuntimeError를 낸다.
    """
    cache_path = cache_dir / f"{corp_code}_{year}.json" if cache_dir else None
    if cache_path is not None and cache_path.exists():
        return json.loads(cache_path.read_text(encoding="utf-8"))
    body = _get(
        "fnlttSinglAcnt.json",
        {
            "corp_code": corp_code,
            "bsns_year": str(year),
            "reprt_code": ANNUAL_REPORT_CODE,
        },
        30,
    ).json()
    if body.get("status") == NO_DATA_STATUS:
        return []
    if body.get("status") != "000":
        raise RuntimeError(
            f"OpenDART fnlttSinglAcnt error {body.get('status')}: {body.get('message')}"
        )
    accounts = body.get("list", [])
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(accounts, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return accounts


def collect_company(
    company: dict, corp_codes: dict, report_config: dict, raw_dir: Path = RAW_DIR
) -> dict:
    """기업 1곳의 최신 사업보고서를 내려받아 본문 XML과 메타데이터 JSON을 저장하고 메타데이터를 반환한다."""
    corp = corp_codes.get(company["stock_code"])
    if corp is None:
        raise RuntimeError(f"{company['name']}: 종목코드 {company['stock_code']} 없음")
    report = find_latest_report(
        corp["corp_code"], report_config["date_from"], report_config["detail_type"]
    )
    rcept_no = report["rcept_no"]
    raw_dir.mkdir(parents=True, exist_ok=True)
    (raw_dir / f"{rcept_no}.xml").write_text(
        download_document(rcept_no), encoding="utf-8"
    )
    meta = {
        "name": company["name"],
        "stock_code": company["stock_code"],
        "corp_code": corp["corp_code"],
        "corp_name": corp["corp_name"],
        "idea_ids": company["idea_ids"],
        "reason": company["reason"],
        "rcept_no": rcept_no,
        "report_nm": " ".join(report["report_nm"].split()),
        "rcept_dt": int(report["rcept_dt"]),
        "period": report_period(report["report_nm"]),
        "corrected": "정정" in report["report_nm"],
        "collected_at": int(date.today().strftime("%Y%m%d")),
    }
    (raw_dir / f"{rcept_no}.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return meta


def main() -> None:
    """설정한 기업(또는 --stock-code로 고른 기업)의 최신 사업보고서를 수집한다."""
    parser = argparse.ArgumentParser(description="DART 사업보고서 수집")
    parser.add_argument(
        "--stock-code", action="append", help="수집할 종목코드 (반복 가능)"
    )
    parser.add_argument(
        "--refresh-codes", action="store_true", help="고유번호 목록 다시 받기"
    )
    args = parser.parse_args()

    config = load_dart_config()
    corp_codes = load_corp_codes(refresh=args.refresh_codes)
    companies = [
        c
        for c in config["companies"]
        if not args.stock_code or c["stock_code"] in args.stock_code
    ]
    failed = 0
    for company in companies:
        try:
            meta = collect_company(company, corp_codes, config["report"])
            print(f"{company['name']}: {meta['report_nm']} ({meta['rcept_no']})")
        except RuntimeError as exc:
            failed += 1
            print(f"{company['name']}: 실패 - {exc}")
        time.sleep(config["report"]["request_interval_sec"])
    print(f"collected {len(companies) - failed}/{len(companies)}")
    if failed:
        raise SystemExit(1)


if __name__ == "__main__":
    main()
