"""Patent retrieval candidate normalization, ranking, and trace helpers."""

from src.retrieval.schemas import RetrievalResult, SearchDocument
from src.schemas import PatentEvidence

KIPRIS_SUPPLEMENT_QUERY_LIMIT = 5


def _metadata_codes(value) -> list[str]:
    """검색 메타데이터의 코드 배열 또는 쉼표 문자열을 목록으로 정리한다."""
    if isinstance(value, (list, tuple, set)):
        values = value
    else:
        values = str(value or "").replace("|", ",").split(",")
    return list(
        dict.fromkeys(str(item).strip() for item in values if str(item).strip())
    )


def _kipris_supplement_queries(plan, idea) -> list[str]:
    """KIPRIS 요청량을 제한하면서 LLM이 만든 한국어 기술 검색어를 우선 사용한다."""
    queries = []
    for item in plan.queries:
        for query in item.korean_queries:
            normalized = " ".join(query.split())
            if normalized and normalized not in queries:
                queries.append(normalized)
                break
        if len(queries) >= KIPRIS_SUPPLEMENT_QUERY_LIMIT:
            break

    if not queries:
        fallback = " ".join((idea.technology or idea.title).split())[:100]
        if fallback:
            queries.append(fallback)
    return queries


def _supplement_result(record: dict) -> RetrievalResult | None:
    """KIPRIS 결과를 공통 검색 결과로 변환한다."""
    application_number = str(record.get("application_number") or "").strip()
    if not application_number:
        return None
    title = str(record.get("title") or "").strip()
    abstract = str(record.get("abstract") or "").strip()
    content = abstract
    if not content:
        return None
    document = SearchDocument(
        chunk_id=f"{application_number}_abstract_0",
        source_id=application_number,
        source_type="patent",
        title=title or application_number,
        content=content,
        metadata={
            "section": "abstract",
            "application_number": application_number,
            "publication_number": record.get("publication_number"),
            "registration_number": record.get("registration_number"),
            "application_date": record.get("application_date"),
            "publication_date": record.get("publication_date"),
            "public_date": record.get("public_date"),
            "source_url": record.get("source_url"),
            "representative_drawing_url": record.get("representative_drawing_url"),
            "representative_thumbnail_url": record.get("representative_thumbnail_url"),
            "representative_drawing_caption": record.get(
                "representative_drawing_caption"
            ),
            "applicant": record.get("applicant"),
            "ipc_codes": record.get("ipc_codes") or [],
            "cpc_codes": record.get("cpc_codes") or [],
        },
    )
    return RetrievalResult(document=document)


def _tag_retrieval_result(
    result: RetrievalResult,
    *,
    query: str,
    technical_element: str,
    retrieval_scope: str,
) -> RetrievalResult:
    """검색 결과에 후보가 발견된 질의·기술 요소·검색 범위를 기록한다."""
    metadata = dict(result.document.metadata)
    trace = dict(metadata.get("retrieval_trace") or {})
    trace["matched_queries"] = list(
        dict.fromkeys([*trace.get("matched_queries", []), query])
    )
    trace["matched_technical_elements"] = list(
        dict.fromkeys([*trace.get("matched_technical_elements", []), technical_element])
    )
    trace["retrieval_scopes"] = list(
        dict.fromkeys([*trace.get("retrieval_scopes", []), retrieval_scope])
    )
    trace["matched_sections"] = list(
        dict.fromkeys(
            [*trace.get("matched_sections", []), metadata.get("section", "unknown")]
        )
    )
    metadata["retrieval_trace"] = trace
    document = result.document.model_copy(update={"metadata": metadata})
    return result.model_copy(update={"document": document})


def _merge_retrieval_results(
    existing: RetrievalResult | None,
    candidate: RetrievalResult,
    retrieval_mode: str = "dense",
) -> RetrievalResult:
    """같은 특허의 검색 흔적을 합치고 가장 높은 점수의 청크를 대표로 둔다."""
    if existing is None:
        return candidate
    existing_trace = existing.document.metadata.get("retrieval_trace", {})
    candidate_trace = candidate.document.metadata.get("retrieval_trace", {})
    score_field = {
        "dense": "dense_score",
        "bm25": "bm25_score",
        "hybrid": "rrf_score",
    }[retrieval_mode]

    def score(item):
        if item.rerank_score is not None:
            return item.rerank_score
        value = getattr(item, score_field)
        return value if value is not None else float("-inf")

    primary = candidate if score(candidate) > score(existing) else existing
    metadata = dict(primary.document.metadata)
    trace = {}
    for key in (
        "matched_queries",
        "matched_technical_elements",
        "retrieval_scopes",
        "matched_sections",
    ):
        trace[key] = list(
            dict.fromkeys(
                [
                    *existing_trace.get(key, []),
                    *candidate_trace.get(key, []),
                ]
            )
        )
    metadata["retrieval_trace"] = trace
    document = primary.document.model_copy(update={"metadata": metadata})
    return primary.model_copy(update={"document": document})


def _candidate_rank_key(
    item: RetrievalResult, retrieval_mode: str
) -> tuple[bool, float]:
    """검색 모드의 점수 기준에 맞는 특허 후보 정렬 키를 만든다."""
    score_field = {
        "dense": "dense_score",
        "bm25": "bm25_score",
        "hybrid": "rrf_score",
    }[retrieval_mode]
    score = (
        item.rerank_score
        if item.rerank_score is not None
        else getattr(item, score_field)
    )
    return score is not None, score if score is not None else float("-inf")


def _retrieval_trace(metadata: dict) -> dict:
    """PatentEvidence에 노출할 검색 추적 정보를 반환한다."""
    return metadata.get("retrieval_trace") or {}


def _evidence_search_trace(metadata: dict) -> dict:
    """검색 질의와 범위 추적 정보를 근거 모델 필드로 변환한다."""
    trace = _retrieval_trace(metadata)
    return {
        "matched_queries": trace.get("matched_queries", []),
        "matched_technical_elements": trace.get("matched_technical_elements", []),
        "matched_sections": trace.get("matched_sections", []),
        "retrieval_scopes": trace.get("retrieval_scopes", []),
    }
