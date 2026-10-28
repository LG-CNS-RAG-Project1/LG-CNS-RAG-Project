"""아이디어 기술 요소와 실제 특허 근거의 비교 초안을 생성한다."""

import json
import html
from pathlib import Path
from typing import Callable

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
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
    )
    return json.loads(response.choices[0].message.content)


ComparisonLLMFn = Callable[[str, str], dict]


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
        raw = llm_fn(system_prompt, user_text)
        comparison_ids = []
        try:
            if not isinstance(raw, dict) or not isinstance(raw.get("comparisons"), list):
                raise ValueError("Response must contain a comparisons list")
            comparisons = [PatentComparison.model_validate(item) for item in raw["comparisons"]]
            comparison_ids = [item.citation_id for item in comparisons]
            if set(comparison_ids) != expected_ids or len(comparison_ids) != len(expected_ids):
                raise ValueError("Patent comparisons must map one-to-one to supplied evidence")
            by_id = {item.citation_id: item for item in comparisons}
            return [by_id[citation_id] for citation_id in evidence_ids]
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                missing = sorted(expected_ids - set(comparison_ids))
                duplicated = sorted(
                    citation_id for citation_id in set(comparison_ids)
                    if comparison_ids.count(citation_id) > 1
                )
                correction = {
                    "required_citation_ids": evidence_ids,
                    "previous_response": raw,
                    "validation_error": str(exc),
                    "missing_citation_ids": missing,
                    "duplicated_citation_ids": duplicated,
                }
                user_text = (
                    json.dumps(payload, ensure_ascii=False)
                    + "\n\n이전 응답을 수정하세요. 원문 근거를 유지하고 required_citation_ids의 각 ID에 대해 정확히 하나씩 비교를 반환하세요.\n"
                    + json.dumps(correction, ensure_ascii=False)
                )
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
        raw = llm_fn(system_prompt, user_text)
        try:
            reviews = [
                PatentDocumentReview.model_validate(item)
                for item in raw.get("patent_reviews", [])
            ]
            assessment = PatentabilityPrecheck.model_validate(
                raw["patentability_precheck"]
            )
            actual_patents = [item.patent_id for item in reviews]
            if set(actual_patents) != set(grouped) or len(actual_patents) != len(
                grouped
            ):
                raise ValueError(
                    "Patent reviews must map one-to-one to supplied patents"
                )

            component_ids = {item["component_id"] for item in components}
            all_ids = {item.citation_id for item in evidence}
            evidence_by_patent = {
                patent_id: {item.citation_id for item in records}
                for patent_id, records in grouped.items()
            }
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
                    raise ValueError(
                        f"Component comparisons must map one-to-one for {review.patent_id}"
                    )
                for comparison in review.component_comparisons:
                    if not set(comparison.citation_ids) <= allowed:
                        raise ValueError(
                            "Component comparison references unknown citation"
                        )
                    if comparison.matched_text and not any(
                        comparison.matched_text in item.quote
                        for item in evidence
                        if item.citation_id in comparison.citation_ids
                    ):
                        raise ValueError(
                            "Matched patent text must be verbatim cited evidence"
                        )
                    comparison.idea_component = next(
                        item["text"]
                        for item in components
                        if item["component_id"] == comparison.component_id
                    )
            if not set(assessment.citation_ids) <= all_ids:
                raise ValueError("Patentability precheck references unknown citation")

            reviews_by_id = {item.patent_id: item for item in reviews}
            ordered_reviews = [reviews_by_id[patent_id] for patent_id in grouped]
            return ordered_reviews, assessment
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                user_text = (
                    json.dumps(payload, ensure_ascii=False)
                    + "\n\n이전 응답을 수정하라. 모든 required_patent_ids를 한 번씩 포함하고, 각 특허마다 모든 component_id를 하나씩 비교하라. citation_ids는 해당 특허의 실제 근거 ID만 쓰라. 법적 등록 가능성을 확정하지 말라.\n"
                    + json.dumps(
                        {"previous_response": raw, "validation_error": str(exc)},
                        ensure_ascii=False,
                    )
                )
    raise ValueError(str(last_error)) from last_error
