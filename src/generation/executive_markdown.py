"""Render the final cross-domain executive report in Markdown."""

from datetime import datetime

from src.generation.executive_review import (
    ExecutiveReview,
    RECOMMENDATION_LABELS,
    cross_domain_findings,
    executive_limitations,
    executive_next_checks,
)
from src.generation.report_formatting import escape_md


def _market_context_markdown(market) -> list[str]:
    """실제 MarketReport 값만 참고 맥락으로 옮기고 수요 결론과 분리한다."""
    if market is None:
        return []

    from src.generation.market_markdown import (
        cell,
        keyword_network_summary,
        search_trend_summary,
    )
    from src.retrieval.market_relevance import DIMENSION_LABELS

    dart_evidence = []
    seen_companies = set()
    for evidence in market.evidence:
        if evidence.source_type != "dart":
            continue
        company = evidence.publisher or "공시 기업 미제공"
        if company in seen_companies:
            continue
        seen_companies.add(company)
        dart_evidence.append(evidence)
        if len(dart_evidence) == 3:
            break

    trend = market.search_trend
    network = market.keyword_network
    if not (dart_evidence or trend or network or market.dimensions):
        return []

    lines = ["", "## 시장 맥락 (참고)", ""]
    if market.dimensions:
        verdict_labels = {
            "confirmed": "확인됨",
            "signal_only": "신호만 확인",
            "unverified": "미확인",
        }
        evidence_labels = {
            "sufficient": "관련 근거 충분",
            "limited": "관련 근거 제한적",
            "insufficient": "관련 근거 부족",
            "no_results": "검색 결과 없음",
            "error": "판정 오류",
        }
        lines.append("- **차원별 확인 상태:**")
        for dimension in market.dimensions:
            status = evidence_labels.get(dimension.evidence_status or "", "상태 미제공")
            count = (
                f" · 관련 자료 {dimension.relevant_count}건"
                if dimension.relevant_count is not None
                else ""
            )
            limitation = (
                f" · {cell(dimension.limitation)}" if dimension.limitation else ""
            )
            lines.append(
                f"  - {DIMENSION_LABELS[dimension.dimension]}: "
                f"{verdict_labels[dimension.verdict]} · {status}{count}{limitation}"
            )

    if dart_evidence:
        lines += [
            "",
            "- **DART 기업 공시 맥락:** 기업 자체 사업 설명이며 시장 전체 수요나 특허 보유 관계를 입증하지 않습니다.",
        ]
        for evidence in dart_evidence:
            company = cell(evidence.publisher or "공시 기업 미제공")
            period = cell(evidence.period or "사업연도 미제공")
            section = cell(evidence.section or "원문 위치 미제공")
            quote = cell(evidence.quote)
            if len(quote) > 260:
                quote = quote[:260].rstrip() + "…"
            lines.append(
                f"  - M:{evidence.citation_id} · {company} · {period} · {section}"
                f" · {cell(evidence.title)} — {quote}"
            )
        lines.append(
            "  - 현재 특허 근거 계약에는 출원인 정보가 없어 공시 기업과 특허 출원인의 동일성은 확인되지 않았습니다."
        )

    if trend:
        lines += ["", f"- **검색 관심도:** {cell(search_trend_summary(trend))}"]
        lines.append(
            "  - 기준 검색어 대비 상대 지수이며 시장 규모나 고객 수요의 근거가 아닙니다."
        )

    if network:
        lines += [
            "",
            f"- **키워드 동시 출현:** {cell(keyword_network_summary(network))}",
        ]
        if network.status == "completed" and network.clusters:
            lines.append(
                "  - 주제 묶음: "
                + " / ".join(
                    " · ".join(cell(term) for term in group[:4])
                    for group in network.clusters[:3]
                )
            )
        if network.note:
            lines.append(f"  - {cell(network.note)}")
        lines.append(
            "  - 같은 뉴스에서 함께 다뤄진 주제이며 수요·인과 관계를 뜻하지 않습니다."
        )

    return lines


def executive_report_markdown(
    title: str,
    review: ExecutiveReview,
    *,
    analyzed_on: int | None = None,
    cost_estimate=None,
    cost_totals=None,
    market=None,
    swot=None,
    canvas=None,
) -> str:
    """특허·시장 교차 결론과 다음 확인만 담은 간결한 최종 검토 문서.

    swot(SwotAnalysis)을 주면 시장 맥락 뒤에 'SWOT 분석 (예비)' 절을 넣고,
    canvas(BusinessCanvas)를 주면 그 뒤에 '비즈니스 모델 캔버스 (예비)' 절을 넣는다.
    """
    from datetime import datetime

    date_label = (
        datetime.strptime(str(analyzed_on), "%Y%m%d").strftime("%Y-%m-%d")
        if analyzed_on
        else datetime.now().strftime("%Y-%m-%d")
    )

    findings = cross_domain_findings(review)
    combined = bool(findings)
    recommendation = (
        RECOMMENDATION_LABELS.get(review.recommendation, review.recommendation)
        if combined
        else "추가 확인 후 결정"
    )
    decision = (
        review.decision_summary
        if combined
        else "특허와 시장 양쪽 근거가 함께 확인될 때까지 통합 결론을 보류합니다."
    )
    lines = [
        f"# 종합 검토 | {escape_md(title) or '아이디어'}",
        "",
        f"> 검토일 {date_label}",
        "",
        "## 종합 결론",
        "",
        f"- **판단:** {recommendation}",
        f"- {escape_md(decision)}",
        "",
        "## 결론 근거",
        "",
    ]
    if findings:
        for finding in findings:
            references = ", ".join(finding.evidence_ids)
            lines.append(
                f"- **{escape_md(finding.label)}:** {escape_md(finding.judgment)} "
                f"— {escape_md(finding.business_implication)} ({escape_md(references)})"
            )
    else:
        lines += ["- 특허와 시장 근거 ID가 함께 연결된 결론이 없어 판단을 보류합니다."]
    lines += _market_context_markdown(market)
    if swot is not None:
        from src.generation.swot import swot_markdown_lines

        lines += swot_markdown_lines(swot)
    if canvas is not None:
        from src.generation.business_canvas import canvas_markdown_lines

        lines += canvas_markdown_lines(canvas)
    limitations = executive_limitations(review)
    lines += ["", "## 판단 한계", ""]
    lines.extend(f"- {escape_md(item)}" for item in limitations[:3])
    if not limitations:
        lines.append("- 상세 특허·시장 보고서의 검색 범위와 근거 한계를 따릅니다.")
    lines += ["", "## 다음 확인", ""]
    lines.extend(f"- {escape_md(item)}" for item in executive_next_checks(review))
    lines += [
        "",
        "> 사업 검토용 예비 정리이며 법률 의견이나 사업 성공 보장이 아닙니다.",
        "",
    ]
    return "\n".join(lines)
