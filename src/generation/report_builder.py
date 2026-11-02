"""특허·시장 근거를 읽기 쉬운 통합 Markdown 보고서로 렌더링한다."""

from datetime import datetime


from src.generation.business_review import (
    BusinessReview,
    RECOMMENDATION_LABELS,
)
from src.retrieval.market_relevance import DIMENSION_LABELS
from src.generation.report_formatting import (
    CLAIM_TYPE_LABELS,
    CONFIDENCE_LABELS,
    PATENTABILITY_STATUS_LABELS,
    PATENT_COMPONENT_STATUS_LABELS,
    PATENT_RELEVANCE_LABELS,
    REPORT_STATUS_LABELS,
    RUN_STATE_LABELS,
    escape_md,
    escaped_market_report,
    evidence_period,
    patent_location,
    safe_url,
    _format_yyyymmdd,
)
from src.generation.report_summary import (
    _compact_business_lines,
    _compact_market_lines,
    _compact_patent_lines,
    _compact_refs,
    _compact_text,
    _cross_analysis_lines,
)

from src.generation.question_links import (
    BOTH_SIDES_SUMMARY,
    CRITERIA,
    HOLD_SUMMARY,
    LINK_ATTEMPTS,
    CriterionLink,
    LinkBatch,
    QuestionLink,
    build_question_links,
    call_report_llm,
    hold_link,
    link_questions_with_retry,
    salvage_question_links,
)
from src.schemas import IDEA_FIELDS, IdeaDraft, MarketReport, PatentReport

FIELD_LABELS = {
    "problem": "문제",
    "technology": "기술",
    "customers": "고객",
    "difference": "차별점",
    "revenue": "수익모델",
}
SOURCE_LABELS = {
    "extracted": "입력에서 추출",
    "user_answer": "재질문 답변",
    "ai_hypothesis": "AI 검증 가설",
    "unknown": "모름",
}
LINK_STATUS_LABELS = {"connected": "연결", "partial": "부분 연결", "hold": "판단 보류"}


def _brief_lines(draft: IdeaDraft) -> list[str]:
    """아이디어 입력과 항목별 출처를 Markdown 줄로 만든다."""
    lines = ["## 확정 브리프", "", "| 항목 | 내용 | 출처 |", "|---|---|---|"]
    fields = [
        *((field, FIELD_LABELS[field], getattr(draft, field)) for field in IDEA_FIELDS),
        ("current_alternative", "현재 대안", draft.current_alternative),
        ("target_segment", "목표 세그먼트", draft.target_segment),
        (
            "technical_components",
            "기술 구성요소",
            ", ".join(draft.technical_components),
        ),
        ("value_hypotheses", "가치 가설", "; ".join(draft.value_hypotheses)),
    ]
    for field, label, field_value in fields:
        source = SOURCE_LABELS.get(draft.field_sources.get(field, ""), "입력에서 추출")
        value = field_value or "모름"
        lines.append(f"| {label} | {escape_md(value)} | {source} |")
    return lines + [""]


def _run_lines(runs: dict) -> list[str]:
    """특허·시장 실행 상태와 부분 실패 사유를 보고서 줄로 만든다."""
    lines = [
        "## 분석 실행 상태",
        "",
        "| 영역 | 상태 | 소요 시간 | 메모 |",
        "|---|---|---|---|",
    ]
    for label, run in runs.items():
        if run is None:
            continue
        seconds = f"{run.seconds:.1f}초" if run.seconds is not None else "-"
        state = RUN_STATE_LABELS.get(run.state, run.state)
        lines.append(
            f"| {label} | {state} | {seconds} | {escape_md(run.message) or '-'} |"
        )
    return lines + [""]


