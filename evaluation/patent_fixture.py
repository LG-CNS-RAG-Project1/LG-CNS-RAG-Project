"""오프라인 특허 검색 파이프라인용 합성 fixture를 검증한다."""

import hashlib
import json
from pathlib import Path

FIXTURE_PATH = (
    Path(__file__).resolve().parent / "fixtures" / "patent_retrieval_synthetic_v1.json"
)


def load_fixture(path: Path = FIXTURE_PATH) -> tuple[dict, str]:
    """합성 fixture를 읽고 구조와 참조 무결성을 검사한다."""
    raw = path.read_bytes()
    dataset = json.loads(raw)
    if dataset.get("dataset_type") != "synthetic_pipeline_fixture":
        raise ValueError("fixture must be explicitly marked synthetic")

    documents = dataset.get("documents", [])
    queries = dataset.get("queries", [])
    document_ids = [document.get("source_id") for document in documents]
    query_ids = [query.get("case_id") for query in queries]
    if not documents or not queries:
        raise ValueError("fixture must contain documents and queries")
    if len(document_ids) != len(set(document_ids)):
        raise ValueError("document source_id values must be unique")
    if len(query_ids) != len(set(query_ids)):
        raise ValueError("query case_id values must be unique")
    if any(not source_id.startswith("SYN-") for source_id in document_ids):
        raise ValueError("synthetic documents must use SYN- source IDs")

    known_ids = set(document_ids)
    for query in queries:
        judged = set(query.get("judged_source_ids", []))
        relevant = set(query.get("relevant_source_ids", []))
        if not relevant <= judged <= known_ids:
            raise ValueError(f"invalid relevance references in {query.get('case_id')}")
    return dataset, hashlib.sha256(raw).hexdigest()


def main() -> None:
    dataset, fingerprint = load_fixture()
    print(f"dataset_id: {dataset['dataset_id']}")
    print(f"documents: {len(dataset['documents'])}")
    print(f"queries: {len(dataset['queries'])}")
    print(f"sha256: {fingerprint}")
    print("scope: synthetic pipeline fixture; not a real patent quality benchmark")


if __name__ == "__main__":
    main()
