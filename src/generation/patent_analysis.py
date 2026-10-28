"""아이디어 기술 요소와 실제 특허 근거의 비교 초안을 생성한다."""

import json
import html
import re
from pathlib import Path
from typing import Callable
from urllib.parse import urlencode

from dotenv import load_dotenv
from openai import OpenAI

from src.schemas import (
    PatentComparison,
    PatentComponentComparison,
    PatentDocumentReview,
    PatentEvidence,
    PatentabilityPrecheck,
    StructuredIdea,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
LLM_MODEL = "gpt-4o-mini"


def kipris_application_search_url(application_number: str | None) -> str | None:
    """출원번호가 유효하면 공식 KIPRIS 통합 검색 URL을 만든다."""
    if not application_number:
        return None
    number = re.sub(r"[\s-]", "", str(application_number))
    if not number.isdigit() or not 6 <= len(number) <= 20:
        return None
    query = urlencode({"queryText": number})
    return f"https://www.kipris.or.kr/khome/search/searchResult.do?{query}"


PROMPT_PATH = ROOT_DIR / "prompts" / "patent_analysis.md"


def load_prompt() -> str:
    """특허 비교 생성 규칙을 저장된 프롬프트에서 읽는다."""
    return PROMPT_PATH.read_text(encoding="utf-8")


def call_comparison_llm(system_prompt: str, user_text: str) -> dict:
    """OpenAI JSON 응답을 반환한다."""
    load_dotenv(ROOT_DIR / ".env")
    client = OpenAI()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        temperature=0,
        max_tokens=6000,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
    )
    return json.loads(response.choices[0].message.content)


ComparisonLLMFn = Callable[[str, str], dict]


def _normalize_recommendations(review_data: dict, allowed_ids: set[int]) -> list[str]:
    """가설/근거 분류가 충돌하면 인용을 제거해 미검증 가설로 안전하게 낮춘다."""
    recommendations = review_data.get("design_recommendations") or []
    if not isinstance(recommendations, list):
        return []
    notes = []
    for recommendation in recommendations:
        if not isinstance(recommendation, dict):
            continue
        basis = recommendation.get("basis", "hypothesis")
        citations = recommendation.get("citation_ids") or []
        has_citations = bool(citations)
        valid_citations = (
            isinstance(citations, list)
            and all(
                isinstance(cid, int) and not isinstance(cid, bool) for cid in citations
            )
            and set(citations) <= allowed_ids
        )
        if basis == "evidence_based" and has_citations and valid_citations:
            continue
        if basis == "hypothesis" and not has_citations:
            continue
        recommendation["basis"] = "hypothesis"
        recommendation["citation_ids"] = []
        if not recommendation.get("validation_needed"):
            recommendation["validation_needed"] = (
                "해당 제안이 실제 청구항 범위와 맞는지 원문·전문가 검토로 확인"
            )
        note = (
            "설계 제안의 근거 분류와 citation ID가 일치하지 않아 인용 연결을 제거하고 "
            "검증 전 가설로 낮췄습니다."
        )
        if note not in notes:
            notes.append(note)
    return notes


def _is_transient_llm_error(error: Exception) -> bool:
    """Identify API failures that can succeed on one bounded retry."""
    return type(error).__name__ in {
        "APIConnectionError",
        "APITimeoutError",
        "RateLimitError",
        "InternalServerError",
        "TimeoutError",
        "ConnectionError",
    }


def _retry_user_text(
    payload: dict,
    raw,
    error: Exception,
    instruction: str,
    details: dict | None = None,
) -> str:
    """Build a correction request without sending raw API error details back to the model."""
    correction = {"previous_response": raw} if raw is not None else {}
    correction["retry_reason"] = (
        "응답 형식 또는 인용 검증 실패"
        if raw is not None
        else f"일시적 API 호출 오류({type(error).__name__})"
    )
    if raw is not None:
        correction["validation_error"] = str(error)
    correction.update(details or {})
    return (
        json.dumps(payload, ensure_ascii=False)
        + "\n\n"
        + instruction
        + "\n"
        + json.dumps(correction, ensure_ascii=False)
    )