def _patent_lines(patent: PatentReport) -> list[str]:
    """특허 근거·비교·한계를 통합 보고서 문장으로 정리한다."""
    lines = [
        "## 특허 조사",
        "",
        f"- 상태: {REPORT_STATUS_LABELS.get(patent.status, patent.status)}",
        f"- 범위: {escape_md(patent.search_scope)}",
    ]
    if patent.error_message:
        lines.append(f"- 오류: {escape_md(patent.error_message)}")
    evidence_by_id = {item.citation_id: item for item in patent.evidence}
    comparisons = {c.citation_id: c for c in patent.comparisons}
    if patent.patent_reviews:
        for review in patent.patent_reviews:
            first = (
                evidence_by_id[review.citation_ids[0]] if review.citation_ids else None
            )
            dates = " · ".join(
                f"{label} {value}"
                for label, value in (
                    (
                        "출원",
                        _format_yyyymmdd(first.application_date) if first else None,
                    ),
                    (
                        "공개",
                        _format_yyyymmdd(first.publication_date) if first else None,
                    ),
                )
                if value
            )
            url = safe_url(first.source_url) if first else None
            lines += [
                "",
                f"### {escape_md(review.title)}",
                "",
                f"- 문헌: {escape_md(review.patent_id)} · 관련성 {PATENT_RELEVANCE_LABELS[review.relevance]}"
                + (f" · {dates}" if dates else "")
                + (f" · [원문]({url})" if url else " · 원문 링크 미확인"),
                f"- 관련성 근거: {escape_md(review.relevance_reason)}",
                f"- 특허 단위 요약: {escape_md(review.overall_summary)}",
                "",
                "| 아이디어 구성 | 비교 상태 | 공통점 | 차이점 | 근거 | 미확인 |",
                "|---|---|---|---|---|---|",
            ]
            for comparison in review.component_comparisons:
                refs = (
                    ", ".join(f"P:{cid}" for cid in comparison.citation_ids) or "없음"
                )
                lines.append(
                    f"| {escape_md(comparison.idea_component)} | {PATENT_COMPONENT_STATUS_LABELS[comparison.status]} | "
                    f"{escape_md(comparison.overlap)} | {escape_md(comparison.difference)} | "
                    f"{refs} | {escape_md(comparison.uncertainty)} |"
                )
            for citation_id in review.citation_ids:
                evidence = evidence_by_id[citation_id]
                lines += [
                    "",
                    f"- [P:{citation_id}] {patent_location(evidence)} 원문: {escape_md(evidence.quote)}",
                ]
            for item in review.watchouts:
                lines.append(f"- 주의: {escape_md(item)}")
            for item in review.unknowns:
                lines.append(f"- 미확인: {escape_md(item)}")
    else:
        for evidence in patent.evidence:
            comparison = comparisons.get(evidence.citation_id)
            url = safe_url(evidence.source_url)
            lines += [
                "",
                f"### [P:{evidence.citation_id}] {escape_md(evidence.title)}",
                "",
                f"- 문헌: {escape_md(evidence.patent_id)}"
                + (f" · [원문]({url})" if url else " · 원문 링크 미확인"),
                f"- 근거 원문 ({patent_location(evidence)}): {escape_md(evidence.quote)}",
            ]
            if comparison:
                lines += [
                    f"- 유사점: {escape_md(comparison.similarity)}",
                    f"- 차이점: {escape_md(comparison.difference)}",
                    f"- 미확인: {escape_md(comparison.uncertainty)}",
                ]
    if patent.patentability_precheck:
        precheck = patent.patentability_precheck
        refs = ", ".join(f"P:{cid}" for cid in precheck.citation_ids) or "없음"
        lines += [
            "",
            "### 등록 관련 예비 신호 (법적 판단 아님)",
            "",
            f"- 상태: {PATENTABILITY_STATUS_LABELS[precheck.status]}",
            f"- 요약: {escape_md(precheck.summary)} ({refs})",
        ]
        lines += [
            f"- 차별점 가설: {escape_md(item)}"
            for item in precheck.distinction_hypotheses
        ]
        lines += [
            f"- 전문가 확인 질문: {escape_md(item)}"
            for item in precheck.expert_questions
        ]
        lines += [f"- 한계: {escape_md(item)}" for item in precheck.limitations]
    if patent.unknowns:
        lines += ["", "### 특허 미확인 사항", ""]
        lines += [f"- {escape_md(item)}" for item in patent.unknowns]
    return lines + [""]


