"""저장된 자료집 입력으로 의미 결과(SemanticResult)를 결정적으로 계산한다.

입력: 아이디어, 기사 메타데이터, Anchor, 수집 기록, 검토·사용자 입력(revision), 버전.
외부 검색·HTTP·LLM을 부르지 않으며 원문 본문도 읽지 않는다. 같은 입력이면 같은 결과·해시가 나온다.
"""

from collections import Counter

from src.planner.assumptions import build_assumptions, evaluate_questions
from src.planner.availability import check_followup_charts
from src.planner.config import Profile, QuestionBank
from src.planner.matrix import build_matrix
from src.planner.pricing import compute_price
from src.planner.relations import build_relations
from src.planner.rules import evaluate_evidence
from src.planner.schemas import Anchor, SemanticResult

SOURCE_FIELDS = (
    "source_id",
    "url",
    "title",
    "publisher",
    "published_at",
    "collected_at",
    "dup_group",
    "body_status",
    "industry_scope",
    "extraction_status",
    "question_id",
    "round",
)


def price_from_revision(revision: dict):
    """revision의 사용자 가격 입력으로 실제 모드 계산. 입력이 없으면 계산 보류 결과."""
    price = (revision.get("user_inputs") or {}).get("price") or {}
    return compute_price(
        price.get("values", {}), mode="actual", provenance=price.get("provenance", {})
    )


def analyze(
    idea,
    idea_digest: str,
    area_id: str,
    profile: Profile,
    bank: QuestionBank,
    articles: list[dict],
    anchors: list[Anchor],
    collection: dict,
    revision: dict,
    versions: dict,
) -> SemanticResult:
    by_id = {a["source_id"]: a for a in articles}
    evidence, entities, approved_in = evaluate_evidence(
        anchors, revision.get("reviews", [])
    )
    evidence = [
        e.model_copy(
            update={
                "dup_group": by_id[e.source_id]["dup_group"],
                "published_at": by_id[e.source_id]["published_at"],
                "industry_scope": by_id[e.source_id]["industry_scope"],
            }
        )
        for e in evidence
    ]
    table = build_matrix(evidence, entities, approved_in, idea, profile, by_id)
    relations = build_relations(
        evidence, entities, {a.anchor_id: a for a in anchors}, by_id
    )
    price = price_from_revision(revision)
    links = build_assumptions(profile, idea, table, relations["edges"], evidence, price)
    questions = evaluate_questions(
        bank,
        profile,
        table,
        relations["edges"],
        evidence,
        entities,
        links,
        stop_reasons=(collection.get("followups") or {}).get("stop_reasons", {}),
    )
    counts = {
        "requests_used": collection.get("requests_used", 0),
        "candidates_seen": collection.get("candidates_seen", 0),
        "retained_articles": len(articles),
        "dup_groups": len({a["dup_group"] for a in articles}),
        "excluded_by_reason": dict(
            sorted(collection.get("excluded_by_reason", {}).items())
        ),
        "shortfalls": collection.get("shortfalls", []),
        "collection_stops": collection.get("stops", []),
        "body_status": dict(
            sorted(Counter(a["body_status"] for a in articles).items())
        ),
        "extraction_status": dict(
            sorted(Counter(a["extraction_status"] for a in articles).items())
        ),
        "span_not_found": collection.get("span_not_found", 0),
        "approved_suppliers": sum(1 for e in entities.values() if e.approved),
        "evidence": dict(
            sorted(Counter(f"{e.kind}:{e.review_status}" for e in evidence).items())
        ),
        "rounds": len((collection.get("followups") or {}).get("rounds", [])),
    }
    return SemanticResult(
        idea_hash=idea_digest,
        area_id=area_id,
        versions=dict(sorted(versions.items())),
        counts=counts,
        sources=[
            {field: a.get(field) for field in SOURCE_FIELDS}
            for a in sorted(articles, key=lambda a: a["source_id"])
        ],
        entities=sorted(entities.values(), key=lambda e: e.entity_id),
        evidence=evidence,
        criteria=table["criteria"],
        rows=table["rows"],
        cells=table["cells"],
        insights=table["insights"],
        nodes=relations["nodes"],
        edges=relations["edges"],
        relation_counts=relations["counts"],
        assumptions=links,
        questions=questions,
        followup_charts=check_followup_charts(relations["edges"], evidence),
        price=price,
    )
