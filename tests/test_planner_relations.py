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


def test_price_dotplot_requires_reviewed_comparable_prices():
    from src.planner.schemas import Evidence, Span

    def price(n, reasons):
        span = Span(
            source_id=f"s{n}",
            sentence_id="s1",
            layer="stored_snippet",
            start=0,
            end=3,
            text="1억원",
        )
        return Evidence(
            evidence_id=f"ev{n}",
            anchor_id=f"a{n}",
            source_id=f"s{n}",
            kind="metric",
            span=span,
            evidence_layer="stored_snippet",
            statement_kind="reported_event",
            review_status="approved",
            reasons=reasons,
            markers=["price", "sales_unit:대당", "price_scope"],
        )

    rule_only = check_followup_charts([], [price(1, []), price(2, [])])
    assert not {c.chart_id: c for c in rule_only}["price_dotplot"].available
    reviewed = check_followup_charts(
        [], [price(1, ["reviewer_approved"]), price(2, ["reviewer_approved"])]
    )
    assert {c.chart_id: c for c in reviewed}["price_dotplot"].available


def _mini(key, title, snippet, mentions, relation):
    from tests.planner_fixtures import article

    subject, obj, clause = relation
    return article(
        key,
        title,
        snippet,
        candidates={
            "mentions": mentions,
            "relations": [
                {
                    "exact_clause": clause,
                    "subject_text": subject,
                    "object_text": obj,
                    "relation_hint": "supply",
                }
            ],
        },
    )


def test_relation_counterparts_must_be_organizations_on_topic():
    world = [
        _mini(
            "B1",
            "가상메트리, 미국향 검사장비 공급계약",
            "가상메트리는 미국향 ESS 검사장비 공급계약을 체결했다.",
            [("가상메트리", "supplier")],
            (
                "가상메트리",
                "미국향 ESS 검사장비",
                "가상메트리는 미국향 ESS 검사장비 공급계약을 체결했다",
            ),
        ),
        _mini(
            "B2",
            "가상코, 비전 검사장비 사업 확대",
            "가상코가 세라믹 원재료를 공급하면 가상코세라믹스가 부품으로 만든다.",
            [("가상코", "supplier"), ("가상코세라믹스", "adopter")],
            (
                "가상코",
                "가상코세라믹스",
                "가상코가 세라믹 원재료를 공급하면 가상코세라믹스가 부품으로 만든다",
            ),
        ),
        _mini(
            "B3",
            "가상미코, 계열사에 AI 검사 장비 공급",
            "가상미코는 가상미코테크에 AI 검사 장비를 공급했다.",
            [("가상미코", "supplier"), ("가상미코테크", "adopter")],
            (
                "가상미코",
                "가상미코테크",
                "가상미코는 가상미코테크에 AI 검사 장비를 공급했다",
            ),
        ),
        _mini(
            "B4",
            "가상세이지, 배터리 3사에 비전검사 솔루션 공급",
            "가상세이지는 가상SDI · 가상엔솔 · 가상온 등에 비전검사 솔루션을 공급하고 있다.",
            [("가상세이지", "supplier"), ("가상SDI · 가상엔솔 · 가상온", "adopter")],
            (
                "가상세이지",
                "가상SDI · 가상엔솔 · 가상온",
                "가상세이지는 가상SDI · 가상엔솔 · 가상온 등에 비전검사 솔루션을 공급하고 있다",
            ),
        ),
        _mini(
            "B5",
            "가상피플, 라면 공장에 AI 검사 솔루션 적용",
            "가상피플은 지방의 한 라면 공장에 검사 솔루션을 적용하고 있다.",
            [("가상피플", "supplier")],
            (
                "가상피플",
                "라면 공장",
                "가상피플은 지방의 한 라면 공장에 검사 솔루션을 적용하고 있다",
            ),
        ),
    ]
    result, relations, _, _ = analyzed(world)
    reasons = {
        e.span.source_id: e.reasons for e in result["evidence"] if e.kind == "relation"
    }
    assert "counterpart_not_an_organization" in reasons[source_id_of(world, "B1")]
    assert "off_topic_relation" in reasons[source_id_of(world, "B2")]
    approved = [e for e in relations["edges"] if e.status == "approved"]
    overlap = next(e for e in approved if e.supplier_id == entity_id("가상미코"))
    assert "affiliate_name_overlap" in overlap.reasons
    listed = [e for e in approved if e.supplier_id == entity_id("가상세이지")]
    assert sorted(e.counterpart_id for e in listed) == sorted(
        entity_id(n) for n in ("가상SDI", "가상엔솔", "가상온")
    )
    noodle = next(e for e in approved if e.supplier_id == entity_id("가상피플"))
    assert noodle.counterpart_kind == "anonymous"
    counts = relations["counts"]
    assert counts["named_external_adopters"] == 3
    assert counts["affiliate_excluded"] == 1


def source_id_of(world, key):
    from src.ingestion.news_client import make_source_id

    return make_source_id(next(a["url"] for a in world if a["key"] == key))


def test_v3_lexical_rules():
    from src.planner.rules import is_public, mention_name, relation_type, split_parties

    assert relation_type("가상이 추진한 검사 기술의 양산 검증을 통과했다") == "poc"
    assert relation_type("가상은 내년 공급을 추진할 예정이다") == "plan"
    assert mention_name("회사")[1] == "generic_noun_mention"
    assert is_public("코트라") and not is_public("가상비전")
    assert split_parties("가상SDI · 가상엔솔 · 가상온") == [
        "가상SDI",
        "가상엔솔",
        "가상온",
    ]
