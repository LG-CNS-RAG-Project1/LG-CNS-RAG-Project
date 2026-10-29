"""NAVER API HUB 검색어 트렌드(Search Trend)로 주제어 그룹의 월별 상대 검색량을 조회한다.

- 인증: .env의 NAVER_TREND_CLIENT_ID·NAVER_TREND_CLIENT_SECRET (뉴스 검색 키와 별도 Application)
- 응답 ratio는 한 요청 안 모든 그룹·기간의 최댓값을 100으로 둔 상대값이다. 다른 요청의 값과 비교하지 않는다.
- 같은 요청(그룹·기간)은 조회한 날짜 기준으로 data/market/trends/에 캐시해 같은 날 다시 호출하지 않는다.

사용 예:
    python -m src.ingestion.trend_client 협동로봇 코봇
"""

import argparse
import hashlib
import json
import os
from datetime import date
from pathlib import Path

import requests
import yaml
from dotenv import load_dotenv

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT_DIR / "configs" / "search_trend.yaml"
CACHE_DIR = ROOT_DIR / "data" / "market" / "trends"


def load_trend_config(path: Path = CONFIG_PATH) -> dict:
    """검색어 트렌드 설정(YAML)을 읽는다."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def _credentials() -> tuple[str, str]:
    load_dotenv(ROOT_DIR / ".env")
    client_id = os.getenv("NAVER_TREND_CLIENT_ID")
    client_secret = os.getenv("NAVER_TREND_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError(
            "NAVER_TREND_CLIENT_ID / NAVER_TREND_CLIENT_SECRET is not set in .env"
        )
    return client_id, client_secret


def fetch_search_trend(
    groups: list[dict],
    start_date: str,
    end_date: str,
    config: dict | None = None,
    cache_dir: Path | None = CACHE_DIR,
) -> dict[str, dict[str, float]]:
    """주제어 그룹의 월별 상대 검색량을 {그룹명: {YYYY-MM: ratio}}로 반환한다.

    groups: [{"groupName": 이름, "keywords": [주제어, ...]}]. 검색량이 없는 달은 결과에 빠진다.
    API 오류는 상태 코드와 응답 메시지로 RuntimeError를 낸다 (인증키는 메시지에 넣지 않는다).
    """
    config = config or load_trend_config()
    body = {
        "startDate": start_date,
        "endDate": end_date,
        "timeUnit": config["api"]["time_unit"],
        "keywordGroups": groups,
    }
    payload = json.dumps(body, ensure_ascii=False, sort_keys=True)
    cache_path = None
    if cache_dir is not None:
        digest = hashlib.sha1(payload.encode("utf-8")).hexdigest()[:16]
        cache_path = cache_dir / f"{date.today():%Y%m%d}_{digest}.json"
        if cache_path.exists():
            return json.loads(cache_path.read_text(encoding="utf-8"))

    client_id, client_secret = _credentials()
    response = requests.post(
        config["api"]["url"],
        headers={
            "X-NCP-APIGW-API-KEY-ID": client_id,
            "X-NCP-APIGW-API-KEY": client_secret,
            "Content-Type": "application/json",
        },
        data=payload.encode("utf-8"),
        timeout=config["api"]["timeout_sec"],
    )
    if response.status_code != 200:
        raise RuntimeError(
            f"search trend API {response.status_code}: {response.text[:200]}"
        )
    series = {
        result["title"]: {p["period"][:7]: float(p["ratio"]) for p in result["data"]}
        for result in response.json()["results"]
    }
    if cache_path is not None:
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text(
            json.dumps(series, ensure_ascii=False, indent=1), encoding="utf-8"
        )
    return series


def main() -> None:
    """주제어 1그룹을 기준 주제어와 함께 최근 24개월 조회해 월별 값을 출력한다."""
    parser = argparse.ArgumentParser(description="네이버 검색어 트렌드 조회")
    parser.add_argument("keywords", nargs="+", help="한 그룹으로 묶을 주제어")
    args = parser.parse_args()

    from src.services.market_trend import period_range

    config = load_trend_config()
    start, end = period_range(date.today(), config["months"])
    reference = config["reference"]
    series = fetch_search_trend(
        [
            {"groupName": reference["name"], "keywords": reference["keywords"]},
            {"groupName": "주제어", "keywords": args.keywords},
        ],
        start,
        end,
        config,
    )
    for name, values in series.items():
        print(name, " ".join(f"{m}:{v:.1f}" for m, v in values.items()))


if __name__ == "__main__":
    main()