def patent_review_priority(review: PatentDocumentReview) -> int:
    """비교 상태와 관련성을 함께 고려한 화면 정렬용 검토 우선순위."""
    statuses = {
        item.status for item in review.component_comparisons if item.citation_ids
    }
    if not statuses:
        return 4
    if review.relevance == "high" and "overlap" in statuses:
        return 0
    if "overlap" in statuses or (review.relevance == "high" and "partial" in statuses):
        return 1
    if review.relevance == "medium" or "partial" in statuses:
        return 2
    if review.relevance == "low":
        return 3
    return 4


PATENT_PRIORITY_LABELS = {
    0: "우선 확인",
    1: "주의",
    2: "검토",
    3: "낮은 관련성",
    4: "근거 부족",
}

PATENT_ORBIT_COLORS = {
    "red": "#c9473a",
    "yellow": "#d6a42c",
    "green": "#47846d",
    "blue": "#4a78a8",
}
PATENT_ORBIT_LABELS = {
    "red": "청구항 직접 대응 · 우선 확인",
    "yellow": "청구항 부분 대응 · 주의",
    "green": "기술 관계 참고 · 검토",
    "blue": "근거 부족 또는 관련성 낮음",
}


def patent_orbit_category(review: PatentDocumentReview, evidence_by_id: dict) -> str:
    """청구항 인용과 비교 결과로 시각화 우선순위를 정한다(법적 위험 등급 아님)."""
    claim_ids = {
        citation_id
        for item in review.component_comparisons
        for citation_id in item.citation_ids
        if citation_id in evidence_by_id
        and evidence_by_id[citation_id].section == "claims"
    }
    cited_statuses = {
        item.status for item in review.component_comparisons if item.citation_ids
    }
    if claim_ids and "overlap" in cited_statuses:
        return "red"
    if claim_ids and "partial" in cited_statuses:
        return "yellow"
    if (
        cited_statuses & {"overlap", "partial", "different"}
        or review.relevance == "medium"
    ):
        return "green"
    return "blue"


def highlight_verbatim_excerpt(quote: str, matched_text: str = "") -> str:
    """Escape untrusted source text and highlight only an exact verbatim match."""
    escaped_quote = html.escape(quote or "")
    if not matched_text or matched_text not in (quote or ""):
        return escaped_quote
    start = quote.index(matched_text)
    end = start + len(matched_text)
    return (
        html.escape(quote[:start])
        + "<mark><u>"
        + html.escape(matched_text)
        + "</u></mark>"
        + html.escape(quote[end:])
    )


def _align_verbatim_excerpt(quote: str, candidate: str) -> str:
    """Map whitespace-only model formatting differences to the exact source span."""
    quote = quote or ""
    candidate = candidate or ""
    if not candidate:
        return ""
    if candidate in quote:
        return candidate
    parts = [part for part in re.split(r"\s+", candidate.strip()) if part]
    if not parts:
        return ""
    match = re.search(r"\s+".join(re.escape(part) for part in parts), quote)
    return quote[match.start() : match.end()] if match else ""


