"""특허 평가 질의의 문헌 후보를 내보내고 사람 관련도 라벨을 반영한다.

사용 예:
    python -m evaluation.patent_labeling export
    python -m evaluation.patent_labeling import
"""

import argparse
import json
from pathlib import Path

from evaluation.market_labeling import read_label_rows, write_label_rows
from src.generation.patent_analysis import kipris_application_search_url
from src.retrieval.patent_search import search_patents
from src.retrieval.patent_store import get_collection

ROOT_DIR = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT_DIR / "evaluation" / "patent_cases.json"
CANDIDATES_PATH = ROOT_DIR / "evaluation" / "labels" / "patent_candidates.csv"
MODES = ("dense", "bm25", "hybrid")
TOP_K = 20
LABEL_VALUES = {"0", "1"}
CSV_FIELDS = [
    "case_id",
    "idea_id",
    "technical_element",
    "query",
    "source_id",
    "title",
    "summary",
    "claim_number",
    "version_id",
    "url",
    "relevant",
    "note",
]


def load_cases(path: Path = CASES_PATH) -> list[dict]:
    """특허 평가 질의를 JSON 파일에서 읽는다."""
    text = path.read_text(encoding="utf-8").strip() if path.exists() else ""
    return json.loads(text) if text else []


def save_cases(cases: list[dict], path: Path = CASES_PATH) -> Path:
    """평가 질의와 라벨을 JSON 파일에 저장한다."""
    path.write_text(
        json.dumps(cases, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    return path


def default_searchers(collection=None, top_k: int = TOP_K):
    """같은 색인과 질의로 Dense·BM25·Hybrid 후보 검색기를 만든다."""
    collection = collection or get_collection()
    if collection.count() == 0:
        raise RuntimeError(
            "patent Chroma index is empty; ingest and index patent documents first"
        )
    return {
        mode: (
            lambda query, technology_area_id=None, mode=mode: search_patents(
                query,
                collection=collection,
                top_k=top_k,
                retrieval_mode=mode,
                technology_area_id=technology_area_id,
            )
        )
        for mode in MODES
    }


def add_reranked_searcher(searchers: dict, collection=None, top_k: int = TOP_K):
    """선택된 BGE Cross-Encoder를 포함한 Hybrid 후보 검색기를 추가한다."""
    from src.retrieval.engine import bge_reranker

    collection = collection or get_collection()
    reranker = bge_reranker()
    searchers["hybrid_rerank"] = lambda query, technology_area_id=None: search_patents(
        query,
        collection=collection,
        top_k=top_k,
        retrieval_mode="hybrid",
        reranker=reranker,
        technology_area_id=technology_area_id,
    )
    return searchers


def export_candidates(
    cases: list[dict], searchers: dict, path: Path = CANDIDATES_PATH
) -> int:
    """세 검색 방식의 상위 후보를 문헌 단위로 합쳐 블라인드 라벨 CSV로 저장한다."""
    grouped = {}
    for case in cases:
        for mode, search_fn in searchers.items():
            try:
                hits = search_fn(case["query"], case.get("technology_area_id"))
            except TypeError:
                hits = search_fn(case["query"])
            for hit in hits:
                document = hit.document
                key = (case["case_id"], document.source_id)
                source_url = document.metadata.get("source_url") or ""
                if not source_url:
                    source_url = (
                        kipris_application_search_url(
                            document.metadata.get("application_number")
                            or document.source_id
                        )
                        or ""
                    )
                row = grouped.setdefault(
                    key,
                    {
                        "case_id": case["case_id"],
                        "idea_id": case.get("idea_id", ""),
                        "technical_element": case["technical_element"],
                        "query": case["query"],
                        "source_id": document.source_id,
                        "title": document.title,
                        "summary": document.content[:500],
                        "claim_number": document.metadata.get("claim_number", ""),
                        "version_id": document.metadata.get("version_id", ""),
                        "url": source_url,
                        "relevant": "",
                        "note": "",
                    },
                )

    rows = [row for _, row in sorted(grouped.items())]
    write_label_rows(rows, CSV_FIELDS, path)
    return len(rows)


def import_labels(
    cases: list[dict], path: Path = CANDIDATES_PATH
) -> tuple[list[dict], dict[str, int]]:
    """사람 라벨 0/1을 반영하고 미판단 후보가 남은 문항을 반환한다."""
    rows = read_label_rows(path)
    known_cases = {case["case_id"] for case in cases}
    unknown = {row["case_id"] for row in rows} - known_cases
    if unknown:
        raise ValueError(f"unknown case_id in labels: {sorted(unknown)}")

    by_case = {}
    for row in rows:
        value = row.get("relevant", "").strip()
        if value and value not in LABEL_VALUES:
            raise ValueError(f"relevant must be 0 or 1: {value}")
        by_case.setdefault(row["case_id"], []).append(row)

    pending, updated = {}, []
    for case in cases:
        candidates = by_case.get(case["case_id"], [])
        missing = sum(
            row.get("relevant", "").strip() not in LABEL_VALUES for row in candidates
        )
        if missing or not candidates:
            pending[case["case_id"]] = missing if candidates else 0
            updated.append(case)
            continue
        next_case = dict(case)
        next_case["judged_source_ids"] = sorted(
            {row["source_id"] for row in candidates}
        )
        next_case["relevant_source_ids"] = sorted(
            {row["source_id"] for row in candidates if row["relevant"].strip() == "1"}
        )
        next_case["labeled"] = True
        updated.append(next_case)
    return updated, pending


def main() -> None:
    parser = argparse.ArgumentParser(description="특허 검색 평가 라벨링")
    sub = parser.add_subparsers(dest="command", required=True)
    export = sub.add_parser("export", help="검색 결과 후보를 CSV로 내보냄")
    export.add_argument(
        "--rerank", action="store_true", help="BGE reranker 후보도 포함"
    )
    sub.add_parser("import", help="작성한 CSV 라벨을 평가 질의에 반영")
    args = parser.parse_args()

    cases = load_cases()
    if args.command == "export":
        searchers = default_searchers()
        if args.rerank:
            add_reranked_searcher(searchers)
        count = export_candidates(cases, searchers)
        print(f"{count} patent candidates -> {CANDIDATES_PATH}")
        return
    updated, pending = import_labels(cases)
    save_cases(updated)
    print(f"updated {sum(case['labeled'] for case in updated)} labeled cases")
    if pending:
        print(f"pending cases: {pending}")


if __name__ == "__main__":
    main()
