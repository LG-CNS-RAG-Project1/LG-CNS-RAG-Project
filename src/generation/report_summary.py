"""Render compact patent, market, and business summaries for the final report."""

from src.generation.business_review import BusinessReview, RECOMMENDATION_LABELS
from src.generation.report_formatting import (
    CONFIDENCE_LABELS,
    PATENTABILITY_STATUS_LABELS,
    PATENT_COMPONENT_STATUS_LABELS,
    PATENT_RELEVANCE_LABELS,
    escape_md,
    patent_location,
)
from src.retrieval.market_relevance import DIMENSION_LABELS
from src.schemas import IdeaDraft, MarketReport, PatentReport


def _compact_text(value: str | None, limit: int = 140) -> str:
    """최종 요약에 쓸 문장을 길이 제한과 Markdown 이스케이프를 적용해 반환한다."""
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return escape_md(text)


def _compact_refs(values: list[int] | list[str], limit: int = 3) -> str:
    refs = [str(value) for value in values[:limit]]
    return ", ".join(refs) if refs else "근거 인용 없음"


def _compact_patent_lines(patent: PatentReport) -> list[str]:
    lines = ["## 특허 핵심", ""]
    if patent.status == "error":
        return lines + [f"- 조사 실패: {_compact_text(patent.error_message, 120)}", ""]
    if patent.status == "partial":
        lines.append("- 원문 근거는 확보했지만 비교 분석 일부가 완료되지 않았습니다.")
        if patent.error_message:
            lines.append(f"- 비교 오류: {_compact_text(patent.error_message, 120)}")
    if patent.status == "no_results":
        return lines + [
            "- 검색 범위에서 비교 근거를 확보하지 못함. 특허 위험이 없다는 뜻은 아닙니다.",
            "",
        ]

    statistics = patent.indexed_statistics
    related_statistics = patent.related_statistics
    if statistics:
        top_ipc = (
            " · ".join(
                f"{item.label} {item.count}건"
                for item in statistics.ipc_distribution[:3]
            )
            or "IPC 분류 미확보"
        )
        related_count = (
            f"관련 후보 {related_statistics.total_patents}건"
            if related_statistics
            else "관련 후보 분류 미확인"
        )
        lines.append(
            f"- 색인 기술 동향: {_compact_text(top_ipc, 100)} · {related_count}"
        )

    evidence_by_id = {item.citation_id: item for item in patent.evidence}
    precheck = patent.patentability_precheck
    if precheck:
        refs = _compact_refs([f"P:{item}" for item in precheck.citation_ids])
        lines.append(
            f"- 예비 신호: **{PATENTABILITY_STATUS_LABELS[precheck.status]}** · "
            f"{_compact_text(precheck.summary, 180)} ({refs})"
        )

    if patent.patent_reviews:
        for review in patent.patent_reviews[:2]:
            lines += [
                "",
                f"- **{_compact_text(review.title, 55)}** · 관련성 {PATENT_RELEVANCE_LABELS[review.relevance]}",
                f"  - {_compact_text(review.overall_summary, 130)}",
            ]
            comparisons = sorted(
                review.component_comparisons,
                key=lambda item: {
                    "overlap": 0,
                    "partial": 1,
                    "uncertain": 2,
                    "different": 3,
                    "not_found": 4,
                }[item.status],
            )[:2]
            for comparison in comparisons:
                refs = _compact_refs([f"P:{item}" for item in comparison.citation_ids])
                note = (
                    comparison.overlap
                    or comparison.difference
                    or comparison.uncertainty
                )
                lines.append(
                    f"  - {PATENT_COMPONENT_STATUS_LABELS[comparison.status]}: "
                    f"{_compact_text(comparison.idea_component, 45)} — "
                    f"{_compact_text(note, 100)} ({refs})"
                )
                for citation_id in comparison.citation_ids[:1]:
                    evidence = evidence_by_id.get(citation_id)
                    if evidence:
                        lines.append(
                            f"    - 근거 {patent_location(evidence)}: "
                            f"{_compact_text(evidence.quote, 100)} [P:{citation_id}]"
                        )
    elif patent.comparisons:
        for comparison in patent.comparisons[:2]:
            evidence = evidence_by_id.get(comparison.citation_id)
            if evidence:
                lines.append(
                    f"- {_compact_text(evidence.title, 55)} · 유사점 {_compact_text(comparison.similarity, 80)} · "
                    f"차이 {_compact_text(comparison.difference, 80)} "
                    f"[P:{comparison.citation_id}]"
                )
    else:
        lines.append("- 구성요소별 비교 결과가 충분하지 않습니다.")

    if precheck and precheck.distinction_hypotheses:
        lines.append(
            f"- 검토할 차별점: {_compact_text(precheck.distinction_hypotheses[0], 120)}"
        )
    lines += [
        "- 범위: 검색 문헌 기반 예비 비교이며 등록 가능성·침해 여부를 확정하지 않습니다.",
        "",
    ]
    return lines


