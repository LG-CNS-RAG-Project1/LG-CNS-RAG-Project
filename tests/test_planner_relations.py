"""공급 관계·가정 연결·다음 질문: 동시 언급 무간선, 계열 제외, 익명 비병합, 질문 판정·정렬."""

from src.planner.assumptions import (
    build_assumptions,
    evaluate_questions,
    select_followups,
)
from src.planner.availability import check_followup_charts
from src.planner.config import load_question_bank
from src.planner.matrix import build_matrix
from src.planner.pricing import compute_price
from src.planner.relations import build_relations
from src.planner.rules import entity_id
from tests.planner_fixtures import IDEA, WORLD, processed, source_id


def analyzed(world=WORLD, price=None):
    result = processed(world)
    anchors = {a.anchor_id: a for a in result["anchors"]}
    relations = build_relations(
        result["evidence"], result["entities"], anchors, result["articles_by_id"]
    )
    table = build_matrix(
        result["evidence"],
        result["entities"],
        result["approved_in"],
        IDEA,
        result["profile"],
        result["articles_by_id"],
    )
    links = build_assumptions(
        result["profile"], IDEA, table, relations["edges"], result["evidence"], price
    )
    picks = evaluate_questions(
        load_question_bank(),
        result["profile"],
        table,
        relations["edges"],
        result["evidence"],
        result["entities"],
        links,
    )
    return result, relations, links, {p.question_id: p for p in picks}


def edge(relations, supplier, relation_type):
    return next(
        e
        for e in relations["edges"]
        if e.supplier_id == entity_id(supplier) and e.relation_type == relation_type
    )


def test_relations_are_typed_directed_and_only_from_relation_verbs():
    _, relations, _, _ = analyzed()
    approved = [e for e in relations["edges"] if e.status == "approved"]
    assert {(e.relation_type, e.counterpart_kind) for e in approved} >= {
        ("supply", "anonymous"),
        ("supply", "channel"),
        ("install", "named"),
        ("contract", "named"),
        ("plan", "named"),
    }
    assert relations["counts"]["co_mentions_without_relation"] == 1
    assert not any(
        e.counterpart_id == entity_id("마바솔루션") for e in relations["edges"]
    )
    reverse = edge(relations, "가나비전", "install")
    assert reverse.counterpart_id == entity_id("사바전자")
    assert "supplier_approved_in_other_article" in reverse.reasons


def test_affiliate_plan_and_channel_relations_are_not_external_transactions():
    _, relations, _, _ = analyzed()
    counts = relations["counts"]
    assert counts["external_transaction_reports"] == 3
    assert counts["named_external_adopters"] == 2
    assert counts["anonymous_cases"] == 1
    assert counts["affiliate_excluded"] == 1
    assert counts["plan_or_poc_only"] == 1
    assert counts["channel_relations"] == 1
    assert edge(relations, "자차로봇", "install").affiliate


def test_anonymous_adopters_are_never_merged_across_articles():
    world = [dict(a) for a in WORLD]
    copy = dict(next(a for a in world if a["key"] == "A1"))
    copy.update(
        key="A1B",
        url="https://news.example.com/a1b",
        title="가나비전, 다른 공장에 검사 장비 공급 확대",
    )
    world.append(copy)
    _, relations, _, _ = analyzed(world)
    anonymous = [n for n in relations["nodes"] if n.kind == "anonymous_adopter"]
    assert len(anonymous) == 2
    assert relations["counts"]["anonymous_cases"] == 2


def test_assumptions_link_evidence_to_choices_and_next_questions():
    _, _, links, _ = analyzed()
    by_id = {link.assumption_id: link for link in links}
    assert by_id["A1"].status == "counter_evidence" and by_id["A1"].counter_ids
    assert by_id["A1"].statement == IDEA.difference
    assert by_id["A2"].status == "counter_evidence"
    assert by_id["A3"].status == "mixed"
    assert by_id["A4"].status == "mixed"
    assert by_id["A5"].status == "needs_company_input"
    assert by_id["A3"].next_question_ids == ["G3", "G4"]
    assert "외부 수요 근거에서 뺐습니다" in by_id["A4"].note

    _, _, links, _ = analyzed(price=compute_price({}, mode="example"))
    assert {l.assumption_id: l.status for l in links}["A5"] == "supporting_evidence"


def test_question_checks_route_company_and_customer_questions():
    _, _, _, picks = analyzed()
    assert picks["C1"].status == "answer_requirements_met"
    assert picks["C2"].status == "answer_requirements_met"
    assert picks["G3"].status == "answer_requirements_met"
    assert picks["E1"].status == "answer_requirements_met"
    assert picks["D4"].status == "answer_requirements_met"
    assert picks["R1"].status == "answer_requirements_met"
    assert picks["C3"].status == "gap" and picks["C3"].missing == ["metric_conditions"]
    assert picks["M4"].status == "requires_company_input"
    assert picks["G4"].stop_reason == "requires_company_input"
    assert picks["C4"].status == "requires_customer_validation"
    assert picks["A1"].status == "not_automated"


def test_followup_queries_use_real_pairs_and_stable_priority():
    _, _, _, picks = analyzed()
    assert picks["G2"].queries == [
        "가나비전 사바전자 외부 고객 계약",
        "카타비전 타파전자 외부 고객 계약",
    ]
    assert picks["C3"].queries == ["AI 비전검사 검출률 오검출 측정 조건"]
    chosen = select_followups(list(picks.values()), exhausted=set())
    assert [p.question_id for p in chosen] == ["C3", "G2", "E2"]
    assert [p.question_id for p in select_followups(list(picks.values()), {"C3"})][
        0
    ] == "G2"


def test_followup_charts_report_missing_data_instead_of_drawing():
    result, relations, _, _ = analyzed()
    charts = {
        c.chart_id: c
        for c in check_followup_charts(relations["edges"], result["evidence"])
    }
    assert (
        not charts["case_timeline"].available and charts["case_timeline"].how_to_obtain
    )
    assert not charts["price_dotplot"].available
    assert "D4" in charts["case_timeline"].question_ids
    assert not charts["segment_candidates"].available
    assert source_id("A5")