def _business_review_lines(review: BusinessReview) -> list[str]:
    """예비 사업 권고와 검증 행동을 보고서 문장으로 만든다."""
    lines = [
        "## 한눈에 보는 사업 실행 검토",
        "",
        f"- 다음 행동 권고: **{RECOMMENDATION_LABELS[review.recommendation]}**",
        f"- 판단 신뢰 수준: {CONFIDENCE_LABELS[review.confidence]}",
        f"- 요약: {escape_md(review.summary)}",
        f"- 범위: {escape_md(review.scope_note)}",
        "",
        "### 권고 근거",
        "",
    ]
    for item in review.reasons:
        refs = ", ".join(item.citation_ids) or "근거 인용 없음"
        lines.append(
            f"- **{escape_md(item.topic)}:** {escape_md(item.finding)} ({refs})"
        )
    for title, entries in (("기회", review.opportunities), ("위험", review.risks)):
        lines += ["", f"### {title}", ""]
        if not entries:
            lines.append("- 현재 별도로 확인된 항목 없음")
        for item in entries:
            refs = ", ".join(item.citation_ids) or "근거 인용 없음"
            lines.append(f"- {escape_md(item.finding)} ({refs})")
    lines += ["", "### 다음 검증 행동", ""]
    for action in review.next_steps:
        refs = ", ".join(action.citation_ids)
        lines += [
            f"- **{escape_md(action.horizon)} · {escape_md(action.target)}:** {escape_md(action.action)}",
            f"  성공 신호: {escape_md(action.success_signal)}"
            + (f" ({refs})" if refs else ""),
        ]
    if review.unknowns:
        lines += ["", "### 결론을 바꿀 수 있는 미확인 사항", ""]
        lines += [f"- {escape_md(item)}" for item in review.unknowns]
    return lines + [""]


def integrated_report_markdown(
    title: str,
    questions: list[dict],
    links: list[QuestionLink],
    market: MarketReport,
    patent: PatentReport,
    *,
    draft: IdeaDraft | None = None,
    runs: dict | None = None,
    analyzed_on: int | None = None,
    market_collected_at: int | None = None,
    warnings: list[str] | None = None,
    business_review: BusinessReview | None = None,
) -> str:
    """핵심 의사결정 보고서를 짧게 렌더링한다. 세부 근거는 2·3단계에서 제공한다."""
    analyzed = _format_yyyymmdd(analyzed_on) or datetime.now().strftime("%Y-%m-%d")
    collected = _format_yyyymmdd(market_collected_at) or "미확인"
    lines = [
        f"# {escape_md(title) or '사업기획 검토 보고서'}",
        "",
        f"> 분석일 {analyzed} · 시장 자료 기준 {collected} · 근거 발행 범위 {evidence_period(market, patent)}",
        "",
    ]
    if business_review:
        lines += _compact_business_lines(business_review)
    else:
        lines += [
            "## 실행 전 판단",
            "",
            "- 통합 근거 검토 결과를 만들지 못해 진행 권고를 보류합니다.",
            "",
        ]
    if draft is not None:
        lines += [
            "## 아이디어 요약",
            "",
            f"- 문제: {_compact_text(draft.problem, 90) or '미확인'}",
            f"- 제안: {_compact_text(draft.technology, 90) or '미확인'}",
            f"- 고객: {_compact_text(draft.target_segment or draft.customers, 75) or '미확인'}",
            "",
        ]
    if warnings:
        lines += ["## 분석 메모", ""]
        lines += [f"- {_compact_text(item, 130)}" for item in warnings[:2]]
        lines.append("")
    lines += [
        *_compact_patent_lines(patent),
        *_compact_market_lines(market),
        *_cross_analysis_lines(patent, market),
        "> 상세 비교표·원문 인용·시장 분석은 특허 및 시장성 단계의 상세 근거에서 확인할 수 있습니다.",
    ]
    return "\n".join(lines) + "\n"
