"""특허 검색, 청구항 근거 보강 및 아이디어 비교의 서비스 경계."""

from collections import defaultdict
import os
from pathlib import Path
from typing import Callable

from src.generation.patent_analysis import review_patents_by_component
from src.generation.patent_design import generate_patent_design_analysis
from src.analysis.patent_statistics import (
    calculate_patent_statistics,
    indexed_patent_statistics,
)
from src.ingestion.kipris_client import KiprisAPIError, fetch_patent_claims
from src.retrieval.patent_search import build_patent_queries, search_patents
from src.retrieval.patent_relevance import judge_patent_candidates
from src.retrieval.engine import RetrievalConfig
from src.retrieval.schemas import RetrievalResult, SearchDocument
from src.schemas import (
    PatentComparison,
    PatentDesignAnalysis,
    PatentClaim,
    PatentEvidence,
    PatentReport,
    PatentSearchRequest,
)
from src.ingestion.patent_processor import structure_claims

ROOT_DIR = Path(__file__).resolve().parents[2]

# 특허 검색어 계획의 기술 요소별 한국어 질의를 최대 5개까지 보충 검색한다.
# 5건 목표에 못 미칠 때만 호출하고, 후보가 충분해지면 즉시 멈춘다.
KIPRIS_SUPPLEMENT_QUERY_LIMIT = 5
MIN_RECOMMENDED_PATENTS = 5


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
        "retrieval_scopes": trace.get("retrieval_scopes", []),
    }


def _normalize_quote(value: str) -> str:
    """특허 원문 비교용으로 공백만 정규화한다."""
    return " ".join(value.split())


def validate_patent_citations(
    evidence: list[PatentEvidence], source_texts: dict[int, str]
) -> None:
    """각 인용문이 해당 검색·KIPRIS 원문 텍스트에 포함되는지 검증한다."""
    for item in evidence:
        source = _normalize_quote(source_texts.get(item.citation_id, ""))
        quote = _normalize_quote(item.quote)
        if not quote or quote not in source:
            raise ValueError(
                f"Patent citation {item.citation_id} does not match source text"
            )


def _select_claims(idea, claims: list, limit: int = 5) -> list:
    """관련 청구항과 그 상위항을 한 묶음으로 선택한다."""
    from src.retrieval.engine import tokenize

    idea_text = " ".join(idea.technical_components or [idea.technology, idea.problem])
    terms = set(tokenize(idea_text))
    claims_by_number = {claim.claim_number: claim for claim in claims}
    ranked = sorted(
        claims,
        key=lambda claim: (
            len(terms & set(tokenize(claim.text))),
            claim.claim_type == "independent",
            -claim.claim_number,
        ),
        reverse=True,
    )
    selected = []
    selected_numbers = set()
    for claim in ranked:
        if claim.claim_number in selected_numbers:
            continue
        ancestors = []
        pending = list(claim.depends_on)
        visited = set()
        missing_parent = False
        while pending:
            number = pending.pop()
            if number in visited or number in selected_numbers:
                continue
            visited.add(number)
            parent = claims_by_number.get(number)
            if not parent:
                missing_parent = True
                break
            ancestors.append(parent)
            pending.extend(parent.depends_on)
        # 부모 원문이 빠져 있어도 인용 자체는 보존한다. 호출부가 미확인 경고를 붙이고,
        # 비교기는 상위항 범위를 추정하지 않도록 프롬프트에서 제한한다.
        additions = sorted(ancestors, key=lambda item: item.claim_number) + [claim]
        additions = [
            item for item in additions if item.claim_number not in selected_numbers
        ]
        if len(selected) + len(additions) <= limit:
            selected.extend(additions)
            selected_numbers.update(item.claim_number for item in additions)
    return sorted(selected, key=lambda claim: claim.claim_number)


