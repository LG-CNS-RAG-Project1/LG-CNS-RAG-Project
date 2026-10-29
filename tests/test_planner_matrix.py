"""경쟁 주장 비교표 규칙: 구절 위치, 역할 혼동 방지, 셀 상태·미확인 사유, 해석 템플릿."""

from src.planner.matrix import build_matrix
from src.planner.rules import (
    align,
    entity_id,
    is_anonymous,
    mention_features,
    mention_name,
    relation_type,
)
from tests.planner_fixtures import IDEA, WORLD, processed, source_id


def matrix(result=None, idea=IDEA):
    result = result or processed()
    return result, build_matrix(
        result["evidence"],
        result["entities"],
        result["approved_in"],
        idea,
        result["profile"],
        result["articles_by_id"],
    )


def cell(table, name, criterion, product=""):
    row = next(
        r
        for r in table["rows"]
        if r.kind == "supplier"
        and r.supplier_id == entity_id(name)
        and r.product == product
    )
    return next(
        c
        for c in table["cells"]
        if c.row_id == row.row_id and c.criterion_id == criterion
    )


def layer_text(sid, layer):
    a = next(a for a in WORLD if source_id(a["key"]) == sid)
    if layer == "title":
        return a["title"]
    if layer == "stored_snippet":
        return a["snippet"]
    from src.planner.body import extract_article_text
    from tests.planner_fixtures import html_page

    return extract_article_text(html_page(a))


def test_every_span_is_an_exact_slice_of_its_source_layer():
    result = processed()
    assert result["evidence"]
    for item in result["evidence"]:
        span = item.span
        assert (
            layer_text(span.source_id, span.layer)[span.start : span.end] == span.text
        )


def test_supplier_approval_blocks_adopters_public_and_channel_roles():
    result = processed()
    approved = {e.name for e in result["entities"].values() if e.approved}
    assert approved == {
        "가나비전",
        "다라테크",
        "마바솔루션",
        "자차로봇",
        "카타비전",
        "라마AI",
        "파하AI",
    }
    sabah = result["entities"][entity_id("사바전자")]
    assert not sabah.approved and "adopter_pattern" in sabah.reasons


def test_failed_extraction_and_fake_hallucination_are_recorded():
    result = processed()
    status = {e.source_id: e.status for e in result["extractions"]}
    assert status[source_id("A10")] == "failed"
    assert result["articles_by_id"][source_id("A10")]["extraction_status"] == "failed"
    assert align("가나비전은 공급했다", "가나비전이 공급했다") == []


def test_cell_status_follows_approved_evidence_only():
    _, table = matrix()
    defect = cell(table, "가나비전", "defect_data_preparation")
    assert defect.status == "conflicting"
    assert defect.supporting_source_ids == [source_id("A1")]
    assert defect.conflicting_source_ids == [source_id("A8")]

    site = cell(table, "가나비전", "site_customization")
    assert site.status == "explicit" and site.evidence_layer == "reviewed_body"

    assert cell(table, "다라테크", "changeover_reconfiguration").status == "explicit"
    title_only = cell(table, "파하AI", "changeover_reconfiguration")
    assert title_only.status == "partial" and "title_only" in title_only.reasons


def test_unknown_cells_keep_reasons_and_are_not_zero():
    _, table = matrix()
    failed = cell(table, "가나비전", "changeover_reconfiguration")
    assert failed.status == "unknown" and failed.unknown_reason == "extraction_failed"
    assert failed.article_count is None and failed.evidence_ids == []

    truncated = cell(table, "다라테크", "defect_data_preparation")
    assert truncated.unknown_reason == "snippet_truncated_body_unavailable"
    assert truncated.reasons == ["snippet_truncated_body_unavailable:http_403:1"]

    candidate = cell(table, "마바솔루션", "site_customization")
    assert candidate.unknown_reason == "candidate_not_approved"
    assert candidate.candidate_evidence_ids


def test_rows_are_company_level_when_product_is_unconfirmed_and_no_scores_exist():
    _, table = matrix()
    labels = [r.label for r in table["rows"]]
    assert labels[0] == "당사 주장"
    assert "가나비전 (회사 수준·제품 미확인)" in labels
    for item in table["cells"]:
        assert "score" not in item.model_dump()