def _compact_market_lines(market: MarketReport) -> list[str]:
    lines = ["## 시장성 핵심", ""]
    if market.status == "error":
        return lines + [f"- 조사 실패: {_compact_text(market.error_message, 120)}", ""]
    if market.status == "no_results":
        return lines + [
            "- 시장 근거를 확보하지 못함. 시장 수요가 없다는 뜻은 아닙니다.",
            "",
        ]

    review = market.opportunity_review
    if review:
        labels = {
            "validated_demand": "직접 고객 검증 자료 있음",
            "buyer_signals": "구매자 신호",
            "indirect_signals": "간접 산업 신호",
            "insufficient_evidence": "근거 부족",
        }
        lines.append(
            f"- 수요 근거: **{labels[review.status]}** · 목표 고객: "
            f"{_compact_text(review.target_segment or '미확인', 70)}"
        )
        for finding in review.reasons[:2]:
            refs = _compact_refs([f"M:{item}" for item in finding.citation_ids])
            lines.append(
                f"- {_compact_text(finding.topic, 35)}: "
                f"{_compact_text(finding.statement, 115)} ({refs})"
            )
    commercial = market.commercial_analysis
    if commercial and commercial.hypotheses:
        lines += ["- LLM 가설 (검증 전이며 확인된 수요가 아님):"]
        for hypothesis in commercial.hypotheses[:2]:
            refs = _compact_refs([f"M:{item}" for item in hypothesis.citation_ids])
            lines.append(
                f"  - {_compact_text(hypothesis.hypothesis, 105)} "
                f"(검증: {_compact_text(hypothesis.validation_method, 70)}; "
                f"성공 기준: {_compact_text(hypothesis.success_criterion, 65)}"
                + (f"; {refs}" if refs else "; 직접 근거 인용 없음")
                + ")"
            )

    dimension_labels = {
        "confirmed": "확인",
        "signal_only": "신호",
        "unverified": "미확인",
    }
    dimension_lines = []
    for dimension in market.dimensions:
        refs = dict.fromkeys(
            citation_id
            for claim in dimension.claims
            for citation_id in claim.citation_ids
        )
        if dimension.verdict != "unverified" or refs:
            dimension_lines.append(
                f"{DIMENSION_LABELS[dimension.dimension]} {dimension_labels[dimension.verdict]} "
                f"({_compact_refs([f'M:{item}' for item in refs])})"
            )
    if dimension_lines:
        lines.append("- 차원별 신호: " + " · ".join(dimension_lines[:5]))
    lines += [
        "- 뉴스·기업 자료는 산업 신호이며, 직접 구매 의사로 보지 않습니다.",
        "",
    ]
    return lines


def _compact_business_lines(review: BusinessReview) -> list[str]:
    lines = [
        "## 실행 전 판단",
        "",
        f"- **권고: {RECOMMENDATION_LABELS[review.recommendation]}** · 신뢰도 {CONFIDENCE_LABELS[review.confidence]}",
        f"- {_compact_text(review.summary, 220)}",
    ]
    if review.opportunities:
        lines.append(
            "- 기회: "
            + " · ".join(
                _compact_text(item.finding, 105) for item in review.opportunities[:2]
            )
        )
    if review.risks:
        lines.append(
            "- 위험: "
            + " · ".join(_compact_text(item.finding, 105) for item in review.risks[:2])
        )
    if review.unknowns:
        lines.append(
            "- 핵심 미확인: "
            + " · ".join(_compact_text(item, 75) for item in review.unknowns[:3])
        )
    lines += ["", "## 다음 행동", ""]
    if review.next_steps:
        for action in review.next_steps[:3]:
            refs = (
                f" ({_compact_refs(action.citation_ids)})"
                if action.citation_ids
                else ""
            )
            lines.append(
                f"- **{_compact_text(action.horizon, 25)} · {_compact_text(action.target, 55)}:** "
                f"{_compact_text(action.action, 140)}{refs}"
            )
    else:
        lines.append(
            "- 추가 행동이 정해지지 않았습니다. 고객·특허 전문가와 후속 확인을 진행하세요."
        )
    lines += ["", f"> {_compact_text(review.scope_note, 180)}", ""]
    return lines


