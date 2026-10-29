"""수집한 시장 뉴스 원본을 정제해 MarketDocument JSONL로 저장한다.

- 입력: data/market/raw/news_*.json (news_client 수집 결과)
- 기사의 idea_ids는 수집 당시 값이 아니라 현재 configs/technology_areas.yaml의 키워드 설정을 따른다.
  설정에 없는 키워드(legacy_market_keywords 등)로 수집한 기사는 제외한다. 원본 파일은 지우지 않는다.
- 같은 URL 기사는 1건으로 합치고, 수집 키워드의 idea_ids를 합친다.
- 제목 유사도가 기준 이상이고 발행일 차이가 기준 이내인 기사는 같은 dup_group으로 묶어
  대표 1건만 저장한다. 대표 기사는 그룹 전체의 idea_ids를 가진다.
- 관련성 판단은 검색 단계에 맡기며, 이 단계에서는 기사를 제외하지 않는다.
- 출력: data/market/processed/market_docs.jsonl

사용 예:
    python -m src.ingestion.market_processor
"""

import argparse
import json
import re
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path

from src.schemas import MarketDocument

ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "data" / "market" / "raw"
OUTPUT_PATH = ROOT_DIR / "data" / "market" / "processed" / "market_docs.jsonl"

TITLE_SIMILARITY = 0.8
DUP_WINDOW_DAYS = 3
NEWS_RELIABILITY = "medium"
NEWS_LICENSE = "네이버 뉴스 검색 API 메타데이터(제목·요약·링크)만 저장"

_NON_WORD_RE = re.compile(r"[\W_]+")


def load_raw_news(raw_dir: Path = RAW_DIR) -> list[dict]:
    """원본 뉴스 JSON 파일들의 기사 목록을 하나로 합쳐 반환한다."""
    records = []
    for path in sorted(raw_dir.glob("news_*.json")):
        with open(path, encoding="utf-8") as f:
            records.extend(json.load(f)["items"])
    return records


def apply_keyword_config(
    records: list[dict], keyword_ideas: dict[str, list[str]]
) -> list[dict]:
    """설정에 있는 키워드로 수집한 기사만 남기고 idea_ids를 그 키워드의 현재 설정으로 바꾼다.

    keyword_ideas: {키워드 ID: 아이디어 ID 목록} (news_client.load_keyword_config 기준)
    """
    return [
        {**record, "idea_ids": keyword_ideas[record["keyword_id"]]}
        for record in records
        if record["keyword_id"] in keyword_ideas
    ]


def current_keyword_ideas() -> dict[str, list[str]]:
    """configs/technology_areas.yaml의 시장 키워드별 아이디어 ID를 반환한다."""
    from src.ingestion.news_client import load_keyword_config

    return {k["id"]: k["idea_ids"] for k in load_keyword_config()["keywords"]}


def merge_by_source_id(records: list[dict]) -> list[dict]:
    """같은 source_id(같은 URL) 기사를 1건으로 합치고 idea_ids·keyword_ids를 합친다."""
    merged: dict[str, dict] = {}
    for record in records:
        item = merged.get(record["source_id"])
        if item is None:
            item = {**record, "idea_ids": set(), "keyword_ids": set()}
            merged[record["source_id"]] = item
        item["idea_ids"].update(record.get("idea_ids", []))
        item["keyword_ids"].add(record["keyword_id"])
    return list(merged.values())


def _normalize_title(title: str) -> str:
    return _NON_WORD_RE.sub("", title).lower()


def _days_between(a: int, b: int) -> int:
    fmt = "%Y%m%d"
    return abs((datetime.strptime(str(a), fmt) - datetime.strptime(str(b), fmt)).days)


def title_similarity(a: str, b: str) -> float:
    """공백·문장부호를 제거한 두 제목의 유사도(0~1)를 반환한다."""
    return SequenceMatcher(None, _normalize_title(a), _normalize_title(b)).ratio()


