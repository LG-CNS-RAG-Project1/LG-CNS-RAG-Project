"""시장 근거 검색 평가셋(evaluation/market_cases.json)의 정답 라벨 작업을 돕는다.

- init: data/samples/ideas.json의 아이디어 × 시장 차원 5개로 평가 문항을 만든다.
- export: 문항마다 라벨링 후보를 CSV로 내보낸다.
  후보 = 벡터 검색 상위 VECTOR_POOL건 + 그 아래 순위(최대 TERM_SCAN위)에서 차원 표현이
  들어간 문서 TERM_POOL건. 검색 상위만 라벨링하면 놓친 관련 문서가 드러나지 않기 때문이다.
- extend: 검색 방식(dense·bm25·hybrid)별 상위 EXTEND_TOP_K건 중 아직 후보에 없는 문서를 후보 CSV에
  추가한다. 방식 비교 시 한 방식의 후보만 라벨링되어 있으면 다른 방식이 불리해지기 때문이다.
- import: relevant 열(1/0)을 채운 CSV를 읽어 문항별 relevant_source_ids를 기록한다.

사용 예:
    python -m evaluation.market_labeling init
    python -m evaluation.market_labeling export
    python -m evaluation.market_labeling extend
    python -m evaluation.market_labeling import
"""

import argparse
import csv
import io
import json
import re
from pathlib import Path
from typing import Callable

from src.schemas import ALL_DIMENSIONS, MarketSearchRequest, StructuredIdea

ROOT_DIR = Path(__file__).resolve().parents[1]
IDEAS_PATH = ROOT_DIR / "data" / "samples" / "ideas.json"
CASES_PATH = ROOT_DIR / "evaluation" / "market_cases.json"
CANDIDATES_PATH = ROOT_DIR / "evaluation" / "labels" / "market_candidates.csv"
VECTOR_POOL = 8
TERM_POOL = 4
TERM_SCAN = 60
EXTEND_TOP_K = 5
RETRIEVAL_MODES = ["dense", "bm25", "hybrid"]
# 정답 라벨 후보는 뉴스만으로 만들었으므로 검색 평가도 뉴스로 한정한다
LABELED_SOURCE_TYPES = ["news"]
LABEL_VALUES = {"0", "1"}

# 평가 문항(사람이 읽는 질문). LLM 단독 vs RAG 비교에도 같은 문장을 쓴다.
QUESTION_TEMPLATES = {
    "demand": "'{title}'에 대한 고객({customers}) 수요를 보여주는 근거가 있는가?",
    "competition": "'{title}'의 경쟁 기업이나 대체 제품은 무엇인가?",
    "price": "'{title}'의 도입 가격이나 비용 수준을 보여주는 근거가 있는가?",
    "buyer": "'{title}' 관련 기술({technology})을 실제로 도입한 고객이나 사례가 있는가?",
    "adoption_barrier": "'{title}' 도입 시 고객({customers})이 겪는 어려움은 무엇인가?",
}

# 하위 순위 후보를 고를 때 쓰는 차원별 표현
DIMENSION_TERMS = {
    "demand": r"수요|확대|증가|성장|보급|늘어",
    "competition": r"출시|경쟁|공개|선보|솔루션|업체",
    "price": r"가격|비용|단가|저렴|\d+\s?(?:만|억)?원",
    "buyer": r"도입|사례|구축|적용|납품|공급 계약",
    "adoption_barrier": r"어려움|부담|애로|부족|장벽|한계|걸림돌",
}

CSV_FIELDS = [
    "case_id",
    "idea_id",
    "dimension",
    "question",
    "source_id",
    "published_at",
    "title",
    "summary",
    "url",
    "relevant",
    "note",
    "pool",
    "rank",
    "distance",
]

SearchFn = Callable[[str, int, str], list[dict]]


def load_ideas(path: Path = IDEAS_PATH) -> dict[str, dict]:
    """샘플 아이디어 파일을 {idea_id: 항목}으로 읽는다."""
    entries = json.loads(path.read_text(encoding="utf-8"))
    return {entry["idea_id"]: entry for entry in entries}


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    """평가 문항 목록을 읽는다. 파일이 비어 있으면 빈 목록."""
    text = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    return json.loads(text) if text else []


