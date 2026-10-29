"""사업 가정 → 지지·반대 근거 → 영향받는 선택 → 다음 질문을 코드로 연결한다.

- 가정 진술은 아이디어 입력값을 그대로 쓴다(user_input). 뉴스는 반대·지지 신호만 제공한다.
- 질문 은행의 질문마다 증거 요건 충족 여부를 코드 검사로 판정한다. 회사 내부 조건·지불의사는
  뉴스 재검색 대신 회사 입력·고객 확인으로 넘긴다.
- 다음 질문 정렬: 결정 연결 가정의 상충·반대 → 근거 공백 → 기타, 그다음 답변 가능성, 질의 가능 여부, 질문 순서.
"""

import itertools

from src.planner.config import Profile, QuestionBank, template_slots
from src.planner.relations import is_external_transaction
from src.planner.schemas import AssumptionLink, Edge, Evidence, QuestionPick

ANSWERABILITY_RANK = {"partial": 0, "conditional": 1, "mixed": 2, "user_input": 3}
EVENT_WORDS = {
    "supply": "공급",
    "contract": "계약",
    "install": "구축",
    "operation": "운영",
    "repeat": "추가 발주",
    "poc": "실증",
    "plan": "협약",
    "joint_dev": "공동 개발",
    "withdrawal": "철수",
}


def _status(support: list, counter: list) -> str:
    if support and counter:
        return "mixed"
    if counter:
        return "counter_evidence"
    if support:
        return "supporting_evidence"
    return "no_evidence"


def build_assumptions(
    profile: Profile,
    idea,
    matrix: dict,
    edges: list[Edge],
    evidence: list[Evidence],
    price,
) -> list[AssumptionLink]:
    cells = matrix["cells"]
    ours = {c.criterion_id: c.status for c in cells if c.row_id == "our"}
    supplier_cells = [c for c in cells if c.row_id != "our"]
    approved_claims = [
        e for e in evidence if e.kind == "claim" and e.review_status == "approved"
    ]
    approved_edges = [e for e in edges if e.status == "approved"]
    adverse = [
        e.evidence_id
        for e in evidence
        if e.kind == "adverse" and e.review_status == "approved"
    ]
    links = []
    for template in profile.assumptions:
        statement = getattr(idea, template.source_field, "") or "(입력 없음)"
        origin = (idea.field_sources or {}).get(template.source_field, "user_input")
        support, counter, note = [], [], ""
        status = None
        if template.evidence == "our_claim_competition":
            claimed = [cid for cid, s in ours.items() if s == "explicit"]
            strong = [
                c
                for c in supplier_cells
                if c.criterion_id in claimed and c.status in {"explicit", "conflicting"}
            ]
            counter = sorted({i for c in strong for i in c.evidence_ids})
            suppliers = len({c.row_id.split("|")[0] for c in strong})
            note = (
                f"같은 기준 대응을 주장하는 공급사 {suppliers}곳. 뉴스로 당사 독자성이나 "
                "성능 우위를 확인할 수는 없습니다."
                if counter
                else "자료집에서 같은 기준의 경쟁 주장을 찾지 못했습니다(독자성 근거 아님)."
            )
        elif template.evidence == "criterion_claims":
            counter = sorted(
                {
                    i
                    for c in supplier_cells
                    if c.criterion_id == template.criterion_id
                    and c.status in {"explicit", "conflicting"}
                    for i in c.evidence_ids
                }
            )
            support = sorted(
                e.evidence_id
                for e in approved_claims
                if any(term in e.span.text for term in template.support_terms)
            )
            note = (
                "현장 맞춤 구성을 내세우는 공급 사례는 공급 범위·원가에 현장 작업이 포함될 수 "
                "있음을 뜻합니다. 당사 현장 엔지니어링 역량은 회사 입력이 필요합니다."
            )
        elif template.evidence == "channel_edges":
            support = sorted(
                i
                for e in approved_edges
                if is_external_transaction(e)
                for i in e.evidence_ids
            )
            counter = sorted(
                i
                for e in approved_edges
                if e.counterpart_kind == "channel"
                for i in e.evidence_ids
            )
            note = (
                "장비사·SI 경유 공급 보도는 경로 대안을 비교할 이유입니다. 당사 제휴 가능성·"
                "수익 배분은 확인되지 않았습니다."
            )
        elif template.evidence == "external_adoption":
            support = sorted(
                i
                for e in approved_edges
                if is_external_transaction(e)
                for i in e.evidence_ids
            )
            counter = sorted(
                adverse
                + [
                    i
                    for e in approved_edges
                    if e.relation_type == "withdrawal"
                    for i in e.evidence_ids
                ]
            )
            affiliate = sum(1 for e in approved_edges if e.affiliate)
            plan = sum(1 for e in approved_edges if e.relation_type in {"plan", "poc"})
            note = (
                f"외부 거래 보도는 유상 여부·지속 운영을 확인하지 않습니다. 계열 적용 {affiliate}건과 "
                f"계획·실증 {plan}건은 외부 수요 근거에서 뺐습니다."
            )
        elif template.evidence == "price_inputs":
            if price is None or price.status in {"withheld", "invalid"}:
                status = "needs_company_input"
                note = "직접비·이익률·고객 효과·초기비용·회수기간 입력이 필요합니다."
            elif price.status == "overlap":
                status = "supporting_evidence"
                note = "입력 가정에서 가격 구간이 성립합니다. 지불의사·판매량 근거는 아닙니다."
            else:
                status = "counter_evidence"
                note = "입력 가정에서 공급자 하한이 고객 회수 상한보다 큽니다."
        links.append(
            AssumptionLink(
                assumption_id=template.id,
                label=template.label,
                statement=statement,
                statement_kind="user_input",
                status=status or _status(support, counter),
                supporting_ids=support,
                counter_ids=counter,
                note=note
                + (" 입력값이 AI 가설입니다." if origin == "ai_hypothesis" else ""),
                affected_choice=template.affected_choice,
                options=list(template.options),
                next_question_ids=list(template.next_questions),
            )
        )
    return links


