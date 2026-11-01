"""Render a MarketReport as the market analysis Markdown section."""

from src.retrieval.market_relevance import DIMENSION_LABELS
from src.schemas import MarketReport
from src.generation.market_markdown import (
    CLAIM_LABELS,
    EVIDENCE_NOTE,
    NATURE_LABELS,
    SECTION_TITLE,
    VERDICT_LABELS,
    cell,
    citation,
    company_financial_rows,
    company_financials_summary,
    evidence_row,
    format_date,
    format_won,
    keyword_network_summary,
    procurement_rows,
    procurement_stats,
    procurement_summary,
    safe_url,
    search_trend_summary,
)


def market_report_to_markdown(report: MarketReport, heading_level: int = 2) -> str:
    """MarketReport를 마크다운 섹션 문자열로 바꾼다.

    heading_level은 섹션 제목의 '#' 개수이며, 하위 제목은 한 단계 아래로 쓴다.
    completed가 아니면 상태와 미확인 사항·오류 안내만 쓴다.
    """
    h, sub = "#" * heading_level, "#" * (heading_level + 1)
    lines = [
        f"{h} {SECTION_TITLE}",
        "",
        f"- 분석 기준일: {format_date(report.data_as_of)}",
        f"- 검색 범위: {cell(report.search_scope)}",
    ]

    if report.status == "no_results":
        lines += ["", "검색 범위에서 시장 근거를 찾지 못해 차원별 판정을 하지 않았다."]
    elif report.status == "error":
        lines += [
            "",
            "시장 조사 중 오류가 발생해 결과를 만들지 못했다.",
            f"- 오류: {cell(report.error_message)}",
        ]
    else:
        lines += _dimension_sections(report, sub)

    if report.opportunity_review:
        review = report.opportunity_review
        status_labels = {
            "validated_demand": "직접 고객 검증 자료 있음",
            "buyer_signals": "구매자 신호 있음",
            "indirect_signals": "간접 산업 신호만 있음",
            "insufficient_evidence": "근거 부족",
        }
        lines += [
            "",
            f"{sub} 아이디어 시장성 요약",
            "",
            f"- 근거 상태: {status_labels[review.status]}",
            f"- 목표 세그먼트: {cell(review.target_segment) or '미확인'}",
        ]
        if review.value_hypotheses:
            lines.append("- 검증 전 가치 가설:")
            lines += [f"  - {cell(item)}" for item in review.value_hypotheses]
        for finding in review.reasons:
            refs = (
                ", ".join(citation(item) for item in finding.citation_ids)
                or "근거 인용 없음"
            )
            lines.append(f"- {cell(finding.topic)}: {cell(finding.statement)} ({refs})")
        if review.unknowns:
            lines.append("- 핵심 미확인:")
            lines += [f"  - {cell(item)}" for item in review.unknowns]
        if review.validation_actions:
            lines += ["", f"{sub} 다음 시장 검증", ""]
            for action in review.validation_actions:
                refs = ", ".join(citation(item) for item in action.citation_ids)
                lines += [
                    f"- **{cell(action.title)} · 대상: {cell(action.target) or '미정'}**",
                    f"  - 방법: {cell(action.method)}",
                    f"  - 성공 신호: {cell(action.success_signal)}"
                    + (f" ({refs})" if refs else ""),
                ]

    commercial = report.commercial_analysis
    if commercial and commercial.hypotheses:
        lines += [
            "",
            f"{sub} LLM 검증 전 가설 (확인된 사실·구매 의사가 아님)",
            "",
        ]
        for item in commercial.hypotheses:
            refs = ", ".join(citation(value) for value in item.citation_ids)
            lines += [
                f"- **가설:** {cell(item.hypothesis)}",
                f"  - 질문: {cell(item.question)} · 근거/한계: {cell(item.basis)}",
                f"  - 가정: {', '.join(cell(value) for value in item.assumptions) or '없음'}",
                f"  - 검증: {cell(item.validation_target)} · {cell(item.validation_method)} · 성공 기준: {cell(item.success_criterion)}",
            ]
            if item.numeric_value is not None:
                lines.append(
                    f"  - 자료 기반 수치 추정: {item.numeric_value:g} {cell(item.numeric_unit)} · 산식/자료: {cell(item.numeric_basis)}"
                )
            if refs:
                lines.append(f"  - 연결 근거: {refs}")

    trend = report.search_trend
    if trend:
        lines += [
            "",
            f"{sub} 검색 관심도 흐름",
            "",
            f"- {cell(search_trend_summary(trend))}",
        ]
        if trend.status == "completed":
            recent = [p for p in trend.points[-12:] if p.relative_index is not None]
            lines.append(
                "- 최근 12개월 지수(기준 대비): "
                + " · ".join(f"{p.period} {p.relative_index:g}" for p in recent)
            )
        if trend.note:
            lines += ["", f"> {cell(trend.note)}"]

    network = report.keyword_network
    if network:
        lines += [
            "",
            f"{sub} 키워드 동시 출현",
            "",
            f"- {cell(keyword_network_summary(network))}",
        ]
        if network.status == "completed":
            lines += [
                f"- 묶음 {i + 1}: {' · '.join(cell(t) for t in group)}"
                for i, group in enumerate(network.clusters)
            ]
        if network.note:
            lines += ["", f"> {cell(network.note)}"]

    financials = report.company_financials
    if financials:
        lines += [
            "",
            f"{sub} 인접 기업 재무 현황",
            "",
            f"- {cell(company_financials_summary(financials))}",
        ]
        rows = company_financial_rows(financials)
        if rows:
            headers = list(rows[0])
            lines += [
                "",
                "| " + " | ".join(headers) + " |",
                "|" + "---|" * len(headers),
            ]
            lines += [
                "| " + " | ".join(cell(str(r.get(h, "-"))) for h in headers) + " |"
                for r in rows
            ]
        lines += [f"- 재무 계정 없음: {cell(m)}" for m in financials.missing]
        lines += [
            f"- 연구개발비 근거({cell(c.company)}): {cell(c.rnd_basis)}"
            for c in financials.companies
            if c.rnd_basis
        ]
        if financials.note:
            lines += ["", f"> {cell(financials.note)}"]
    procurement = report.procurement
    if procurement:
        lines += [
            "",
            f"{sub} 공공 조달 공고",
            "",
            f"- {cell(procurement_summary(procurement))}",
        ]
        types = procurement_stats(procurement)["buyer_types"]
        if types:
            lines.append(
                "- 구매 주체: "
                + " · ".join(f"{cell(name)} {count}건" for name, count in types.items())
            )
        rows = procurement_rows(procurement, 10)
        if rows:
            lines += [
                "",
                "| 공고일 | 구분 | 수요기관(유형) | 공고명 | 예산 |",
                "|---|---|---|---|---|",
            ]
            for r in rows:
                title = (
                    f"[{cell(r['공고명'])}]({r['공고']})"
                    if r["공고"]
                    else cell(r["공고명"])
                )
                lines.append(
                    f"| {r['공고일']} | {r['구분']} | {cell(r['수요기관'])}({cell(r['유형'])})"
                    f" | {title} | {r['예산']} |"
                )
        if procurement.note:
            lines += ["", f"> {cell(procurement.note)}"]

    if report.unknowns:
        lines += ["", f"{sub} 미확인 사항", ""]
        lines += [f"- {cell(u)}" for u in report.unknowns]

    if report.status == "completed" and report.evidence:
        lines += [
            "",
            f"{sub} 근거 목록",
            "",
            "| 번호 | 제목 | 출처 | 발행일 | 근거 성격 | 신뢰도·최신성 | 인용문 |",
            "|---|---|---|---|---|---|---|",
        ]
        lines += [evidence_row(e) for e in report.evidence]
        lines += ["", f"> {EVIDENCE_NOTE}"]
    return "\n".join(lines) + "\n"


