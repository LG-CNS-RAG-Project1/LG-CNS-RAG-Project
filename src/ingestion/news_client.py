"""네이버 뉴스 검색 API로 시장 키워드별 기사 목록을 수집해 원본 JSON으로 저장한다.

- NAVER API HUB(네이버클라우드) 뉴스 검색 엔드포인트와 Application 인증키를 사용한다.
- 제목·요약·링크·발행일만 저장하며 기사 본문은 크롤링하지 않는다.
- 저장 위치: data/market/raw/news_{keyword_id}_{수집일}.json
- MarketDocument 변환·중복 그룹 지정은 market_processor에서 수행한다.

사용 예:
    python -m src.ingestion.news_client --keyword-id smart_factory --max-items 10
"""

import argparse
import hashlib
import html
import json
import os
import re
import time
from datetime import datetime
from email.utils import parsedate_to_datetime
from pathlib import Path
from urllib.parse import urlparse

import requests
import yaml
from dotenv import load_dotenv

NAVER_NEWS_URL = "https://naverapihub.apigw.ntruss.com/search/v1/news"
MAX_DISPLAY = 100
MAX_START = 1000

ROOT_DIR = Path(__file__).resolve().parents[2]
KEYWORDS_PATH = ROOT_DIR / "configs" / "market_keywords.yaml"
RAW_DIR = ROOT_DIR / "data" / "market" / "raw"

_TAG_RE = re.compile(r"<[^>]+>")


def load_keyword_config(path: Path = KEYWORDS_PATH) -> dict:
    """키워드 설정 YAML을 읽어 news 설정과 keywords 목록을 반환한다."""
    with open(path, encoding="utf-8") as f:
        config = yaml.safe_load(f)
    ids = [k["id"] for k in config["keywords"]]
    if len(ids) != len(set(ids)):
        raise ValueError("Duplicate keyword ids in market_keywords.yaml")
    return config


def _get_credentials() -> tuple[str, str]:
    """.env에서 NAVER API HUB Application의 Client ID·Secret을 읽는다.

    값이 없으면 RuntimeError를 발생시킨다.
    """
    load_dotenv(ROOT_DIR / ".env")
    client_id = os.getenv("NAVER_CLIENT_ID")
    client_secret = os.getenv("NAVER_CLIENT_SECRET")
    if not client_id or not client_secret:
        raise RuntimeError("NAVER_CLIENT_ID / NAVER_CLIENT_SECRET is not set in .env")
    return client_id, client_secret


def clean_text(value: str) -> str:
    """검색 결과의 <b> 태그와 HTML 엔티티를 제거한다."""
    return html.unescape(_TAG_RE.sub("", value or "")).strip()


def to_yyyymmdd(pub_date: str) -> int:
    """RFC 1123 형식의 pubDate(예: 'Tue, 21 Oct 2026 09:00:00 +0900')를 YYYYMMDD 정수로 변환한다."""
    return int(parsedate_to_datetime(pub_date).strftime("%Y%m%d"))


def make_source_id(url: str) -> str:
    """URL 기반의 고정 source_id를 만든다. 같은 기사는 재수집해도 같은 ID를 갖는다."""
    return "news-" + hashlib.sha1(url.encode("utf-8")).hexdigest()[:12]


def search_news(
    query: str, display: int = MAX_DISPLAY, start: int = 1, sort: str = "date"
) -> dict:
    """네이버 뉴스 검색 API를 1회 호출해 응답 JSON을 반환한다.

    API 오류 시 게이트웨이 오류 코드·메시지를 포함한 RuntimeError를 발생시킨다.
    """
    client_id, client_secret = _get_credentials()
    response = requests.get(
        NAVER_NEWS_URL,
        headers={
            "X-NCP-APIGW-API-KEY-ID": client_id,
            "X-NCP-APIGW-API-KEY": client_secret,
        },
        params={
            "query": query,
            "display": min(display, MAX_DISPLAY),
            "start": start,
            "sort": sort,
        },
        timeout=10,
    )
    if response.status_code != 200:
        try:
            body = response.json()
        except ValueError:
            body = {}
        error = body.get("error", body)
        message = (
            error.get("message") or error.get("errorMessage") or response.text[:200]
        )
        raise RuntimeError(
            f"Naver news API error {response.status_code}: "
            f"{error.get('errorCode', '')} {message}"
        )
    return response.json()


