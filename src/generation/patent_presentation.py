"""Presentation helpers for patent evidence and comparison status."""

import html

from src.schemas import PatentDocumentReview


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