def compare_patent_evidence(
    idea: StructuredIdea,
    evidence: list[PatentEvidence],
    llm_fn: ComparisonLLMFn = call_comparison_llm,
) -> list[PatentComparison]:
    """Generate evidence comparisons, correcting one-to-one citation mapping once."""
    if not evidence:
        return []
    evidence_ids = [item.citation_id for item in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("Supplied patent evidence must have unique citation IDs")

    payload = {
        "idea": idea.model_dump(),
        "evidence": [item.model_dump() for item in evidence],
        "required_citation_ids": evidence_ids,
    }
    system_prompt = load_prompt()
    user_text = json.dumps(payload, ensure_ascii=False)
    expected_ids = set(evidence_ids)
    last_error = None

    for attempt in range(2):
        raw = None
        response_received = False
        comparison_ids = []
        try:
            raw = llm_fn(system_prompt, user_text)
            response_received = True
            if not isinstance(raw, dict) or not isinstance(
                raw.get("comparisons"), list
            ):
                raise ValueError("Response must contain a comparisons list")
            comparisons = [
                PatentComparison.model_validate(item) for item in raw["comparisons"]
            ]
            comparison_ids = [item.citation_id for item in comparisons]
            if set(comparison_ids) != expected_ids or len(comparison_ids) != len(
                expected_ids
            ):
                raise ValueError(
                    "Patent comparisons must map one-to-one to supplied evidence"
                )
            by_id = {item.citation_id: item for item in comparisons}
            return [by_id[citation_id] for citation_id in evidence_ids]
        except Exception as exc:
            last_error = exc
            if not response_received and not _is_transient_llm_error(exc):
                raise
            if attempt == 0 and (response_received or _is_transient_llm_error(exc)):
                missing = sorted(expected_ids - set(comparison_ids))
                duplicated = sorted(
                    citation_id
                    for citation_id in set(comparison_ids)
                    if comparison_ids.count(citation_id) > 1
                )
                user_text = _retry_user_text(
                    payload,
                    raw,
                    exc,
                    "required_citation_ids의 각 ID에 대해 정확히 하나씩 비교를 반환하고, 원문 근거를 그대로 유지하세요.",
                    {
                        "required_citation_ids": evidence_ids,
                        "missing_citation_ids": missing,
                        "duplicated_citation_ids": duplicated,
                    },
                )
    if last_error is not None and not response_received:
        raise last_error
    raise ValueError(str(last_error)) from last_error


def review_patents_by_component(
    idea: StructuredIdea,
    evidence: list[PatentEvidence],
    llm_fn: ComparisonLLMFn = call_comparison_llm,
) -> tuple[list[PatentDocumentReview], PatentabilityPrecheck]:
    """특허별 청구항을 묶어 아이디어 구성요소 대응과 등록 관련 예비 신호를 만든다."""
    if not evidence:
        return [], PatentabilityPrecheck(
            status="insufficient_evidence",
            summary="비교할 특허 원문 근거를 확보하지 못했습니다.",
            limitations=["검색 결과 없음은 관련 특허가 없다는 뜻이 아닙니다."],
        )

    components = [
        {"component_id": f"C{index}", "text": component}
        for index, component in enumerate(idea.technical_components, 1)
        if component.strip()
    ]
    if not components and idea.technology.strip():
        components = [{"component_id": "C1", "text": idea.technology.strip()}]

    grouped: dict[str, list[PatentEvidence]] = {}
    for item in evidence:
        grouped.setdefault(item.patent_id, []).append(item)
    patents = [
        {
            "patent_id": patent_id,
            "title": records[0].title,
            "evidence": [item.model_dump() for item in records],
        }
        for patent_id, records in grouped.items()
    ]
    payload = {
        "idea": idea.model_dump(),
        "components": components,
        "patents": patents,
        "required_patent_ids": list(grouped),
        "required_citation_ids": [item.citation_id for item in evidence],
    }
    system_prompt = load_prompt()
    user_text = json.dumps(payload, ensure_ascii=False)
    last_error = None
    for attempt in range(2):
        raw = None
        response_received = False
        missing_patent_ids = []
        duplicated_patent_ids = []
        component_mapping_errors = {}
        try:
            raw = llm_fn(system_prompt, user_text)
            response_received = True
            raw_reviews = raw.get("patent_reviews", [])
            if not isinstance(raw_reviews, list):
                raise ValueError("Response must contain a patent_reviews list")
            evidence_by_patent = {
                patent_id: {item.citation_id for item in records}
                for patent_id, records in grouped.items()
            }
            recommendation_notes = {}
            for item in raw_reviews:
                if isinstance(item, dict):
                    patent_id = item.get("patent_id")
                    allowed_ids = evidence_by_patent.get(patent_id, set())
                    recommendation_notes[patent_id] = _normalize_recommendations(
                        item, allowed_ids
                    )
            reviews = [
                PatentDocumentReview.model_validate(item) for item in raw_reviews
            ]
            for review in reviews:
                review.unknowns = list(
                    dict.fromkeys(
                        review.unknowns + recommendation_notes.get(review.patent_id, [])
                    )
                )
            assessment = PatentabilityPrecheck.model_validate(
                raw["patentability_precheck"]
            )
            actual_patents = [item.patent_id for item in reviews]
            if set(actual_patents) != set(grouped) or len(actual_patents) != len(
                grouped
            ):
                missing_patent_ids = sorted(set(grouped) - set(actual_patents))
                duplicated_patent_ids = sorted(
                    patent_id
                    for patent_id in set(actual_patents)
                    if actual_patents.count(patent_id) > 1
                )
                raise ValueError(
                    "Patent reviews must map one-to-one to supplied patents"
                )

            component_ids = {item["component_id"] for item in components}
            all_ids = {item.citation_id for item in evidence}
            if not set(assessment.citation_ids) <= all_ids:
                raise ValueError("Patent precheck references unknown citation")
            for finding in assessment.common_watchouts:
                if not set(finding.citation_ids) <= all_ids:
                    raise ValueError(
                        "Common patent watchout references unknown citation"
                    )
            for recommendation in assessment.common_design_recommendations:
                if not set(recommendation.citation_ids) <= all_ids:
                    raise ValueError(
                        "Common patent recommendation references unknown citation"
                    )
            for review in reviews:
                allowed = evidence_by_patent[review.patent_id]
                # A document-level summary may rely on only a subset of the
                # retrieved passages. Component comparisons carry their own
                # citations, so requiring every passage here rejects valid
                # model answers that cite only the passages they actually use.
                if not set(review.citation_ids) <= allowed:
                    raise ValueError(
                        f"Patent review references unknown citation for {review.patent_id}"
                    )
                mapped = [item.component_id for item in review.component_comparisons]
                if set(mapped) != component_ids or len(mapped) != len(component_ids):
                    component_mapping_errors[review.patent_id] = {
                        "missing_component_ids": sorted(component_ids - set(mapped)),
                        "duplicated_component_ids": sorted(
                            component_id
                            for component_id in set(mapped)
                            if mapped.count(component_id) > 1
                        ),
                    }
                    raise ValueError(
                        f"Component comparisons must map one-to-one for {review.patent_id}"
                    )
                for comparison in review.component_comparisons:
                    if not set(comparison.citation_ids) <= allowed:
                        raise ValueError(
                            "Component comparison references unknown citation"
                        )
                    if comparison.matched_text:
                        aligned = next(
                            (
                                excerpt
                                for item in evidence
                                if item.citation_id in comparison.citation_ids
                                and (
                                    excerpt := _align_verbatim_excerpt(
                                        item.quote, comparison.matched_text
                                    )
                                )
                            ),
                            "",
                        )
                        if aligned:
                            comparison.matched_text = aligned
                        elif attempt == 0:
                            raise ValueError(
                                "Matched patent text must be verbatim cited evidence"
                            )
                        else:
                            comparison.matched_text = ""
                            comparison.status = "uncertain"
                            note = (
                                f"{comparison.component_id}: 강조 구절을 인용 원문에서 "
                                "그대로 확인하지 못해 원문 강조를 생략함"
                            )
                            review.unknowns = list(
                                dict.fromkeys(review.unknowns + [note])
                            )
                    comparison.idea_component = next(
                        item["text"]
                        for item in components
                        if item["component_id"] == comparison.component_id
                    )
                for watchout in review.watchout_findings:
                    if not set(watchout.citation_ids) <= allowed:
                        raise ValueError("Patent watchout references unknown citation")
                for recommendation in review.design_recommendations:
                    if not set(recommendation.citation_ids) <= allowed:
                        raise ValueError(
                            "Design recommendation references unknown citation"
                        )
            if not set(assessment.citation_ids) <= all_ids:
                raise ValueError("Patentability precheck references unknown citation")

            reviews_by_id = {item.patent_id: item for item in reviews}
            ordered_reviews = [reviews_by_id[patent_id] for patent_id in grouped]
            return ordered_reviews, assessment
        except Exception as exc:
            last_error = exc
            if not response_received and not _is_transient_llm_error(exc):
                raise
            if attempt == 0 and (response_received or _is_transient_llm_error(exc)):
                user_text = _retry_user_text(
                    payload,
                    raw,
                    exc,
                    "모든 required_patent_ids와 각 특허의 component_id를 한 번씩 포함하세요. "
                    "citation_ids는 해당 특허의 제공 근거만 사용하고, matched_text는 인용 원문에 "
                    "그대로 있는 문구만 쓰세요. 법적 판단을 확정하지 마세요.",
                    {
                        "required_patent_ids": list(grouped),
                        "required_citation_ids": [
                            item.citation_id for item in evidence
                        ],
                        "missing_patent_ids": missing_patent_ids,
                        "duplicated_patent_ids": duplicated_patent_ids,
                        "component_mapping_errors": component_mapping_errors,
                    },
                )
    if last_error is not None and not response_received:
        raise last_error
    raise ValueError(str(last_error)) from last_error