def _checks(matrix, edges, evidence, entities) -> dict:
    """질문별 증거 요건 검사. (충족 여부, 누락 항목)."""
    approved_edges = [e for e in edges if e.status == "approved"]
    external = [e for e in approved_edges if is_external_transaction(e)]
    metrics = [
        e for e in evidence if e.kind == "metric" and e.review_status == "approved"
    ]
    cells = matrix["cells"]
    ours = [
        c.criterion_id for c in cells if c.row_id == "our" and c.status == "explicit"
    ]

    def claimed_ok():
        missing = [
            cid
            for cid in ours
            if not any(
                c.criterion_id == cid
                and c.row_id != "our"
                and c.status in {"explicit", "conflicting"}
                for c in cells
            )
        ]
        return not missing, missing or []

    def metric_feature(prefix):
        return [e for e in metrics if any(m.startswith(prefix) for m in e.markers)]

    return {
        "approved_suppliers": lambda: (
            any(e.approved for e in entities.values()),
            ["supplier"],
        ),
        "our_claim_competitor_claims": claimed_ok,
        "metric_with_conditions": lambda: (
            bool(metric_feature("conditions_stated")),
            ["metric_conditions"],
        ),
        "approved_edges": lambda: (bool(approved_edges), ["relationship_quote"]),
        "affiliation_resolved": lambda: (False, ["externality"]),
        "channel_edges": lambda: (
            any(e.counterpart_kind == "channel" for e in approved_edges),
            ["channel_actor_type"],
        ),
        "price_metric_with_unit": lambda: (
            bool(metric_feature("sales_unit")),
            ["sales_unit"],
        ),
        "price_scope_terms": lambda: (bool(metric_feature("price_scope")), ["scope"]),
        "adoption_edges": lambda: (bool(external), ["adoption_event"]),
        "external_transaction_stage": lambda: (
            any(
                e.relation_type in {"contract", "operation", "repeat"}
                and e.counterpart_kind == "named"
                for e in external
            ),
            ["transaction_stage"],
        ),
        "event_dates": lambda: (
            any(e.event_at for e in approved_edges),
            ["event_date"],
        ),
        "adverse_evidence": lambda: (
            any(e.kind == "adverse" and e.review_status == "approved" for e in evidence)
            or any(e.relation_type == "withdrawal" for e in approved_edges),
            ["adverse_statement"],
        ),
    }


def _names(entities, labels) -> dict[str, str]:
    """엔터티 이름 + 관계 노드 라벨(관계에만 나온 상대 이름). 익명 노드는 질의에 쓰지 않는다."""
    names = {k: v for k, v in (labels or {}).items() if not k.startswith("anon-")}
    names.update({e.entity_id: e.name for e in entities.values()})
    return names


def _slot_values(slot, question_id, profile, edges, entities, labels=None) -> list[str]:
    approved = sorted(e.name for e in entities.values() if e.approved)
    approved_edges = [e for e in edges if e.status == "approved"]
    names = _names(entities, labels)
    if slot == "supplier":
        if question_id in {"G2", "D4"}:
            ids = sorted(
                {e.supplier_id for e in approved_edges if is_external_transaction(e)}
            )
            return [names[i] for i in ids if i in names]
        if question_id in {"G1", "M2"}:
            with_edges = {e.supplier_id for e in approved_edges}
            return [
                n for n in approved if entities_by_name(entities, n) not in with_edges
            ]
        return approved
    if slot in {"adopter", "actor"}:
        if slot == "actor":
            ids = sorted({e.supplier_id for e in approved_edges if not e.event_at})
            return [names[i] for i in ids if i in names]
        ids = sorted(
            {
                e.counterpart_id
                for e in approved_edges
                if is_external_transaction(e) and e.counterpart_kind == "named"
            }
        )
        return [names.get(i, "") for i in ids if names.get(i)]
    if slot == "event":
        return sorted(
            {EVENT_WORDS.get(e.relation_type, "공급") for e in approved_edges}
        )
    if slot == "channel_actor":
        ids = sorted(
            {
                e.counterpart_id
                for e in approved_edges
                if e.counterpart_kind == "channel"
            }
        )
        return [names[i] for i in ids if i in names]
    return list(profile.slots.get(slot, []))


