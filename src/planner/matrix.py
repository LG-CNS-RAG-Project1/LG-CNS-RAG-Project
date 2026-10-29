"""구매 기준별 경쟁 주장 비교표와 규칙 템플릿 해석을 만든다.

- 행: 맨 위 '당사 주장'(아이디어 차별점 입력) → 승인 공급사(제품이 확인되면 제품 행, 아니면 회사 수준).
- 셀 상태는 승인된 주장 근거만으로 정한다: conflicting > explicit > partial > unknown.
- unknown은 '기능 없음'이나 0이 아니며 사유(후보 미승인·추출 실패·잘린 요약 등)를 함께 남긴다.
- 경쟁력 점수·성능 순위는 만들지 않는다. 해석 문장은 고정 템플릿이며 다음 질문 ID를 붙인다.
"""

from collections import Counter

from src.planner.config import Profile
from src.planner.schemas import Evidence, Insight, MatrixCell, MatrixRow
from src.planner.store import canonical_json, sha256_hex

UNKNOWN_ORDER = [
    "candidate_not_approved",
    "extraction_failed",
    "not_extracted",
    "snippet_truncated_body_unavailable",
    "not_found_in_reviewed_text",
    "no_candidate_in_sources",
]
STATUS_LABELS = {
    "explicit": "대응 주장 명시",
    "partial": "설명 불완전",
    "unknown": "미확인",
    "conflicting": "상충",
}
STATUS_SYMBOLS = {"explicit": "●", "partial": "◐", "unknown": "○", "conflicting": "⇄"}
UNKNOWN_LABELS = {
    "candidate_not_approved": "주체 미확정 후보만 있음(검토 필요)",
    "extraction_failed": "추출 실패 기사 있음",
    "not_extracted": "추출하지 않은 기사 있음",
    "snippet_truncated_body_unavailable": "잘린 요약뿐이고 본문 미확보",
    "not_found_in_reviewed_text": "본문까지 확인했으나 해당 주장 없음(기능 부재 아님)",
    "no_candidate_in_sources": "자료집에서 대응 주장 후보를 찾지 못함(기능 부재 아님)",
    "not_in_idea_input": "아이디어 차별점 입력에 없음",
}


def _row_id(supplier_id: str, product: str) -> str:
    if not product:
        return supplier_id
    return f"{supplier_id}|{sha256_hex(canonical_json(product))[:8]}"


def _classify(item: Evidence, criterion_id: str) -> tuple[str, str]:
    """근거 1건의 기준별 성격: positive·negative(명시), partial(사유)."""
    markers = set(item.markers)
    if item.criteria.get(criterion_id) != "strong":
        return "partial", "weak_term_only"
    for marker, reason in (
        ("title_only", "title_only"),
        ("truncated", "truncated_snippet"),
        ("planned", "planned"),
    ):
        if marker in markers:
            return "partial", reason
    return ("negative" if "negated" in markers else "positive"), ""


def build_matrix(
    evidence: list[Evidence],
    entities: dict,
    approved_in: dict[str, set[str]],
    idea,
    profile: Profile,
    articles: dict[str, dict],
) -> dict:
    """비교표 행·셀·해석을 만든다. articles는 source_id → 기사 메타데이터·추출·본문 상태."""
    claims = [e for e in evidence if e.kind == "claim"]
    approved = [e for e in claims if e.review_status == "approved"]
    metrics = [
        e for e in evidence if e.kind == "metric" and e.review_status == "approved"
    ]
    origin = (idea.field_sources or {}).get("difference", "user_input")
    rows = [
        MatrixRow(
            row_id="our",
            label="당사 주장(AI 가설)" if origin == "ai_hypothesis" else "당사 주장",
            kind="our_claim",
            level="idea",
            input_origin=origin,
        )
    ]
    cells: list[MatrixCell] = []
    our_hits = {}
    for criterion in profile.criteria:
        text = idea.difference or ""
        if any(term in text for term in criterion.strong):
            our_hits[criterion.id] = "explicit"
        elif any(term in text for term in criterion.weak):
            our_hits[criterion.id] = "partial"
        status = our_hits.get(criterion.id, "unknown")
        cells.append(
            MatrixCell(
                row_id="our",
                criterion_id=criterion.id,
                status=status,
                evidence_layer="user_input",
                unknown_reason="" if status != "unknown" else "not_in_idea_input",
                decision_id=criterion.decision_id,
                next_question_id=criterion.next_question[status],
            )
        )

    supplier_rows = []
    for entity in entities.values():
        if not entity.approved:
            continue
        products = sorted(
            {e.product for e in approved if e.supplier_id == entity.entity_id}
        )
        if "" not in products:
            products.insert(0, "")
        for product in products:
            supplier_rows.append((entity, product))
    supplier_rows.sort(key=lambda r: (r[0].name, r[1]))

    for entity, product in supplier_rows:
        row_id = _row_id(entity.entity_id, product)
        rows.append(
            MatrixRow(
                row_id=row_id,
                label=(
                    f"{entity.name} · {product}"
                    if product
                    else f"{entity.name} (회사 수준·제품 미확인)"
                ),
                kind="supplier",
                supplier_id=entity.entity_id,
                product=product,
                level="product" if product else "company",
            )
        )
        row_articles = sorted(
            {sid for sid, ids in approved_in.items() if entity.entity_id in ids}
            | {
                sid
                for sid, meta in articles.items()
                if entity.entity_id in meta.get("mentioned_entity_ids", [])
            }
        )
        row_claims = [
            e
            for e in approved
            if e.supplier_id == entity.entity_id and e.product == product
        ]
        for criterion in profile.criteria:
            cells.append(
                _supplier_cell(
                    row_id, criterion, row_claims, claims, row_articles, articles
                )
            )

    insights = _insights(rows, cells, profile, idea, evidence, metrics)
    return {
        "criteria": [
            {"id": c.id, "label": c.label, "decision_id": c.decision_id}
            for c in profile.criteria
        ],
        "rows": rows,
        "cells": cells,
        "insights": insights,
    }