def _dimension_sections(report: MarketReport, sub: str) -> list[str]:
    """판정 요약 표와 차원별 문장·검증 과제를 만든다."""
    lines = [
        "",
        f"{sub} 차원별 판정 요약",
        "",
        "| 차원 | 판정 | 인용 근거 | 확인되지 않은 이유 |",
        "|---|---|---|---|",
    ]
    for d in report.dimensions:
        cited = dict.fromkeys(i for c in d.claims for i in c.citation_ids)
        refs = ", ".join(citation(i) for i in cited) or "-"
        lines.append(
            f"| {DIMENSION_LABELS[d.dimension]} | {VERDICT_LABELS[d.verdict]} | {refs}"
            f" | {cell(d.limitation) or '-'} |"
        )

    for d in report.dimensions:
        lines += [
            "",
            f"{sub} {DIMENSION_LABELS[d.dimension]}: {VERDICT_LABELS[d.verdict]}",
            "",
        ]
        if not d.claims:
            lines.append("- 근거로 쓸 수 있는 문장이 없다.")
        for c in d.claims:
            refs = " ".join(f"[{citation(i)}]" for i in c.citation_ids)
            lines.append(
                f"- [{CLAIM_LABELS[c.claim_type]}] {cell(c.statement)}"
                + (f" {refs}" if refs else "")
            )
        if d.limitation:
            lines.append(f"- 확인되지 않은 이유: {cell(d.limitation)}")
        if d.next_check:
            lines.append(f"- 다음 검증 과제: {cell(d.next_check)}")
    return lines