def normalize_item(item: dict, keyword: dict, collected_at: int) -> dict:
    """API 응답 기사 1건을 원본 저장 형식으로 정리한다. 원문 링크(originallink)를 우선 사용한다."""
    url = item.get("originallink") or item["link"]
    return {
        "source_id": make_source_id(url),
        "title": clean_text(item.get("title", "")),
        "description": clean_text(item.get("description", "")),
        "url": url,
        "naver_link": item.get("link"),
        "domain": urlparse(url).netloc,
        "published_at": to_yyyymmdd(item["pubDate"]),
        "collected_at": collected_at,
        "keyword_id": keyword["id"],
        "query": keyword["query"],
        "idea_ids": keyword.get("idea_ids", []),
        "dimensions": keyword.get("dimensions", []),
    }


def collect_keyword(
    keyword: dict, settings: dict, max_items: int | None = None
) -> list[dict]:
    """키워드 1개의 기사를 페이지 단위로 수집한다.

    - 같은 URL은 1건만 남긴다.
    - date_from 이전 기사는 제외하며, 최신순(sort=date)이면 해당 시점에서 수집을 멈춘다.
    - 결과 수는 max_items(미지정 시 설정값)와 API 조회 한도(start ≤ 1000) 안으로 제한된다.
    """
    sort = settings.get("sort", "date")
    display = settings.get("display", MAX_DISPLAY)
    date_from = settings.get("date_from")
    interval = settings.get("request_interval_sec", 0.2)
    limit = max_items or settings.get("max_items_per_keyword", MAX_DISPLAY)
    collected_at = int(datetime.now().strftime("%Y%m%d"))

    records: dict[str, dict] = {}
    start = 1
    while len(records) < limit and start <= MAX_START:
        data = search_news(
            keyword["query"], display=min(display, limit), start=start, sort=sort
        )
        items = data.get("items", [])
        if not items:
            break

        reached_old = False
        for item in items:
            record = normalize_item(item, keyword, collected_at)
            if date_from and record["published_at"] < date_from:
                reached_old = True
                continue
            records.setdefault(record["url"], record)
            if len(records) >= limit:
                break

        if (reached_old and sort == "date") or start + len(items) > data.get(
            "total", 0
        ):
            break
        start += len(items)
        time.sleep(interval)

    return list(records.values())


def save_raw(keyword: dict, records: list[dict], raw_dir: Path = RAW_DIR) -> Path:
    """수집 결과를 키워드·수집일 단위 JSON 파일로 저장하고 경로를 반환한다. 같은 날 재실행 시 덮어쓴다."""
    raw_dir.mkdir(parents=True, exist_ok=True)
    collected_at = (
        records[0]["collected_at"]
        if records
        else int(datetime.now().strftime("%Y%m%d"))
    )
    path = raw_dir / f"news_{keyword['id']}_{collected_at}.json"
    payload = {
        "source": "naver_news_search",
        "keyword": keyword,
        "collected_at": collected_at,
        "count": len(records),
        "items": records,
    }
    with open(path, "w", encoding="utf-8") as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    return path


def main() -> None:
    """--keyword-id로 지정한 키워드(미지정 시 전체)를 수집해 data/market/raw/에 저장한다."""
    parser = argparse.ArgumentParser(description="네이버 뉴스 시장 자료 수집")
    parser.add_argument(
        "--keyword-id", help="market_keywords.yaml의 키워드 id (미지정 시 전체)"
    )
    parser.add_argument("--max-items", type=int, help="키워드당 최대 기사 수")
    args = parser.parse_args()

    config = load_keyword_config()
    keywords = config["keywords"]
    if args.keyword_id:
        keywords = [k for k in keywords if k["id"] == args.keyword_id]
        if not keywords:
            raise SystemExit(f"Unknown keyword id: {args.keyword_id}")

    for keyword in keywords:
        records = collect_keyword(keyword, config["news"], max_items=args.max_items)
        path = save_raw(keyword, records)
        print(f"[{keyword['id']}] {len(records)} items -> {path.relative_to(ROOT_DIR)}")


if __name__ == "__main__":
    main()
