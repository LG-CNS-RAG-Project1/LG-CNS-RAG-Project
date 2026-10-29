"""공급사–도입 현장–장비사/SI 관계를 유형·방향이 있는 간선으로 만든다.

- 관계 동사가 있는 승인 근거만 확정 간선이 된다. 동사 없는 동시 언급은 간선을 만들지 않는다.
- 익명 도입처는 전재 묶음(dup_group)별로 따로 두고 다른 묶음과 합치지 않는다.
- 자체·계열 현장 적용, 이름이 겹치는 계열 추정 상대, 공공기관 상대는 외부 거래 보도 수에서 뺀다.
- 'A · B · C'처럼 나열된 상대는 각각의 상대로 나눈다.
- 간선 수·연결 수는 경쟁력이나 시장 지배력을 뜻하지 않는다. 금액이 없으므로 간선 두께도 쓰지 않는다.
"""

from src.planner.rules import (
    RELATION_LABELS,
    TRANSACTION_TYPES,
    entity_id,
    normalize_name,
    split_parties,
)
from src.planner.schemas import Anchor, Edge, Evidence, Node


def build_relations(
    evidence: list[Evidence], entities: dict, anchors: dict[str, Anchor], articles: dict
) -> dict:
    nodes: dict[str, Node] = {}
    grouped: dict[tuple, Edge] = {}
    anonymous: dict[tuple, str] = {}
    co_mentions = 0
    for item in sorted(
        (e for e in evidence if e.kind == "relation"), key=lambda e: e.evidence_id
    ):
        if "co_mention_no_relation_verb" in item.reasons:
            co_mentions += 1
            continue
        anchor = anchors[item.anchor_id]
        status = "approved" if item.review_status == "approved" else "candidate"
        supplier = item.supplier_id or anchor.entity_id
        if supplier == anchor.counterpart_id:
            side, text, other = "subject", anchor.entity_text, anchor.entity_id
            supplier_text = anchor.counterpart_text
        else:
            side, text, other = "object", anchor.counterpart_text, anchor.counterpart_id
            supplier_text = anchor.entity_text
        features = set(anchor.features)
        dup_group = articles[item.source_id]["dup_group"]
        supplier_name = (
            entities[supplier].name if supplier in entities else supplier_text
        )
        nodes.setdefault(
            supplier, Node(node_id=supplier, label=supplier_name, kind="supplier")
        )
        parties = (
            [(text, other)]
            if f"{side}_anonymous" in features
            else [
                (part, other if len(split_parties(text)) == 1 else entity_id(part))
                for part in split_parties(text)
            ]
        )
        for text, other in parties:
            if f"{side}_anonymous" in features:
                key = (dup_group, text)
                if key not in anonymous:
                    count = sum(1 for k in anonymous if k[0] == dup_group)
                    anonymous[key] = f"anon-{dup_group}-{count + 1}"
                counterpart_id, kind = anonymous[key], "anonymous"
                node_kind, label = "anonymous_adopter", f"{text} (익명·사건별)"
            elif f"{side}_channel" in features:
                counterpart_id, kind, node_kind, label = (
                    other,
                    "channel",
                    "channel",
                    text,
                )
            else:
                counterpart_id, kind, node_kind, label = other, "named", "adopter", text
            reasons = list(item.reasons)
            if f"{side}_public" in features:
                reasons.append("counterpart_public_or_research")
            if len(parties) > 1:
                reasons.append("listed_counterpart")
            affiliate = "affiliate" in item.markers
            short, long_ = sorted(
                [normalize_name(supplier_name), normalize_name(text)], key=len
            )
            if kind != "anonymous" and len(short) >= 2 and long_.startswith(short):
                reasons.append("affiliate_name_overlap")
            nodes.setdefault(
                counterpart_id,
                Node(node_id=counterpart_id, label=label, kind=node_kind),
            )
            key = (
                supplier,
                item.product,
                counterpart_id,
                anchor.relation_type,
                affiliate,
                status,
            )
            edge = grouped.get(key)
            if edge is None:
                edge = Edge(
                    edge_id=f"edge-{len(grouped) + 1:03d}",
                    supplier_id=supplier,
                    product=item.product,
                    counterpart_id=counterpart_id,
                    counterpart_kind=kind,
                    relation_type=anchor.relation_type or "unknown",
                    affiliate=affiliate,
                    status=status,
                    event_at=anchor.event_at,
                    event_at_text=anchor.event_at_text,
                )
                grouped[key] = edge
            edge.reasons = sorted(set(edge.reasons) | set(reasons))
            if item.evidence_id not in edge.evidence_ids:
                edge.evidence_ids.append(item.evidence_id)
            if item.source_id not in edge.source_ids:
                edge.source_ids.append(item.source_id)
            if dup_group not in edge.dup_groups:
                edge.dup_groups.append(dup_group)
            if anchor.event_at and not edge.event_at:
                edge.event_at = anchor.event_at
    edges = sorted(
        grouped.values(),
        key=lambda e: (
            e.status != "approved",
            e.supplier_id,
            e.counterpart_id,
            e.relation_type,
        ),
    )
    for n, edge in enumerate(edges, 1):
        edge.edge_id = f"edge-{n:03d}"
    return {
        "nodes": sorted(nodes.values(), key=lambda n: (n.kind, n.label)),
        "edges": edges,
        "counts": relation_counts(edges, co_mentions),
    }


def is_external_transaction(edge: Edge) -> bool:
    return (
        edge.status == "approved"
        and edge.relation_type in TRANSACTION_TYPES
        and not edge.affiliate
        and edge.counterpart_kind != "channel"
        and "counterpart_public_or_research" not in edge.reasons
        and "affiliate_name_overlap" not in edge.reasons
    )


def relation_counts(edges: list[Edge], co_mentions: int) -> dict:
    """보도 건수 요약. 사건 동일성은 확인하지 않으므로 '보도(전재 묶음 기준)'로 센다."""
    approved = [e for e in edges if e.status == "approved"]
    external = [e for e in approved if is_external_transaction(e)]
    return {
        "external_transaction_reports": sum(len(e.dup_groups) for e in external),
        "named_external_adopters": len(
            {e.counterpart_id for e in external if e.counterpart_kind == "named"}
        ),
        "anonymous_cases": len(
            {e.counterpart_id for e in external if e.counterpart_kind == "anonymous"}
        ),
        "affiliate_excluded": sum(
            len(e.dup_groups)
            for e in approved
            if e.affiliate or "affiliate_name_overlap" in e.reasons
        ),
        "plan_or_poc_only": sum(
            len(e.dup_groups) for e in approved if e.relation_type in {"plan", "poc"}
        ),
        "channel_relations": sum(
            len(e.dup_groups) for e in approved if e.counterpart_kind == "channel"
        ),
        "withdrawal": sum(
            len(e.dup_groups) for e in approved if e.relation_type == "withdrawal"
        ),
        "candidate_edges": sum(1 for e in edges if e.status == "candidate"),
        "co_mentions_without_relation": co_mentions,
    }


def relation_label(relation_type: str) -> str:
    return RELATION_LABELS.get(relation_type, "관계 유형 미확인")