def group_duplicates(
    records: list[dict],
    threshold: float = TITLE_SIMILARITY,
    window_days: int = DUP_WINDOW_DAYS,
) -> list[list[dict]]:
    """제목 유사도 threshold 초과, 발행일 차이 window_days 이내인 기사를 묶는다.

    유사 관계는 전이적으로 연결된다(A~B, B~C이면 A·B·C가 한 그룹).
    """
    items = sorted(records, key=lambda r: (r["published_at"], r["source_id"]))
    titles = [_normalize_title(r["title"]) for r in items]
    parent = list(range(len(items)))

    def find(i: int) -> int:
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for i in range(len(items)):
        for j in range(i + 1, len(items)):
            if _days_between(items[i]["published_at"], items[j]["published_at"]) > (
                window_days
            ):
                break
            matcher = SequenceMatcher(None, titles[i], titles[j])
            if matcher.real_quick_ratio() <= threshold:
                continue
            if matcher.quick_ratio() <= threshold:
                continue
            if matcher.ratio() > threshold:
                parent[find(j)] = find(i)

    groups: dict[int, list[dict]] = {}
    for i, item in enumerate(items):
        groups.setdefault(find(i), []).append(item)
    return list(groups.values())


def pick_representative(group: list[dict]) -> dict:
    """그룹에서 가장 먼저 발행된 기사를 대표로 고른다. 같으면 요약이 긴 기사를 우선한다."""
    return min(
        group,
        key=lambda r: (r["published_at"], -len(r["description"]), r["source_id"]),
    )


def to_market_document(
    record: dict, dup_group: str, idea_ids: set[str]
) -> MarketDocument:
    """대표 기사 1건을 MarketDocument로 변환한다. 본문 대신 제목과 요약을 text로 사용한다."""
    text = "\n".join(part for part in (record["title"], record["description"]) if part)
    return MarketDocument(
        source_id=record["source_id"],
        source_type="news",
        title=record["title"],
        publisher=record["domain"].removeprefix("www."),
        text=text,
        url=record["url"],
        published_at=record["published_at"],
        collected_at=record["collected_at"],
        section="title+description",
        reliability=NEWS_RELIABILITY,
        evidence_nature="business_signal",
        dup_group=dup_group,
        license=NEWS_LICENSE,
        idea_ids=sorted(idea_ids),
    )


def build_documents(records: list[dict]) -> list[MarketDocument]:
    """원본 기사 목록을 URL 병합·중복 그룹화한 뒤 그룹별 대표 MarketDocument 목록으로 만든다.

    dup_group은 대표 기사의 source_id이며, 결과는 발행일 내림차순으로 정렬된다.
    """
    documents = []
    for group in group_duplicates(merge_by_source_id(records)):
        representative = pick_representative(group)
        idea_ids = set().union(*(r["idea_ids"] for r in group))
        documents.append(
            to_market_document(representative, representative["source_id"], idea_ids)
        )
    return sorted(documents, key=lambda d: (-d.published_at, d.source_id))


def save_documents(documents: list[MarketDocument], path: Path = OUTPUT_PATH) -> Path:
    """MarketDocument 목록을 한 줄에 1건씩 JSONL로 저장한다. 기존 파일은 덮어쓴다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for document in documents:
            f.write(document.model_dump_json() + "\n")
    return path


def main() -> None:
    """data/market/raw/의 뉴스 원본을 정제해 market_docs.jsonl로 저장하고 건수를 출력한다."""
    parser = argparse.ArgumentParser(description="시장 뉴스 정제")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    raw = load_raw_news(args.raw_dir)
    records = apply_keyword_config(raw, current_keyword_ideas())
    documents = build_documents(records)
    path = save_documents(documents, args.output)
    unique = len({r["source_id"] for r in records})
    excluded = sorted(
        {r["keyword_id"] for r in raw} - {r["keyword_id"] for r in records}
    )
    if excluded:
        print(
            f"설정에 없는 키워드 제외: {', '.join(excluded)} ({len(raw) - len(records)}건)"
        )
    print(
        f"raw {len(records)} -> unique url {unique} -> documents {len(documents)} "
        f"({unique - len(documents)} near-duplicates grouped) -> {path}"
    )


if __name__ == "__main__":
    main()