def _estimate_text_tokens(text: str) -> int:
    """특허 근거 문맥을 위한 보수적인 토큰 수 근사치를 계산한다.

    한국어·영어가 섞인 원문에서 문자 길이만으로 예산을 과소평가하지 않도록
    공백 단위 토큰과 문자 길이 기반 상한 중 큰 값을 사용한다.
    """
    normalized = " ".join(text.split())
    if not normalized:
        return 0
    return max(len(normalized.split()), (len(normalized) + 2) // 3)


def _build_patent_context(
    idea, claims: list, *, max_tokens: int = 1800, max_claims: int = 5
) -> tuple[list[PatentClaim], int, list[str]]:
    """청구항 원문과 상위항 문맥을 예산 내에서 선택한다.

    토큰 추정에는 검색 계획·아이디어·서식 오버헤드를 포함하지 않으므로,
    호출부는 반환된 사용량을 전체 요청 한도로 간주하지 않아야 한다.
    """
    selected = _select_claims(idea, claims, limit=max_claims)
    selected_numbers = {claim.claim_number for claim in selected}
    claim_map = {claim.claim_number: claim for claim in claims}
    notes = []

    def cost(claim: PatentClaim) -> int:
        return _estimate_text_tokens(claim.text)

    while selected and sum(cost(claim) for claim in selected) > max_tokens:
        removable = [
            claim
            for claim in selected
            if claim.claim_type == "dependent"
            and not any(claim.claim_number in other.depends_on for other in selected)
        ]
        if removable:
            selected.remove(max(removable, key=cost))
            selected_numbers = {claim.claim_number for claim in selected}
            continue

        # 독립항은 잘라 인용하지 않고, 원문 전체가 예산에 들지 않으면 보류한다.
        independent = next(
            (claim for claim in selected if claim.claim_type == "independent"), None
        )
        if independent:
            selected.remove(independent)
            selected_numbers = {claim.claim_number for claim in selected}
            notes.append(
                f"청구항 {independent.claim_number} 원문이 문맥 토큰 예산을 초과해 제외됨"
            )
            # 빠진 독립항에 의존하는 종속항도 함께 제외해 문맥이 잘리지 않게 한다.
            changed = True
            while changed:
                changed = False
                for claim in list(selected):
                    if any(
                        parent not in selected_numbers for parent in claim.depends_on
                    ):
                        selected.remove(claim)
                        selected_numbers.remove(claim.claim_number)
                        notes.append(
                            f"청구항 {claim.claim_number} 상위항 문맥이 제외되어 함께 제외됨"
                        )
                        changed = True
            continue

        # 남은 종속항 집합이 상위항 관계를 모두 포함하지 않으면 추가 비교에 쓰지 않는다.
        claim = max(selected, key=cost)
        selected.remove(claim)
        selected_numbers.remove(claim.claim_number)
        notes.append(
            f"청구항 {claim.claim_number} 원문이 문맥 토큰 예산을 초과해 제외됨"
        )

    for claim in selected:
        missing = [number for number in claim.depends_on if number not in claim_map]
        if missing:
            notes.append(
                f"청구항 {claim.claim_number} 상위항 {', '.join(map(str, missing))} 원문 미확보"
            )
    return selected, sum(cost(claim) for claim in selected), notes


def analyze_patents(
    request: PatentSearchRequest,
    *,
    collection=None,
    embed_fn=None,
    query_llm_fn=None,
    claim_fetcher: Callable[[str], list[dict]] | None = None,
    kipris_search_fn: Callable[[str, int], list[dict]] | None = None,
    comparison_fn: (
        Callable[[object, list[PatentEvidence]], list[PatentComparison]] | None
    ) = None,
    patent_review_fn: Callable | None = None,
    design_proposal_fn: Callable | None = None,
    relevance_fn: Callable | None = None,
    candidate_k: int = 20,
    retrieval_mode: str | None = None,
    reranker: Callable | None = None,
) -> PatentReport:
    """특허 후보를 최대 8건 고르고 청구항 원문 근거와 비교 결과를 만든다.

    테스트와 다른 배포 환경은 collection 및 KIPRIS/LLM 함수들을 주입할 수 있다.
    """
    from src.ingestion.kipris_client import search_patents as search_kipris_patents
    from dotenv import load_dotenv

    load_dotenv(ROOT_DIR / ".env")
    retrieval_mode = (
        retrieval_mode
        or os.getenv("IDEALENS_PATENT_RETRIEVAL_MODE", "dense").strip().lower()
    )
    if retrieval_mode not in {"dense", "bm25", "hybrid"}:
        raise ValueError(
            "IDEALENS_PATENT_RETRIEVAL_MODE must be dense, bm25, or hybrid"
        )
    reranker_name = os.getenv("IDEALENS_PATENT_RERANKER", "none").strip().lower()
    if reranker is None and reranker_name not in {"", "none"}:
        if reranker_name != "bge-cross-encoder":
            raise ValueError(
                "IDEALENS_PATENT_RERANKER must be none or bge-cross-encoder"
            )
        from src.retrieval.engine import bge_reranker

        reranker = bge_reranker()

    if collection is None:
        from src.retrieval.patent_store import get_collection

        collection = get_collection()

    claim_fetcher = claim_fetcher or fetch_patent_claims
    kipris_search_fn = kipris_search_fn or search_kipris_patents
    relevance_fn = relevance_fn or judge_patent_candidates
    plan_kwargs = {"request": request}
    if query_llm_fn is not None:
        plan_kwargs["llm_fn"] = query_llm_fn

    evidence: list[PatentEvidence] = []
    source_texts: dict[int, str] = {}
    unknowns: list[str] = []
    used_global_fallback = False
    kipris_search_error = None
    indexed_statistics = None
    try:
        indexed_statistics = indexed_patent_statistics(collection)
    except Exception as statistics_error:
        unknowns.append(
            "색인 전체 통계를 읽지 못했습니다: " f"{type(statistics_error).__name__}"
        )
    try:
        plan = build_patent_queries(**plan_kwargs)
        query_specs = []
        seen_queries = set()
        for item in plan.queries:
            for query in item.korean_queries + item.english_queries:
                normalized = " ".join(query.split()).casefold()
                if normalized and normalized not in seen_queries:
                    seen_queries.add(normalized)
                    query_specs.append(
                        (item.technical_element, " ".join(query.split()))
                    )
        queries = [query for _, query in query_specs]
        retrieved_by_id = {}
        local_scope = (
            "technology_area" if request.technology_area_id else "global_index"
        )
        for technical_element, query in query_specs:
            for result in search_patents(
                query,
                collection=collection,
                embed_fn=embed_fn,
                top_k=max(candidate_k, request.top_k),
                retrieval_mode=retrieval_mode,
                reranker=reranker,
                retrieval_config=RetrievalConfig(
                    candidate_k=candidate_k,
                    top_k=max(candidate_k, request.top_k),
                    deduplicate_by_source=True,
                ),
                technology_area_id=request.technology_area_id,
            ):
                tagged = _tag_retrieval_result(
                    result,
                    query=query,
                    technical_element=technical_element,
                    retrieval_scope=local_scope,
                )
                source_id = result.document.source_id
                retrieved_by_id[source_id] = _merge_retrieval_results(
                    retrieved_by_id.get(source_id), tagged, retrieval_mode
                )

        ordered_candidates = sorted(
            retrieved_by_id.values(),
            key=lambda item: _candidate_rank_key(item, retrieval_mode),
            reverse=True,
        )[: max(candidate_k, request.top_k)]
        judgments = relevance_fn(request.idea, ordered_candidates)
        related_candidates = [
            item
            for item in ordered_candidates
            if judgments[item.document.source_id].relevant
        ]
        candidates = [item for item in related_candidates][: request.top_k]

        # A chosen technology area is a search preference, not a hard boundary.
        # Broaden to the full local index before concluding that no evidence exists.
        if request.technology_area_id and len(candidates) < request.top_k:
            used_global_fallback = True
            global_candidates = {}
            for technical_element, query in query_specs:
                for result in search_patents(
                    query,
                    collection=collection,
                    embed_fn=embed_fn,
                    top_k=max(candidate_k, request.top_k),
                    retrieval_mode=retrieval_mode,
                    reranker=reranker,
                    retrieval_config=RetrievalConfig(
                        candidate_k=candidate_k,
                        top_k=max(candidate_k, request.top_k),
                        deduplicate_by_source=True,
                    ),
                    technology_area_id=None,
                ):
                    source_id = result.document.source_id
                    if source_id not in retrieved_by_id:
                        tagged = _tag_retrieval_result(
                            result,
                            query=query,
                            technical_element=technical_element,
                            retrieval_scope="global_fallback",
                        )
                        global_candidates[source_id] = _merge_retrieval_results(
                            global_candidates.get(source_id), tagged, retrieval_mode
                        )

            if global_candidates:
                expanded = sorted(
                    global_candidates.values(),
                    key=lambda item: _candidate_rank_key(item, retrieval_mode),
                    reverse=True,
                )[: max(candidate_k, request.top_k)]
                expanded_judgments = relevance_fn(request.idea, expanded)
                expanded_related = [
                    item
                    for item in expanded
                    if expanded_judgments[item.document.source_id].relevant
                ]
                related_candidates.extend(expanded_related)
                candidates.extend(expanded_related)
                candidates = candidates[: request.top_k]

        minimum_target = min(MIN_RECOMMENDED_PATENTS, request.top_k)
        if len(candidates) < minimum_target:
            for query in _kipris_supplement_queries(plan, request.idea):
                try:
                    records = kipris_search_fn(query, minimum_target - len(candidates))
                except KiprisAPIError as exc:
                    kipris_search_error = str(exc)
                    unknowns.append(f"KIPRIS 후보 보충 미실행: {exc}")
                    break
                added = []
                for record in records:
                    result = _supplement_result(record)
                    if result and result.document.source_id not in retrieved_by_id:
                        result = _tag_retrieval_result(
                            result,
                            query=query,
                            technical_element="KIPRIS 후보 보충",
                            retrieval_scope="kipris_supplement",
                        )
                        retrieved_by_id[result.document.source_id] = result
                        added.append(result)
                if added:
                    supplemental_judgments = relevance_fn(request.idea, added)
                    candidates.extend(
                        item
                        for item in added
                        if supplemental_judgments[item.document.source_id].relevant
                    )
                    related_candidates.extend(
                        item
                        for item in added
                        if supplemental_judgments[item.document.source_id].relevant
                    )
                if len(candidates) >= minimum_target:
                    candidates = candidates[: request.top_k]
                    break
        if 0 < len(candidates) < minimum_target:
            unknowns.append(
                f"검색 범위에서 관련 특허 {len(candidates)}건만 확보했습니다. "
                f"목표 {minimum_target}건보다 적어 결과를 임의로 채우지 않았습니다."
            )
        if not candidates:
            if kipris_search_error:
                return PatentReport(
                    status="error",
                    search_scope=(
                        f"로컬 {retrieval_mode} 검색 후 KIPRIS 보충 검색에서 오류 발생; "
                        "특허 부재 여부 미확인"
                    ),
                    error_message=kipris_search_error,
                    unknowns=unknowns,
                    indexed_statistics=indexed_statistics,
                )
            return PatentReport(
                status="no_results",
                search_scope=(
                    f"분야 우선 {retrieval_mode} 검색·전체 색인 보충 후 관련 후보 없음"
                    if used_global_fallback
                    else "아이디어 기술 요소별 Dense 검색 및 필요 시 KIPRIS 후보 보충"
                ),
                unknowns=unknowns or ["검색된 특허 후보가 없습니다."],
                indexed_statistics=indexed_statistics,
            )

        for result in candidates:
            document = result.document
            meta = document.metadata
            evidence_trace = _evidence_search_trace(meta)
            app_number = str(meta.get("application_number") or document.source_id)
            version_id = (
                meta.get("claim_version_id")
                or meta.get("registration_number")
                or meta.get("publication_number")
            )
            local_claims = []
            local_unclassified_claim = None
            if meta.get("section") == "claims":
                if meta.get("claim_number"):
                    references = meta.get("depends_on") or []
                    if isinstance(references, str):
                        references = [
                            int(value)
                            for value in references.split(",")
                            if value.strip().isdigit()
                        ]
                    local_claims = [
                        PatentClaim(
                            claim_number=int(meta["claim_number"]),
                            text=document.content,
                            claim_type=meta.get("claim_type") or "unclassified",
                            depends_on=references,
                            version_id=meta.get("version_id") or version_id,
                        )
                    ]
                else:
                    local_unclassified_claim = document.content.strip()
            try:
                fetched = claim_fetcher(app_number)
                claims = (
                    structure_claims(fetched, version_id) if fetched else local_claims
                )
            except KiprisAPIError as exc:
                claims = local_claims
                unknowns.append(f"{app_number}: KIPRIS 청구항 원문 조회 실패 ({exc})")

            if claims:
                selected_claims, context_tokens, context_notes = _build_patent_context(
                    request.idea, claims
                )
                unknowns.extend(f"{app_number}: {note}" for note in context_notes)
                if context_tokens:
                    unknowns.append(
                        f"{app_number}: 비교 문맥 청구항 원문 추정 토큰 {context_tokens}"
                    )
                available_claim_numbers = {claim.claim_number for claim in claims}
                for claim in selected_claims:
                    missing_parents = [
                        number
                        for number in claim.depends_on
                        if number not in available_claim_numbers
                    ]
                    if missing_parents:
                        unknowns.append(
                            f"{app_number}: 청구항 {claim.claim_number}의 상위항 "
                            f"{', '.join(map(str, missing_parents))} 원문 미확보; "
                            "종속항만으로 권리 범위를 추정하지 않음"
                        )
                    evidence.append(
                        PatentEvidence(
                            citation_id=len(evidence) + 1,
                            patent_id=document.source_id,
                            title=document.title,
                            section="claims",
                            quote=claim.text,
                            similarity=(
                                min(1.0, max(0.0, result.dense_score))
                                if result.dense_score is not None
                                else None
                            ),
                            source_url=meta.get("source_url"),
                            application_number=app_number,
                            publication_number=meta.get("publication_number"),
                            registration_number=meta.get("registration_number"),
                            ipc_codes=_metadata_codes(meta.get("ipc_codes")),
                            cpc_codes=_metadata_codes(meta.get("cpc_codes")),
                            application_date=meta.get("application_date"),
                            publication_date=meta.get("publication_date"),
                            collected_at=meta.get("collected_at"),
                            claim_number=claim.claim_number,
                            claim_type=claim.claim_type,
                            depends_on=claim.depends_on,
                            version_id=claim.version_id or version_id,
                            **evidence_trace,
                        )
                    )
                    source_texts[evidence[-1].citation_id] = claim.text
            elif local_unclassified_claim:
                evidence.append(
                    PatentEvidence(
                        citation_id=len(evidence) + 1,
                        patent_id=document.source_id,
                        title=document.title,
                        section="claims",
                        quote=local_unclassified_claim,
                        similarity=(
                            min(1.0, max(0.0, result.dense_score))
                            if result.dense_score is not None
                            else None
                        ),
                        source_url=meta.get("source_url"),
                        application_number=app_number,
                        publication_number=meta.get("publication_number"),
                        registration_number=meta.get("registration_number"),
                        ipc_codes=_metadata_codes(meta.get("ipc_codes")),
                        cpc_codes=_metadata_codes(meta.get("cpc_codes")),
                        application_date=meta.get("application_date"),
                        publication_date=meta.get("publication_date"),
                        collected_at=meta.get("collected_at"),
                        claim_type="unclassified",
                        version_id=meta.get("version_id") or version_id,
                        **evidence_trace,
                    )
                )
                source_texts[evidence[-1].citation_id] = local_unclassified_claim
                unknowns.append(f"{app_number}: 청구항 원문 위치·번호·참조 관계 미확인")
            elif document.content.strip():
                quote = document.content.strip()
                if "\n" in quote:
                    quote = quote.split("\n", 1)[1].strip() or quote.split("\n", 1)[0]
                evidence.append(
                    PatentEvidence(
                        citation_id=len(evidence) + 1,
                        patent_id=document.source_id,
                        title=document.title,
                        section="abstract",
                        quote=quote,
                        similarity=(
                            min(1.0, max(0.0, result.dense_score))
                            if result.dense_score is not None
                            else None
                        ),
                        source_url=meta.get("source_url"),
                        application_number=app_number,
                        publication_number=meta.get("publication_number"),
                        registration_number=meta.get("registration_number"),
                        ipc_codes=_metadata_codes(meta.get("ipc_codes")),
                        cpc_codes=_metadata_codes(meta.get("cpc_codes")),
                        application_date=meta.get("application_date"),
                        publication_date=meta.get("publication_date"),
                        collected_at=meta.get("collected_at"),
                        version_id=version_id,
                        **evidence_trace,
                    )
                )
                source_texts[evidence[-1].citation_id] = document.content
                unknowns.append(f"{app_number}: 청구항 원문 미확보, 초록만 확인됨")

        if not evidence:
            return PatentReport(
                status="no_results",
                search_scope="아이디어 기술 요소별 Dense 검색 및 필요 시 KIPRIS 후보 보충",
                related_statistics=calculate_patent_statistics(
                    [
                        item.document.metadata | {"source_id": item.document.source_id}
                        for item in related_candidates
                    ],
                    scope="아이디어 관련 검색 후보",
                ),
                unknowns=unknowns + ["검색 후보의 원문 근거를 확보하지 못했습니다."],
            )

        evidenced_patent_count = len({item.patent_id for item in evidence})
        if 0 < evidenced_patent_count < minimum_target:
            unknowns.append(
                f"원문 근거까지 확보한 관련 특허는 {evidenced_patent_count}건입니다. "
                f"목표 {minimum_target}건보다 적어 확인된 문헌만 표시합니다."
            )

        validate_patent_citations(evidence, source_texts)
        expected_ids = {item.citation_id for item in evidence}
        comparisons = []
        patent_reviews = []
        patentability_precheck = None
        design_analysis = None
        if comparison_fn is not None:
            try:
                comparisons = comparison_fn(request.idea, evidence)
                actual_ids = [item.citation_id for item in comparisons]
                if set(actual_ids) != expected_ids or len(actual_ids) != len(
                    expected_ids
                ):
                    raise ValueError(
                        "Patent comparisons must map one-to-one to supplied evidence"
                    )
            except Exception as comparison_error:
                return PatentReport(
                    status="partial",
                    evidence=evidence,
                    unknowns=unknowns
                    + [
                        "특허 원문 검색은 완료했지만 비교 응답을 검증하지 못했습니다.",
                        "비교 단계 실패로 설계 대안 생성은 실행하지 않았습니다.",
                    ],
                    search_scope="아이디어 기술 요소별 Dense 검색 및 관련성 판정 후 비교",
                    error_message=f"특허 비교 응답 검증 실패: {comparison_error}",
                )
        else:
            try:
                patent_reviews, patentability_precheck = (
                    patent_review_fn or review_patents_by_component
                )(request.idea, evidence)
            except Exception as review_error:
                return PatentReport(
                    status="partial",
                    evidence=evidence,
                    unknowns=unknowns
                    + [
                        "특허 원문 검색은 완료했지만 구성요소 비교 생성에 실패했습니다.",
                        "비교 단계 실패로 설계 대안 생성은 실행하지 않았습니다.",
                    ],
                    search_scope=(
                        "아이디어 기술 요소별 특허 후보 검색과 원문 근거 확보 완료; "
                        "구성요소 비교 생성 실패"
                    ),
                    error_message=f"특허 비교 생성 실패: {review_error}",
                    indexed_statistics=indexed_statistics,
                    related_statistics=calculate_patent_statistics(
                        [
                            item.document.metadata
                            | {"source_id": item.document.source_id}
                            for item in related_candidates
                        ],
                        scope="아이디어 관련 검색 후보",
                    ),
                )
            for review in patent_reviews:
                unknowns.extend(f"{review.title}: {item}" for item in review.unknowns)
        try:
            if not patent_reviews and design_proposal_fn is None:
                design_analysis = PatentDesignAnalysis(
                    status="insufficient_evidence",
                    evidence_level=(
                        "claims_and_abstract"
                        if any(item.section == "claims" for item in evidence)
                        and any(item.section == "abstract" for item in evidence)
                        else (
                            "claims_only"
                            if any(item.section == "claims" for item in evidence)
                            else "abstract_only"
                        )
                    ),
                    missing_information=[
                        "문헌별 기술 구성요소 비교가 없어 설계 대안을 생성하지 않았습니다."
                    ],
                )
            else:
                design_analysis = (
                    design_proposal_fn or generate_patent_design_analysis
                )(request.idea, evidence, patent_reviews, patentability_precheck)
            if design_analysis.status in {"partial", "insufficient_evidence"}:
                unknowns.extend(design_analysis.missing_information)
        except Exception as design_error:
            design_analysis = PatentDesignAnalysis(
                status="failed",
                evidence_level=(
                    "claims_and_abstract"
                    if any(item.section == "claims" for item in evidence)
                    and any(item.section == "abstract" for item in evidence)
                    else (
                        "claims_only"
                        if any(item.section == "claims" for item in evidence)
                        else "abstract_only"
                    )
                ),
                missing_information=["설계 대안 분석을 완료하지 못했습니다."],
                limitations=[f"대안 생성 단계 오류: {type(design_error).__name__}"],
            )
            unknowns.append(
                "설계 대안 생성에 실패했지만 특허 검색 근거와 기존 비교 결과는 보존했습니다."
            )
        return PatentReport(
            status="completed",
            evidence=evidence,
            comparisons=comparisons,
            patent_reviews=patent_reviews,
            patentability_precheck=patentability_precheck,
            design_analysis=design_analysis,
            indexed_statistics=indexed_statistics,
            related_statistics=calculate_patent_statistics(
                [
                    item.document.metadata | {"source_id": item.document.source_id}
                    for item in related_candidates
                ],
                scope="아이디어 관련 검색 후보",
            ),
            unknowns=unknowns,
            search_scope=(
                f"아이디어 기술 요소별 {retrieval_mode} 후보 검색·LLM 관련성 판정"
                + (
                    "· 분야 결과 부족으로 전체 색인 보충"
                    if used_global_fallback
                    else ""
                )
                + "; 후보 부족 시 KIPRIS 검색; "
                "청구항 원문 조회는 선택된 최대 8개 문헌에 한함"
            ),
        )
    except Exception as exc:
        return PatentReport(
            status="error",
            evidence=evidence,
            search_scope="아이디어 기술 요소별 특허 검색 및 청구항 분석",
            error_message=str(exc),
            unknowns=unknowns
            + [
                "특허 비교 분석 중 오류가 발생했습니다. 확보된 원문 근거는 보존했습니다."
            ],
        )
