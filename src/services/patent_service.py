"""특허 검색, 청구항 근거 보강 및 아이디어 비교의 서비스 경계."""

from collections import defaultdict
from typing import Callable

from src.generation.patent_analysis import compare_patent_evidence
from src.ingestion.kipris_client import KiprisAPIError, fetch_patent_claims
from src.retrieval.patent_search import build_patent_queries, search_patents
from src.retrieval.patent_relevance import judge_patent_candidates
from src.retrieval.schemas import RetrievalResult, SearchDocument
from src.schemas import (
    PatentComparison,
    PatentClaim,
    PatentEvidence,
    PatentReport,
    PatentSearchRequest,
)
from src.ingestion.patent_processor import structure_claims


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
        },
    )
    return RetrievalResult(document=document)


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
    """기술 표현과 토큰이 겹치는 청구항을 우선하되 독립항 근거를 우선 포함한다."""
    from src.retrieval.engine import tokenize

    idea_text = " ".join(idea.technical_components or [idea.technology, idea.problem])
    terms = set(tokenize(idea_text))
    scored = []
    for claim in claims:
        overlap = len(terms & set(tokenize(claim.text)))
        independent_priority = 1 if claim.claim_type == "independent" else 0
        scored.append((independent_priority, overlap, -claim.claim_number, claim))
    return [row[3] for row in sorted(scored, reverse=True)[:limit]]


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
    relevance_fn: Callable | None = None,
    candidate_k: int = 20,
) -> PatentReport:
    """특허 후보를 최대 5건 고르고 청구항 원문 근거와 비교 결과를 만든다.

    테스트와 다른 배포 환경은 collection 및 KIPRIS/LLM 함수들을 주입할 수 있다.
    """
    from src.ingestion.kipris_client import search_patents as search_kipris_patents

    claim_fetcher = claim_fetcher or fetch_patent_claims
    kipris_search_fn = kipris_search_fn or search_kipris_patents
    comparison_fn = comparison_fn or compare_patent_evidence
    relevance_fn = relevance_fn or judge_patent_candidates
    plan_kwargs = {"request": request}
    if query_llm_fn is not None:
        plan_kwargs["llm_fn"] = query_llm_fn

    try:
        plan = build_patent_queries(**plan_kwargs)
        queries = [
            query
            for item in plan.queries
            for query in item.korean_queries + item.english_queries
        ]
        retrieved_by_id = {}
        for query in dict.fromkeys(queries):
            for result in search_patents(
                query,
                collection=collection,
                embed_fn=embed_fn,
                top_k=max(candidate_k, request.top_k),
                technology_area_id=request.technology_area_id,
            ):
                previous = retrieved_by_id.get(result.document.source_id)
                current_score = (
                    result.dense_score
                    if result.dense_score is not None
                    else float("-inf")
                )
                previous_score = (
                    previous.dense_score
                    if previous and previous.dense_score is not None
                    else float("-inf")
                )
                if previous is None or current_score > previous_score:
                    retrieved_by_id[result.document.source_id] = result

        unknowns = []
        ordered_candidates = sorted(
            retrieved_by_id.values(),
            key=lambda item: (
                item.dense_score is not None,
                item.dense_score if item.dense_score is not None else 0,
            ),
            reverse=True,
        )[: max(candidate_k, request.top_k)]
        judgments = relevance_fn(request.idea, ordered_candidates)
        candidates = [
            item
            for item in ordered_candidates
            if judgments[item.document.source_id].relevant
        ][: request.top_k]

        if len(candidates) < request.top_k:
            for query in dict.fromkeys(queries):
                try:
                    records = kipris_search_fn(query, request.top_k - len(candidates))
                except KiprisAPIError as exc:
                    unknowns.append(f"KIPRIS 후보 보충 미실행: {exc}")
                    break
                added = []
                for record in records:
                    result = _supplement_result(record)
                    if result and result.document.source_id not in retrieved_by_id:
                        retrieved_by_id[result.document.source_id] = result
                        added.append(result)
                if added:
                    supplemental_judgments = relevance_fn(request.idea, added)
                    candidates.extend(
                        item
                        for item in added
                        if supplemental_judgments[item.document.source_id].relevant
                    )
                if len(candidates) >= request.top_k:
                    candidates = candidates[: request.top_k]
                    break
        if not candidates:
            return PatentReport(
                status="no_results",
                search_scope="아이디어 기술 요소별 Dense 검색 및 필요 시 KIPRIS 후보 보충",
                unknowns=unknowns or ["검색된 특허 후보가 없습니다."],
            )

        evidence = []
        source_texts = {}
        for result in candidates:
            document = result.document
            meta = document.metadata
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
                for claim in _select_claims(request.idea, claims):
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
                            application_date=meta.get("application_date"),
                            publication_date=meta.get("publication_date"),
                            claim_number=claim.claim_number,
                            claim_type=claim.claim_type,
                            depends_on=claim.depends_on,
                            version_id=claim.version_id or version_id,
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
                        application_date=meta.get("application_date"),
                        publication_date=meta.get("publication_date"),
                        claim_type="unclassified",
                        version_id=meta.get("version_id") or version_id,
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
                        application_date=meta.get("application_date"),
                        publication_date=meta.get("publication_date"),
                        version_id=version_id,
                    )
                )
                source_texts[evidence[-1].citation_id] = document.content
                unknowns.append(f"{app_number}: 청구항 원문 미확보, 초록만 확인됨")

        if not evidence:
            return PatentReport(
                status="no_results",
                search_scope="아이디어 기술 요소별 Dense 검색 및 필요 시 KIPRIS 후보 보충",
                unknowns=unknowns + ["검색 후보의 원문 근거를 확보하지 못했습니다."],
            )

        validate_patent_citations(evidence, source_texts)
        expected_ids = {item.citation_id for item in evidence}
        comparison_error = None
        comparisons = []
        for _ in range(2):
            try:
                comparisons = comparison_fn(request.idea, evidence)
                actual_ids = [item.citation_id for item in comparisons]
                if set(actual_ids) != expected_ids or len(actual_ids) != len(
                    expected_ids
                ):
                    raise ValueError(
                        "Patent comparisons must map one-to-one to supplied evidence"
                    )
                comparison_error = None
                break
            except Exception as exc:
                comparison_error = exc
        if comparison_error is not None:
            return PatentReport(
                status="error",
                evidence=evidence,
                unknowns=unknowns + ["특허 비교 생성이 재시도 후 실패했습니다."],
                search_scope="아이디어 기술 요소별 Dense 검색 및 관련성 판정 후 비교",
                error_message=str(comparison_error),
            )
        return PatentReport(
            status="completed",
            evidence=evidence,
            comparisons=comparisons,
            unknowns=unknowns,
            search_scope=(
                "아이디어 기술 요소별 Dense 후보 검색·LLM 관련성 판정; 후보 부족 시 KIPRIS 검색; "
                "청구항 원문 조회는 선택된 최대 5개 문헌에 한함"
            ),
        )
    except Exception as exc:
        return PatentReport(
            status="error",
            search_scope="아이디어 기술 요소별 특허 검색 및 청구항 분석",
            error_message=str(exc),
            unknowns=["분석 실행 중 오류가 발생해 결과를 확인하지 못했습니다."],
        )