def save_cases(cases: list[dict], path: Path = CASES_PATH) -> Path:
    """평가 문항 목록을 JSON으로 저장한다."""
    path.write_text(
        json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def idea_of(entry: dict) -> StructuredIdea:
    """샘플 아이디어 항목을 StructuredIdea로 변환한다."""
    return StructuredIdea(**entry["idea"])


def make_cases(ideas: dict[str, dict]) -> list[dict]:
    """아이디어 × 차원 조합마다 라벨이 비어 있는 평가 문항을 만든다."""
    cases = []
    for idea_id, entry in ideas.items():
        values = entry["idea"]
        for dimension in ALL_DIMENSIONS:
            cases.append(
                {
                    "case_id": f"{idea_id}-{dimension}",
                    "idea_id": idea_id,
                    "dimension": dimension,
                    "question": QUESTION_TEMPLATES[dimension].format(**values),
                    "relevant_source_ids": [],
                    "judged_source_ids": [],
                    "labeled": False,
                }
            )
    return cases


def case_query(case: dict, ideas: dict[str, dict]) -> str:
    """문항의 아이디어·차원으로 검색 툴과 같은 질의를 만든다."""
    from src.retrieval.market_search import build_dimension_queries

    request = MarketSearchRequest(
        idea=idea_of(ideas[case["idea_id"]]), dimensions=[case["dimension"]]
    )
    return build_dimension_queries(request)[case["dimension"]]


def default_search_fn(
    retrieval_mode: str = "dense",
    reranker=None,
    source_types: list[str] | None = LABELED_SOURCE_TYPES,
) -> SearchFn:
    """로컬 Chroma 색인을 쓰는 검색 함수를 만든다. OPENAI_API_KEY가 필요하다.

    기본 검색 대상은 정답 라벨이 있는 뉴스뿐이다. source_types=None이면 모든 출처를 검색한다.
    """
    from src.retrieval.market_search import get_collection, search_market

    collection = get_collection()
    if collection.count() == 0:
        raise RuntimeError(
            "market Chroma index is empty; ingest and index market documents before evaluation"
        )
    return lambda query, top_k, idea_id: search_market(
        query,
        collection=collection,
        top_k=top_k,
        idea_id=idea_id,
        source_types=source_types,
        retrieval_mode=retrieval_mode,
        reranker=reranker,
    )


def collect_candidates(case: dict, ideas: dict[str, dict], search_fn: SearchFn):
    """문항 1개의 라벨링 후보(벡터 상위 + 하위 순위 차원 표현 문서)를 반환한다."""
    hits = search_fn(case_query(case, ideas), TERM_SCAN, case["idea_id"])
    for rank, hit in enumerate(hits, start=1):
        hit["rank"] = rank
    vector = [dict(h, pool="vector") for h in hits[:VECTOR_POOL]]
    pattern = re.compile(DIMENSION_TERMS[case["dimension"]])
    term = [
        dict(h, pool="term") for h in hits[VECTOR_POOL:] if pattern.search(h["text"])
    ][:TERM_POOL]
    return vector + term


def candidate_row(case: dict, hit: dict) -> dict:
    """검색 결과 1건을 라벨링 후보 CSV 행으로 만든다 (relevant는 빈 값)."""
    _, _, summary = hit["text"].partition("\n")
    distance = hit.get("distance")
    return {
        "case_id": case["case_id"],
        "idea_id": case["idea_id"],
        "dimension": case["dimension"],
        "question": case["question"],
        "source_id": hit["source_id"],
        "published_at": hit["published_at"],
        "title": hit["title"],
        "summary": summary[:200],
        "url": hit.get("url") or "",
        "relevant": "",
        "note": "",
        "pool": hit["pool"],
        "rank": hit["rank"],
        "distance": "" if distance is None else distance,
    }


def export_candidates(
    cases: list[dict],
    ideas: dict[str, dict],
    search_fn: SearchFn,
    path: Path = CANDIDATES_PATH,
) -> int:
    """라벨링 후보 CSV(엑셀용 UTF-8 BOM)를 저장하고 행 수를 반환한다.

    순위가 판단에 영향을 주지 않도록 문항 안에서는 source_id 순으로 섞어 쓴다.
    """
    rows = []
    for case in cases:
        candidates = collect_candidates(case, ideas, search_fn)
        for hit in sorted(candidates, key=lambda h: h["source_id"]):
            rows.append(candidate_row(case, hit))
    write_label_rows(rows, CSV_FIELDS, path)
    return len(rows)


def extend_candidates(
    rows: list[dict],
    cases: list[dict],
    ideas: dict[str, dict],
    search_fns: dict[str, SearchFn],
    top_k: int = EXTEND_TOP_K,
) -> tuple[list[dict], dict[str, int]]:
    """검색 방식별 상위 top_k건 중 후보에 없는 문서를 빈 라벨 행으로 덧붙인다.

    pool은 그 문서를 가져온 방식 이름(여러 방식이면 '+'로 연결), rank는 처음 가져온 방식의 순위다.
    기존 행은 그대로 둔다. 반환: (전체 행, {방식: 그 방식 상위에 있었던 새 문서 수})
    """
    existing = {(r["case_id"], r["source_id"]) for r in rows}
    added: dict[tuple[str, str], dict] = {}
    counts = {mode: 0 for mode in search_fns}
    for case in cases:
        query = case_query(case, ideas)
        for mode, search_fn in search_fns.items():
            hits = search_fn(query, top_k, case["idea_id"])
            for rank, hit in enumerate(hits, start=1):
                key = (case["case_id"], hit["source_id"])
                if key in existing:
                    continue
                counts[mode] += 1
                if key in added:
                    added[key]["pool"] += f"+{mode}"
                else:
                    added[key] = candidate_row(
                        case, {**hit, "pool": mode, "rank": rank}
                    )
    fields = list(rows[0].keys()) if rows else CSV_FIELDS
    new_rows = [{f: row.get(f, "") for f in fields} for row in added.values()]
    return rows + new_rows, counts


def read_label_rows(path: Path = CANDIDATES_PATH) -> list[dict]:
    """라벨 CSV를 행 목록으로 읽는다. UTF-8이 아니면 엑셀 기본 형식(cp949)으로 읽는다."""
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("cp949")
    return list(csv.DictReader(io.StringIO(text, newline="")))


def write_label_rows(rows: list[dict], fields: list[str], path: Path) -> Path:
    """행 목록을 엑셀용 UTF-8 BOM CSV로 저장한다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
    return path


def import_labels(
    cases: list[dict], path: Path = CANDIDATES_PATH
) -> tuple[list[dict], dict[str, int]]:
    """라벨 CSV를 문항에 반영한다.

    relevant가 1인 문서를 relevant_source_ids, 1·0으로 판단한 문서를 judged_source_ids에 기록한다.
    한 문항의 모든 후보가 판단되었을 때만 labeled=True가 된다.
    반환: (갱신된 문항 목록, {case_id: 미판단 후보 수})
    """
    rows = read_label_rows(path)
    by_case: dict[str, list[dict]] = {}
    for row in rows:
        by_case.setdefault(row["case_id"], []).append(row)

    unknown = set(by_case) - {c["case_id"] for c in cases}
    if unknown:
        raise ValueError(f"unknown case_id in labels: {sorted(unknown)}")

    pending, updated = {}, []
    for case in cases:
        case_rows = by_case.get(case["case_id"], [])
        judged = [r for r in case_rows if r["relevant"].strip() in LABEL_VALUES]
        missing = len(case_rows) - len(judged)
        if missing or not case_rows:
            pending[case["case_id"]] = missing
        updated.append(
            {
                **case,
                "relevant_source_ids": sorted(
                    r["source_id"] for r in judged if r["relevant"].strip() == "1"
                ),
                "judged_source_ids": sorted(r["source_id"] for r in judged),
                "labeled": bool(case_rows) and not missing,
            }
        )
    return updated, pending


def main() -> None:
    """init·export·import 하위 명령을 실행한다."""
    parser = argparse.ArgumentParser(description="시장 검색 평가셋 라벨링")
    sub = parser.add_subparsers(dest="command", required=True)
    init = sub.add_parser("init", help="ideas.json으로 평가 문항 생성")
    init.add_argument("--force", action="store_true", help="라벨이 있어도 다시 생성")
    sub.add_parser("export", help="라벨링 후보 CSV 생성")
    sub.add_parser("extend", help="검색 방식별 상위 결과 중 새 문서를 후보에 추가")
    sub.add_parser("import", help="라벨링한 CSV를 평가 문항에 반영")
    args = parser.parse_args()

    ideas = load_ideas()
    cases = load_cases()
    if args.command == "init":
        if any(c.get("labeled") for c in cases) and not args.force:
            raise SystemExit("labeled cases exist; use --force to overwrite")
        cases = make_cases(ideas)
        print(f"{len(cases)} cases -> {save_cases(cases)}")
    elif args.command == "export":
        count = export_candidates(cases, ideas, default_search_fn())
        print(f"{count} candidates -> {CANDIDATES_PATH}")
    elif args.command == "extend":
        rows = read_label_rows(CANDIDATES_PATH)
        search_fns = {mode: default_search_fn(mode) for mode in RETRIEVAL_MODES}
        extended, counts = extend_candidates(rows, cases, ideas, search_fns)
        write_label_rows(extended, list(extended[0].keys()), CANDIDATES_PATH)
        print(f"{len(extended) - len(rows)} new candidates -> {CANDIDATES_PATH}")
        for mode, count in counts.items():
            print(f"  {mode}: 상위 {EXTEND_TOP_K}건 중 새 문서 {count}건")
    else:
        cases, pending = import_labels(cases)
        save_cases(cases)
        done = sum(c["labeled"] for c in cases)
        print(f"labeled {done}/{len(cases)} cases")
        for case_id, missing in pending.items():
            print(f"  {case_id}: {missing} candidates without 1/0")


if __name__ == "__main__":
    main()
