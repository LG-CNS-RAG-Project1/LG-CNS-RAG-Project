"""조달청 나라장터 입찰공고정보서비스(공공데이터포털)에서 공고명에 주제어가 들어간 입찰공고를 조회한다.

- 인증: .env의 DATA_GO_KR_SERVICE_KEY (공공데이터포털 일반 인증키, Decoding 값)
- API는 한 요청의 조회 기간을 약 1개월로 제한해, 한 달·한 공고 종류(물품·용역)·한 주제어 단위로 조회한다.
- 공고에는 담당 공무원 이름·전화·이메일이 있어, 저장·반환은 NOTICE_FIELDS의 공고 정보만 남긴다.
- 끝난 달의 결과는 data/market/procurement/에 캐시해 다시 호출하지 않는다.

사용 예:
    python -m src.ingestion.procurement_client 협동로봇 202609
"""

import argparse
import hashlib
import json
import os
import time
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT_DIR / "configs" / "procurement.yaml"
CACHE_DIR = ROOT_DIR / "data" / "market" / "procurement"
# 저장·반환하는 공고 필드 (담당자 이름·연락처 등 개인정보는 넣지 않는다)
NOTICE_FIELDS = (
    "bidNtceNo",  # 공고번호
    "bidNtceOrd",  # 공고차수
    "bidNtceNm",  # 공고명
    "bidNtceDt",  # 공고일시
    "ntceKindNm",  # 공고종류 (등록·재공고·취소 등)
    "dminsttNm",  # 수요기관
    "asignBdgtAmt",  # 배정예산
    "presmptPrce",  # 추정가격
    "dtilPrdctClsfcNoNm",  # 세부품명
    "cntrctCnclsMthdNm",  # 계약체결방법 (일반·제한경쟁, 수의 등)
    "sucsfbidMthdNm",  # 낙찰방법
    "bidNtceDtlUrl",  # 공고 상세 URL
)
NO_DATA_CODE = "03"  # 데이터 없음


def load_procurement_config(path: Path = CONFIG_PATH) -> dict:
    """입찰공고 조회 설정(YAML)을 읽는다."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _service_key() -> str:
    load_dotenv(ROOT_DIR / ".env")
    key = os.getenv("DATA_GO_KR_SERVICE_KEY")
    if not key:
        raise RuntimeError("DATA_GO_KR_SERVICE_KEY is not set in .env")
    return key


def _month_range(month: str) -> tuple[str, str]:
    """'YYYYMM' → API 조회 기간 ('YYYYMM010000', 'YYYYMM말일2359')."""
    import calendar

    year, mon = int(month[:4]), int(month[4:])
    return f"{month}010000", f"{month}{calendar.monthrange(year, mon)[1]:02d}2359"


def _request_page(url: str, params: dict, timeout: int) -> dict:
    """한 페이지를 조회해 응답 body를 반환한다. 오류 응답은 결과 코드·메시지로 RuntimeError를 낸다.

    인증키가 URL에 들어가므로 오류 메시지에는 URL을 넣지 않는다.
    """
    try:
        response = requests.get(url, params=params, timeout=timeout)
    except requests.RequestException as exc:
        raise RuntimeError(
            f"나라장터 입찰공고 요청 실패: {type(exc).__name__}"
        ) from None
    try:
        payload = response.json()
    except ValueError:
        raise RuntimeError(f"나라장터 입찰공고 HTTP {response.status_code}") from None
    if "response" not in payload:
        header = next(iter(payload.values()), {})
        header = header.get("header") or header.get("cmmMsgHeader") or {}
        code = header.get("resultCode") or header.get("returnReasonCode")
        message = header.get("resultMsg") or header.get("errMsg")
        raise RuntimeError(f"나라장터 입찰공고 오류 {code}: {message}")
    header = payload["response"]["header"]
    if header.get("resultCode") not in ("00", NO_DATA_CODE):
        raise RuntimeError(
            f"나라장터 입찰공고 오류 {header.get('resultCode')}: {header.get('resultMsg')}"
        )
    return payload["response"].get("body") or {}


def fetch_bid_notices(
    keyword: str,
    kind: str,
    month: str,
    config: dict | None = None,
    cache_dir: Path | None = CACHE_DIR,
) -> list[dict]:
    """한 달(YYYYMM)·한 공고 종류(물품·용역)에서 공고명에 keyword가 들어간 입찰공고를 반환한다.

    공고마다 NOTICE_FIELDS만 남긴 dict이며, 공고 종류는 'kind' 키로 붙인다. max_pages까지 넘긴다.
    """
    config = config or load_procurement_config()
    api = config["api"]
    cache_path = None
    if cache_dir is not None:
        digest = hashlib.sha1(keyword.encode("utf-8")).hexdigest()[:12]
        cache_path = cache_dir / f"{month}_{kind}_{digest}.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))

    begin, end = _month_range(month)
    params = {
        "serviceKey": _service_key(),
        "numOfRows": api["num_of_rows"],
        "type": "json",
        "inqryDiv": "1",
        "inqryBgnDt": begin,
        "inqryEndDt": end,
        "bidNtceNm": keyword,
    }
    url = f"{api['url']}/{api['operations'][kind]}"
    notices = []
    for page in range(1, api["max_pages"] + 1):
        body = _request_page(url, {**params, "pageNo": page}, api["timeout_sec"])
        items = body.get("items") or []
        notices += [
            {**{f: item.get(f, "") for f in NOTICE_FIELDS}, "kind": kind}
            for item in items
        ]
        if page * api["num_of_rows"] >= int(body.get("totalCount") or 0):
            break
        time.sleep(api["request_interval_sec"])
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(notices, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return notices


def main() -> None:
    """주제어 1개의 한 달 물품·용역 입찰공고 수와 앞 5건을 출력한다."""
    parser = argparse.ArgumentParser(description="나라장터 입찰공고 조회")
    parser.add_argument("keyword", help="공고명에 들어갈 주제어")
    parser.add_argument("month", help="조회할 달 YYYYMM")
    args = parser.parse_args()

    config = load_procurement_config()
    for kind in config["api"]["operations"]:
        notices = fetch_bid_notices(args.keyword, kind, args.month, config)
        print(f"{kind}: {len(notices)}건")
        for n in notices[:5]:
            print(f"  {n['bidNtceDt'][:10]} {n['dminsttNm']} | {n['bidNtceNm']}")


if __name__ == "__main__":
    main()
