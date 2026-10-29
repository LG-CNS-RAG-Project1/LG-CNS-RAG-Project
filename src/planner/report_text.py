"""같은 의미 결과(SemanticResult)를 도표 없이 텍스트 보고서(Markdown)로 쓴다.

화면 도표와 같은 근거·판정·다음 질문을 담아, 텍스트 보고서와 시각화 보고서의 기획 과업 효용을
같은 근거 조건에서 비교 평가할 수 있게 한다. LLM을 부르지 않는다.
"""

from src.planner.matrix import STATUS_LABELS, UNKNOWN_LABELS
from src.planner.pricing import NOT_EVIDENCE
from src.planner.relations import relation_label
from src.planner.schemas import SemanticResult

ASSUMPTION_LABELS = {
    "counter_evidence": "반대 근거 있음",
    "supporting_evidence": "지지 근거 있음",
    "mixed": "지지·반대 근거 모두 있음",
    "no_evidence": "근거 미확인",
    "needs_company_input": "회사 입력 필요",
    "needs_customer_validation": "고객 확인 필요",
}
STOP_LABELS = {
    "answer_requirements_met": "증거 요건 충족",
    "budget_exhausted": "수집 예산 소진",
    "no_new_evidence_within_capped_search": "제한된 추가 검색에서 새 근거 없음",
    "requires_company_input": "회사 입력 필요",
    "requires_customer_validation": "고객 확인 필요",
    "slot_unfilled": "질의에 넣을 확인된 기업·관계 없음",
}
QUESTION_LABELS = {
    "answer_requirements_met": "증거 요건 충족",
    "gap": "근거 공백",
    "requires_company_input": "회사 입력 필요",
    "requires_customer_validation": "고객 확인 필요",
    "not_automated": "판정 규칙 미구현",
}


def semantic_to_markdown(result: SemanticResult, title: str = "") -> str:
    sources = {s["source_id"]: s for s in result.sources}
    evidence = {e.evidence_id: e for e in result.evidence}
    questions = {q.question_id: q for q in result.questions}
    lines = [f"# 사업기획 근거 보고서{(' · ' + title) if title else ''}", ""]
    c = result.counts
    lines += [
        f"- 자료 범위: 채택 기사 {c['retained_articles']}건 · 전재 묶음 {c['dup_groups']}개 · "
        f"검색 요청 {c['requests_used']}회 · 후보 {c['candidates_seen']}건",
        f"- 본문 상태: {c['body_status']} · 추출 상태: {c['extraction_status']}",
        f"- 규칙 {result.versions.get('rule_version', '')} · "
        f"추출기 {result.versions.get('extractor_version', '')}",
        "- 구절 존재 확인은 의미 검증과 다르며, 공급사 주장은 독립 검증된 성능이 아닙니다.",
        "",
        "## 경쟁 주장 비교",
        "",
    ]
    rows = {r.row_id: r for r in result.rows}
    for criterion in result.criteria:
        lines.append(f"### {criterion['label']}")
        for cell in result.cells:
            if cell.criterion_id != criterion["id"]:
                continue
            row = rows[cell.row_id]
            reason = UNKNOWN_LABELS.get(cell.unknown_reason, cell.unknown_reason)
            status = STATUS_LABELS[cell.status] + (f" — {reason}" if reason else "")
            lines.append(
                f"- **{row.label}**: {status} (다음 질문 {cell.next_question_id})"
            )
            for eid in cell.evidence_ids[:3]:
                item = evidence[eid]
                src = sources.get(item.source_id, {})
                lines.append(
                    f"  - \"{item.span.text}\" — {src.get('publisher', '')} "
                    f"{src.get('published_at', '')[:10]} {src.get('url', '')}"
                )
        lines.append("")
    if result.insights:
        lines += ["## 비교 해석(규칙 템플릿)", ""]
        for insight in result.insights:
            lines.append(
                f"- {insight.text} 다음 질문: {', '.join(insight.next_question_ids)}. "
                f"한계: {insight.limits}"
            )
        lines.append("")
    lines += ["## 공급 관계", ""]
    counts = result.relation_counts
    lines.append(
        f"- 외부 공급·계약 보도 {counts.get('external_transaction_reports', 0)}건"
        f"(계열 적용 {counts.get('affiliate_excluded', 0)}건 제외, 유상 여부 미확인) · "
        f"장비사·SI 경로 {counts.get('channel_relations', 0)}건 · "
        f"계획·실증 {counts.get('plan_or_poc_only', 0)}건"
    )
    nodes = {n.node_id: n.label for n in result.nodes}
    for edge in result.edges:
        if edge.status != "approved":
            continue
        lines.append(
            f"- {nodes.get(edge.supplier_id, edge.supplier_id)} → "
            f"{nodes.get(edge.counterpart_id, edge.counterpart_id)}: "
            f"{relation_label(edge.relation_type)}"
            + (" · 계열 적용" if edge.affiliate else "")
            + f" (기사 {len(edge.source_ids)}건)"
        )
    lines += ["", "## 사업 가정과 다음 확인", ""]
    for link in result.assumptions:
        lines.append(
            f"- **{link.label}** ({ASSUMPTION_LABELS[link.status]}): {link.statement} → "
            f"영향받는 선택: {link.affected_choice}. {link.note}"
        )
        for qid in link.next_question_ids:
            q = questions.get(qid)
            if q:
                lines.append(
                    f"  - {qid} {q.question} — {QUESTION_LABELS[q.status]}"
                    + (
                        f" · 중단 사유 {STOP_LABELS.get(q.stop_reason, q.stop_reason)}"
                        if q.stop_reason
                        else ""
                    )
                    + (f" · 질의 예: {q.queries[0]}" if q.queries else "")
                )
    lines += ["", "## 가격 조건", ""]
    price = result.price
    if price is None or price.status in {"withheld", "invalid"}:
        missing = ", ".join(price.missing) if price else "전체"
        lines.append(f"- 계산 보류: 입력 필요 {missing}")
    else:
        lines.append(
            f"- 공급자 하한 {price.floor_display}만원 · 고객 회수 상한 {price.ceiling_display}만원 "
            f"· 상태 {price.status}"
        )
    lines.append(f"- {NOT_EVIDENCE}")
    lines += ["", "## 후속 도표의 데이터 요건", ""]
    for chart in result.followup_charts:
        state = "표시 가능" if chart.available else "표시 불가"
        lines.append(f"- {chart.label}: {state}")
        for item in chart.missing:
            lines.append(f"  - 누락: {item}")
        for item in chart.how_to_obtain:
            lines.append(f"  - 확보 방법: {item}")
    return "\n".join(line.replace("\r", " ") for line in lines) + "\n"