def _supplier_cell(row_id, criterion, row_claims, all_claims, row_articles, articles):
    relevant = [e for e in row_claims if criterion.id in e.criteria]
    groups = {"positive": [], "negative": [], "partial": []}
    partial_reasons = []
    for item in relevant:
        kind, reason = _classify(item, criterion.id)
        groups[kind].append(item)
        if reason:
            partial_reasons.append(reason)
    positives, negatives = groups["positive"], groups["negative"]
    scope_note, reasons = "", []
    supporting, conflicting = positives, []
    if positives and negatives:
        pos_scopes = {articles[e.source_id]["industry_scope"] for e in positives}
        neg_scopes = {articles[e.source_id]["industry_scope"] for e in negatives}
        if "unknown" not in pos_scopes | neg_scopes and not pos_scopes & neg_scopes:
            status, scope_note = "explicit", "조건 상이 근거(적용 산업 범위가 다름)"
        else:
            status, conflicting = "conflicting", negatives
    elif positives:
        status = "explicit"
    elif negatives or groups["partial"]:
        status = "partial"
        supporting = negatives + groups["partial"]
        reasons = sorted(
            set(partial_reasons + (["negated_statement_only"] if negatives else []))
        )
    else:
        status = "unknown"
    used = supporting + conflicting
    candidates = [
        e.evidence_id
        for e in all_claims
        if e.review_status == "candidate"
        and e.source_id in row_articles
        and criterion.id in e.criteria
        and not e.supplier_id
    ]
    unknown_reason = ""
    if status == "unknown":
        counts = Counter()
        if candidates:
            counts["candidate_not_approved"] = len(candidates)
        for sid in row_articles:
            meta = articles[sid]
            if meta["extraction_status"] == "failed":
                counts["extraction_failed"] += 1
            elif meta["extraction_status"].startswith("not_extracted"):
                counts["not_extracted"] += 1
        bodies = [articles[sid]["body_status"] for sid in row_articles]
        if row_articles and all(
            b != "ok" and articles[sid]["snippet_truncated"]
            for sid, b in zip(row_articles, bodies)
        ):
            common = Counter(bodies).most_common(1)[0][0]
            counts[f"snippet_truncated_body_unavailable:{common}"] = len(bodies)
        elif any(b == "ok" for b in bodies):
            counts["not_found_in_reviewed_text"] = sum(b == "ok" for b in bodies)
        if not counts:
            counts["no_candidate_in_sources"] = len(row_articles)
        reasons = [f"{key}:{value}" for key, value in counts.items()]
        reasons.sort(key=lambda r: UNKNOWN_ORDER.index(r.split(":")[0]))
        unknown_reason = reasons[0].split(":")[0]
    layers = {e.evidence_layer for e in used}
    return MatrixCell(
        row_id=row_id,
        criterion_id=criterion.id,
        status=status,
        evidence_layer=(
            "reviewed_body"
            if "reviewed_body" in layers
            else ("stored_snippet" if layers else "")
        ),
        evidence_ids=sorted(e.evidence_id for e in used),
        supporting_source_ids=sorted({e.source_id for e in supporting}),
        conflicting_source_ids=sorted({e.source_id for e in conflicting}),
        candidate_evidence_ids=sorted(candidates),
        reasons=reasons,
        unknown_reason=unknown_reason,
        scope_note=scope_note,
        article_count=len({e.source_id for e in used}) if used else None,
        dup_group_count=(
            len({articles[e.source_id]["dup_group"] for e in used}) if used else None
        ),
        decision_id=criterion.decision_id,
        next_question_id=criterion.next_question[status],
    )