def _pair_queries(template, slots, profile, edges, entities, labels=None) -> list[str]:
    """공급사·고객 슬롯은 실제 관계 간선의 쌍으로만 채운다(교차 조합 금지)."""
    names = _names(entities, labels)
    pairs = sorted(
        {
            (names[e.supplier_id], names[e.counterpart_id])
            for e in edges
            if is_external_transaction(e)
            and e.counterpart_kind == "named"
            and e.supplier_id in names
            and e.counterpart_id in names
        }
    )
    queries = []
    for supplier, adopter in pairs:
        query = template.replace("{supplier}", supplier).replace("{adopter}", adopter)
        for slot in slots:
            if slot not in {"supplier", "adopter"}:
                values = profile.slots.get(slot, [])
                if not values:
                    return []
                query = query.replace("{" + slot + "}", values[0])
        queries.append(" ".join(query.split()))
        if len(queries) >= profile.budget.queries_per_question:
            break
    return queries


def entities_by_name(entities, name):
    return next((e.entity_id for e in entities.values() if e.name == name), "")


def build_queries(question, profile, edges, entities, labels=None) -> list[str]:
    """질문 템플릿 슬롯을 채운 질의. 채울 값이 없는 슬롯이 있으면 빈 목록."""
    template = question.query_template
    slots = sorted(template_slots(template))
    if not template:
        return []
    if {"supplier", "adopter"} <= set(slots):
        return _pair_queries(template, slots, profile, edges, entities, labels)
    values = []
    for slot in slots:
        options = [
            v
            for v in _slot_values(slot, question.id, profile, edges, entities, labels)
            if v
        ]
        if not options:
            return []
        values.append(options)
    queries = []
    for combo in itertools.product(*values):
        query = template
        for slot, value in zip(slots, combo):
            query = query.replace("{" + slot + "}", value)
        query = " ".join(query.split())
        if query not in queries:
            queries.append(query)
        if len(queries) >= profile.budget.queries_per_question:
            break
    return queries


def evaluate_questions(
    bank: QuestionBank,
    profile: Profile,
    matrix: dict,
    edges: list[Edge],
    evidence: list[Evidence],
    entities: dict,
    assumptions: list[AssumptionLink],
    stop_reasons: dict[str, str] | None = None,
    labels: dict[str, str] | None = None,
) -> list[QuestionPick]:
    """질문 은행 전체의 상태·우선순위·후속 질의를 만든다. stop_reasons는 수집 기록에서 온다."""
    checks = _checks(matrix, edges, evidence, entities)
    stop_reasons = stop_reasons or {}
    linked: dict[str, list[AssumptionLink]] = {}
    for link in assumptions:
        for qid in link.next_question_ids:
            linked.setdefault(qid, []).append(link)
    conflict_questions = {
        c.next_question_id for c in matrix["cells"] if c.status == "conflicting"
    }
    picks = []
    for index, question in enumerate(bank.questions):
        missing, queries = [], []
        if question.id in profile.question_checks:
            met, missing = checks[profile.question_checks[question.id]]()
            status = "answer_requirements_met" if met else "gap"
            if met:
                missing = []
        elif question.id in profile.company_input:
            status = "requires_company_input"
        elif question.id in profile.customer_validation:
            status = "requires_customer_validation"
        else:
            status = "not_automated"
        if status == "gap":
            queries = build_queries(question, profile, edges, entities, labels)
        links = linked.get(question.id, [])
        if question.id in conflict_questions or any(
            link.status in {"counter_evidence", "mixed"} for link in links
        ):
            first = 0
        elif any(link.status == "no_evidence" for link in links):
            first = 1
        else:
            first = 2
        priority = [
            first,
            ANSWERABILITY_RANK[question.news_answerability],
            0 if queries else 1,
            index,
        ]
        stop = {
            "answer_requirements_met": "answer_requirements_met",
            "requires_company_input": "requires_company_input",
            "requires_customer_validation": "requires_customer_validation",
        }.get(status, "")
        if status == "gap":
            stop = stop_reasons.get(question.id) or ("" if queries else "slot_unfilled")
        picks.append(
            QuestionPick(
                question_id=question.id,
                question=question.question,
                decision=question.decision,
                status=status,
                priority=priority,
                missing=missing,
                queries=queries,
                stop_reason=stop,
                linked_assumptions=[link.assumption_id for link in links],
            )
        )
    return picks


def select_followups(picks: list[QuestionPick], exhausted: set[str], limit: int = 3):
    """후속 라운드 대상: 질의가 있는 gap 질문을 우선순위대로 limit개."""
    candidates = [
        p
        for p in picks
        if p.status == "gap" and p.queries and p.question_id not in exhausted
    ]
    return sorted(candidates, key=lambda p: p.priority)[:limit]
