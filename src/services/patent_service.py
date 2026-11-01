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
from src.retrieval.patent_search import (
    build_patent_queries,
    search_patents,
    semantic_similarity_scores,
)
from src.retrieval.patent_relevance import judge_patent_candidates
from src.retrieval.engine import RetrievalConfig
from src.schemas import (
    PatentComparison,
    PatentDesignAnalysis,
    PatentClaim,
    PatentEvidence,
    PatentReport,
    PatentSearchRequest,
)
from src.ingestion.patent_processor import structure_claims

from src.services.patent_candidates import (
    KIPRIS_SUPPLEMENT_QUERY_LIMIT,
    _candidate_rank_key,
    _evidence_search_trace,
    _kipris_supplement_queries,
    _merge_retrieval_results,
    _metadata_codes,
    _retrieval_trace,
    _supplement_result,
    _tag_retrieval_result,
)
from src.services.patent_context import (
    _build_patent_context,
    _estimate_text_tokens,
    _select_claims,
)

ROOT_DIR = Path(__file__).resolve().parents[2]

MIN_RECOMMENDED_PATENTS = 5
SEMANTIC_SIMILARITY_MODEL = "text-embedding-3-small"
SEMANTIC_DOCUMENT_MAX_CHARS = 6000


def score_patent_semantic_similarity(idea, evidence, source_texts, embed_fn):
    """아이디어 기술 내용과 각 특허의 제목·초록·청구항을 같은 모델로 비교한다."""
    query_parts = [
        ("아이디어 제목", idea.title),
        ("해결할 문제", idea.problem),
        ("핵심 기술", idea.technology),
        ("기술 구성요소", " ".join(idea.technical_components)),
        ("차별점", idea.difference),
    ]
    query = "\n".join(f"{label}: {value}" for label, value in query_parts if value)

    grouped = defaultdict(lambda: {"title": "", "sections": []})
    seen = defaultdict(set)
    for item in evidence:
        text = (source_texts.get(item.citation_id) or item.quote or "").strip()
        if not text or text in seen[item.patent_id]:
            continue
        seen[item.patent_id].add(text)
        record = grouped[item.patent_id]
        record["title"] = record["title"] or item.title
        section = "초록" if item.section == "abstract" else "청구항"
        if item.claim_number:
            section += f" {item.claim_number}"
        record["sections"].append(f"{section}: {text}")

    patent_ids = list(grouped)
    document_texts = [
        (
            f"특허 제목: {grouped[patent_id]['title']}\n"
            + "\n".join(grouped[patent_id]["sections"])
        )[:SEMANTIC_DOCUMENT_MAX_CHARS]
        for patent_id in patent_ids
    ]
    scores = semantic_similarity_scores(query, document_texts, embed_fn)
    return dict(zip(patent_ids, scores))


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
    semantic_similarity_fn: Callable | None = None,
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
                    else f"아이디어 기술 요소별 {retrieval_mode} 검색 및 필요 시 KIPRIS 후보 보충"
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
                            representative_drawing_url=meta.get(
                                "representative_drawing_url"
                            ),
                            representative_thumbnail_url=meta.get(
                                "representative_thumbnail_url"
                            ),
                            representative_drawing_caption=meta.get(
                                "representative_drawing_caption"
                            ),
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
                        representative_drawing_url=meta.get(
                            "representative_drawing_url"
                        ),
                        representative_thumbnail_url=meta.get(
                            "representative_thumbnail_url"
                        ),
                        representative_drawing_caption=meta.get(
                            "representative_drawing_caption"
                        ),
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
                        representative_drawing_url=meta.get(
                            "representative_drawing_url"
                        ),
                        representative_thumbnail_url=meta.get(
                            "representative_thumbnail_url"
                        ),
                        representative_drawing_caption=meta.get(
                            "representative_drawing_caption"
                        ),
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

        semantic_similarity_model = None
        if semantic_similarity_fn is not None:
            semantic_similarity_model = SEMANTIC_SIMILARITY_MODEL
            try:
                scores = semantic_similarity_fn(request.idea, evidence, source_texts)
                evidence = [
                    PatentEvidence.model_validate(
                        {
                            **item.model_dump(),
                            "semantic_similarity": scores.get(item.patent_id),
                        }
                    )
                    for item in evidence
                ]
            except Exception as similarity_error:
                unknowns.append(
                    "후보 문헌 의미 유사도를 계산하지 못했습니다 "
                    f"({type(similarity_error).__name__}); 임베딩 설정과 사용량을 확인하세요."
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
                    semantic_similarity_model=semantic_similarity_model,
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
                    semantic_similarity_model=semantic_similarity_model,
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
            semantic_similarity_model=semantic_similarity_model,
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