def test_our_claim_row_reflects_idea_input_and_its_origin():
    _, table = matrix()
    ours = {c.criterion_id: c for c in table["cells"] if c.row_id == "our"}
    assert ours["defect_data_preparation"].status == "explicit"
    assert ours["site_customization"].status == "partial"
    assert ours["changeover_reconfiguration"].unknown_reason == "not_in_idea_input"

    hypothesis = IDEA.model_copy(
        update={"field_sources": {"difference": "ai_hypothesis"}}
    )
    _, table = matrix(idea=hypothesis)
    assert table["rows"][0].label == "당사 주장(AI 가설)"


def test_insights_link_competing_claims_to_next_questions():
    _, table = matrix()
    by_criterion = {i.criterion_id: i for i in table["insights"]}
    defect = by_criterion["defect_data_preparation"]
    assert "공급사 1곳" in defect.text and defect.next_question_ids == ["C4"]
    assert defect.statement_kind == "analyst_interpretation"
    assert "성능 우위" in defect.limits
    changeover = by_criterion["changeover_reconfiguration"]
    assert "차별점 입력에는" in changeover.text
    assert changeover.next_question_ids == ["C4", "C3"]


def test_different_industry_scope_turns_conflict_into_scope_note():
    world = [dict(a) for a in WORLD]
    a8 = next(a for a in world if a["key"] == "A8")
    a8["snippet"] = a8["snippet"].replace("회사는...", "이차전지 공정 기준이다...")
    _, table = matrix(processed(world))
    defect = cell(table, "가나비전", "defect_data_preparation")
    assert defect.status == "explicit" and "조건 상이" in defect.scope_note


def test_reviews_can_reject_but_not_invent_missing_suppliers():
    base = processed()
    a1_claim = next(
        e
        for e in base["evidence"]
        if e.kind == "claim"
        and e.source_id == source_id("A1")
        and "defect_data_preparation" in e.criteria
    )
    channel_claim = next(
        e
        for e in base["evidence"]
        if e.kind == "claim" and e.source_id == source_id("A3")
    )
    reviews = [
        {"evidence_id": a1_claim.evidence_id, "decision": "reject", "reason": "검토"},
        {
            "evidence_id": channel_claim.evidence_id,
            "decision": "approve",
            "reason": "x",
        },
    ]
    result, table = matrix(processed(reviews=reviews))
    defect = cell(table, "가나비전", "defect_data_preparation")
    assert defect.status == "partial" and "negated_statement_only" in defect.reasons
    reviewed = next(
        e for e in result["evidence"] if e.evidence_id == channel_claim.evidence_id
    )
    assert reviewed.review_status == "candidate"
    assert "approval_not_applicable" in reviewed.reasons


def test_lexical_helpers_for_anonymous_and_relation_types():
    assert is_anonymous("국내 이차전지 제조사") and is_anonymous("B사")
    assert not is_anonymous("타파전자") and not is_anonymous("삼성가상 공장")
    assert relation_type("공급할 예정이다") == "plan"
    assert relation_type("계약을 체결했다") == "contract"
    assert relation_type("도입했다가 철수했다") == "withdrawal"
    assert relation_type("전시회에 참가했다") == ""


def test_mention_names_are_cut_to_company_and_compounds_rejected():
    assert mention_name("가상트윔(대표 홍길동") == ("가상트윔", "")
    long = "가상바이슨은 카메라와 렌즈, 조명을 포함한 광학계 설계부터 현장 설치까지 수행한다."
    assert mention_name(long) == ("가상바이슨", "")
    assert mention_name("가상차와 가상기아")[1] == "compound_mention"
    assert mention_name("가상대학 연구진")[1] == "research_team_mention"
    assert mention_name("AI 머신비전 검사 솔루션 전문 기업 아주 긴 설명 문장")[1] == (
        "mention_not_a_name"
    )


def test_spokesperson_pattern_counts_as_supplier_evidence():
    title = "[인터뷰] 홍길동 가상인더스트리AI 대표 “셋업 시간 단축”"
    features = mention_features(
        "가상인더스트리AI", "검사 플랫폼을 소개했다.", title, ["플랫폼"]
    )
    assert "spokesperson" in features


def test_loosely_related_idea_text_gets_scope_definition_insight():
    _, table = matrix()
    site = next(i for i in table["insights"] if i.criterion_id == "site_customization")
    assert "관련된 표현만" in site.text and site.next_question_ids == ["E2", "C4"]
    assert "단독 차별점" not in site.text