def _insights(rows, cells, profile, idea, evidence, metrics) -> list[Insight]:
    """규칙 템플릿 해석. 근거 조건이 충족될 때만 만들고 점수·우열 판정은 하지 않는다."""
    by_key = {(c.row_id, c.criterion_id): c for c in cells}
    suppliers = {r.row_id: r.supplier_id for r in rows if r.kind == "supplier"}
    claim = (idea.difference or "").strip()
    insights = []
    for criterion in profile.criteria:
        ours = by_key[("our", criterion.id)].status
        strong_cells = [
            by_key[(row_id, criterion.id)]
            for row_id in suppliers
            if by_key[(row_id, criterion.id)].status in {"explicit", "conflicting"}
        ]
        partial_cells = [
            by_key[(row_id, criterion.id)]
            for row_id in suppliers
            if by_key[(row_id, criterion.id)].status == "partial"
        ]
        companies = sorted({suppliers[c.row_id] for c in strong_cells})
        ids = sorted({i for c in strong_cells for i in c.evidence_ids})
        sources = {e.source_id: e.dup_group for e in evidence if e.evidence_id in ids}
        n, m = len(sources), len(set(sources.values()))
        next_ids = ["C4"]
        if any(e.supplier_id in companies for e in metrics):
            next_ids.append("C3")
        if ours == "partial" and companies:
            insights.append(
                Insight(
                    insight_id=f"competition:{criterion.id}",
                    text=(
                        f"당사 기획안은 '{criterion.label}'와 관련된 표현만 담고 대응 방식은 밝히지 "
                        f"않았습니다. 공급사 {len(companies)}곳은 이 기준 대응을 주장합니다"
                        f"(기사 {n}건·전재 묶음 {m}개). 공급 범위와 현장 작업 책임을 먼저 정의해야 합니다."
                    ),
                    criterion_id=criterion.id,
                    evidence_ids=ids,
                    decision_id=criterion.decision_id,
                    next_question_ids=["E2", "C4"],
                    limits="공급사가 말한 주장이며 당사 차별성 판단이 아닙니다.",
                )
            )
        elif ours == "explicit" and companies:
            insights.append(
                Insight(
                    insight_id=f"competition:{criterion.id}",
                    text=(
                        f"당사 주장('{claim}')의 '{criterion.label}' 대응을 공급사 "
                        f"{len(companies)}곳도 주장합니다(기사 {n}건·전재 묶음 {m}개). "
                        "이 기능만으로 단독 차별점을 확정하기 어려울 수 있습니다. "
                        "준비·셋업·검증의 총 작업량처럼 비교 기준을 구체화해야 합니다."
                    ),
                    criterion_id=criterion.id,
                    evidence_ids=ids,
                    decision_id=criterion.decision_id,
                    next_question_ids=next_ids,
                    limits="공급사가 말한 주장이며 성능 우위·시장 점유율 비교가 아닙니다.",
                )
            )
        elif ours != "unknown":
            text = (
                f"'{criterion.label}' 관련 설명이 일부 있으나 대응 주장으로 확정하지 못했습니다."
                if partial_cells
                else f"자료집에서 '{criterion.label}' 대응 주장을 확인하지 못했습니다."
            )
            insights.append(
                Insight(
                    insight_id=f"competition:{criterion.id}",
                    text=text + " 기능 부재나 당사 독자성의 근거가 아닙니다.",
                    criterion_id=criterion.id,
                    evidence_ids=sorted(
                        {i for c in partial_cells for i in c.evidence_ids}
                    ),
                    decision_id=criterion.decision_id,
                    next_question_ids=["C2"],
                    limits="수집한 기사 범위 안의 결과입니다.",
                )
            )
        elif companies:
            insights.append(
                Insight(
                    insight_id=f"competition:{criterion.id}",
                    text=(
                        f"공급사 {len(companies)}곳이 '{criterion.label}' 대응을 내세웁니다. "
                        "당사 기획안의 차별점 입력에는 이 기준 설명이 없습니다. "
                        "가치 제안에 포함할지 검토가 필요합니다."
                    ),
                    criterion_id=criterion.id,
                    evidence_ids=ids,
                    decision_id=criterion.decision_id,
                    next_question_ids=next_ids,
                    limits="공급사가 말한 주장이며 고객의 구매 기준임을 확인한 것은 아닙니다.",
                )
            )
    return insights