def _cross_analysis_lines(patent: PatentReport, market: MarketReport) -> list[str]:
    """특허 비교 신호와 시장 근거 상태를 나란히 보여주는 짧은 교차표를 만든다."""
    precheck = patent.patentability_precheck
    patent_signal = (
        PATENTABILITY_STATUS_LABELS[precheck.status]
        if precheck and precheck.citation_ids
        else "특허 비교 근거 부족"
    )
    market_review = market.opportunity_review
    market_labels = {
        "validated_demand": "직접 고객 검증 자료 있음",
        "buyer_signals": "구매자 관련 공개 신호",
        "indirect_signals": "간접 산업 신호",
        "insufficient_evidence": "수요 근거 부족",
    }
    market_signal = (
        market_labels.get(market_review.status, "시장 판단 자료 없음")
        if market_review
        else "시장 판단 자료 없음"
    )
    patent_refs = (
        _compact_refs([f"P:{item}" for item in precheck.citation_ids])
        if precheck and precheck.citation_ids
        else "인용 근거 없음"
    )
    market_refs = (
        _compact_refs(
            [
                f"M:{citation_id}"
                for reason in market_review.reasons
                for citation_id in reason.citation_ids
            ]
        )
        if market_review
        else "인용 근거 없음"
    )
    directions: list[tuple[str, str]] = []
    if (
        market.status in {"error", "no_results"}
        or not market_review
        or market_review.status == "insufficient_evidence"
    ):
        directions.append(("고객 인터뷰와 문제·지불의사 검증을 우선", market_refs))
    elif precheck and precheck.citation_ids and precheck.status == "overlap_concern":
        directions.append(
            ("수요 신호와 별도로 청구항 대조 및 차별 구성 검토", patent_refs)
        )
    elif (
        precheck and precheck.citation_ids and precheck.status == "potentially_distinct"
    ):
        directions.append(
            (
                "차별 구성은 예비 신호로 두고 고객 조건을 확인한 제한 파일럿 검토",
                f"{patent_refs} · {market_refs}",
            )
        )
    else:
        directions.append(
            ("특허 범위 확인과 고객 검증을 병행", f"{patent_refs} · {market_refs}")
        )

    for dimension in market.dimensions:
        has_citations = any(claim.citation_ids for claim in dimension.claims)
        if (
            dimension.dimension == "adoption_barrier"
            and dimension.verdict != "unverified"
            and has_citations
        ):
            refs = _compact_refs(
                [f"M:{cid}" for claim in dimension.claims for cid in claim.citation_ids]
            )
            directions.append(
                ("도입 비용·설치 장벽을 확인하고 저비용 MVP 가설 검증", refs)
            )
            break
    for dimension in market.dimensions:
        has_citations = any(claim.citation_ids for claim in dimension.claims)
        if (
            dimension.dimension == "competition"
            and dimension.verdict != "unverified"
            and has_citations
        ):
            refs = _compact_refs(
                [f"M:{cid}" for claim in dimension.claims for cid in claim.citation_ids]
            )
            directions.append(
                ("경쟁·대체재 근거를 확인해 목표 고객과 가치 제안 재검토", refs)
            )
            break
    rows = [
        "| 특허 분석 | 시장 분석 | 종합 검토 방향 |",
        "|---|---|---|",
        f"| {_compact_text(patent_signal, 70)} ({patent_refs}) | {_compact_text(market_signal, 70)} ({market_refs}) | {_compact_text(directions[0][0], 100)} |",
    ]
    for direction, references in directions[1:]:
        rows.append(
            f"| 특허와 별도 확인 | {_compact_text(references, 45)} | {_compact_text(direction, 100)} |"
        )
    return [
        "## 특허와 시장 근거의 교차 분석",
        "",
        *rows,
        "",
        "특허 검색 결과만으로 사업성을 판단하지 않습니다. 시장 근거가 부족한 결론은 검증 가설로 남깁니다.",
        "",
    ]
