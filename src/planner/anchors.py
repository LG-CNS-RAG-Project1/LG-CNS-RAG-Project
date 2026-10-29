"""LLM 후보를 원문 위치·특징이 확인된 Anchor로 바꾼다(refresh·reanalyze 때만 실행).

- 구절은 해당 문장의 연속 부분 문자열이어야 한다(rules.align). 없으면 span_not_found로 버린다.
- 부정·예정·철수·계열·잘림·제목 표지, 기준 사전 적중, 관계 동사 유형, 날짜를 원문에서 계산해 둔다.
- 반대 근거(철수·실패·지연 표현이 범위 표현과 같은 문장에 있는 경우)는 LLM 없이 코드로 찾는다.
replay는 이 결과만 읽으므로 본문 파일이 없어도 같은 판정을 재현한다.
"""

import re

from src.planner import rules
from src.planner.config import Profile
from src.planner.extract import article_sentences, has_lexicon_hit
from src.planner.schemas import Anchor, ExtractionRecord, Sentence, Span, TextLayer
from src.planner.store import sha256_hex

ROLE_SUBJECT_RE = rules.SUBJECT_RE


def _span(source_id: str, sentence: Sentence, found: list[tuple[int, int]]) -> Span:
    start, end = found[0]
    return Span(
        source_id=source_id,
        sentence_id=sentence.sentence_id,
        layer=sentence.layer,
        start=sentence.start + start,
        end=sentence.start + end,
        text=sentence.text[start:end],
        occurrences=len(found),
    )


def _tail(sentence: Sentence, found: list[tuple[int, int]], extra: int = 15) -> str:
    start, end = found[0]
    return sentence.text[start : min(len(sentence.text), end + extra)]


def build_anchors(
    source: dict,
    sentences: list[Sentence],
    extraction: ExtractionRecord,
    profile: Profile,
) -> tuple[list[Anchor], list[dict]]:
    """기사 한 건의 Anchor와 거부된 후보를 반환한다. source는 articles 레코드다."""
    source_id = source["source_id"]
    by_id = {s.sentence_id: s for s in sentences}
    title = next((s.text for s in sentences if s.layer == "title"), source["title"])
    anchors: list[Anchor] = []
    rejected: list[dict] = []
    counter = {"n": 0}

    def next_id(kind: str) -> str:
        counter["n"] += 1
        return f"{source_id}:{kind}:{counter['n']}"

    def reject(kind: str, item: dict, reason: str):
        rejected.append(
            {
                "source_id": source_id,
                "kind": kind,
                "sentence_id": item.get("sentence_id", ""),
                "text": (item.get("exact_text") or item.get("exact_clause") or "")[
                    :200
                ],
                "reason": reason,
            }
        )

    candidates = extraction.candidates if extraction.status == "ok" else {}
    mention_roles: dict[str, str] = {}
    seen_mentions = set()
    for item in candidates.get("mentions", []):
        sentence = by_id[item["sentence_id"]]
        found = rules.align(sentence.text, item["exact_text"])
        if not found:
            reject("mention", item, "span_not_found")
            continue
        name = rules.normalize_name(item["exact_text"])
        if not name:
            reject("mention", item, "empty_name")
            continue
        eid = rules.entity_id(name)
        mention_roles.setdefault(name, item["candidate_role"])
        key = (eid, sentence.sentence_id)
        if key in seen_mentions:
            continue
        seen_mentions.add(key)
        features = rules.mention_features(
            name, sentence.text, title, profile.offering_terms
        )
        anchors.append(
            Anchor(
                anchor_id=next_id("mention"),
                source_id=source_id,
                kind="mention",
                span=_span(source_id, sentence, found),
                candidate_role=item["candidate_role"],
                entity_text=name,
                entity_id=eid,
                features=features,
                markers=rules.sentence_markers(
                    sentence.text, sentence.truncated, sentence.layer
                ),
            )
        )

    def other_subject(sentence: Sentence, owner: str) -> bool:
        for name, role in mention_roles.items():
            if name == owner or role == "supplier":
                continue
            if re.search(re.escape(name) + ROLE_SUBJECT_RE, sentence.text):
                return True
        return False

    for item in candidates.get("claims", []):
        sentence = by_id[item["sentence_id"]]
        found = rules.align(sentence.text, item["exact_text"])
        if not found:
            reject("claim", item, "span_not_found")
            continue
        owner = rules.normalize_name(item["owner_text"])
        owner_ok = bool(owner) and bool(rules.align(sentence.text, owner))
        span = _span(source_id, sentence, found)
        features = ["other_subject"] if other_subject(sentence, owner) else []
        if owner and not owner_ok:
            features.append("owner_text_not_in_sentence")
        anchors.append(
            Anchor(
                anchor_id=next_id("claim"),
                source_id=source_id,
                kind="claim",
                span=span,
                entity_text=owner if owner_ok else "",
                owner_entity_id=rules.entity_id(owner) if owner_ok else "",
                product=rules.product_name(item["product_text"], sentence.text),
                criteria=rules.criteria_hits(span.text, profile.criteria),
                features=features,
                markers=rules.sentence_markers(
                    _tail(sentence, found), sentence.truncated, sentence.layer
                ),
            )
        )

    for item in candidates.get("relations", []):
        sentence = by_id[item["sentence_id"]]
        found = rules.align(sentence.text, item["exact_clause"])
        if not found:
            reject("relation", item, "span_not_found")
            continue
        span = _span(source_id, sentence, found)
        subject = rules.normalize_name(item["subject_text"])
        obj = rules.normalize_name(item["object_text"])
        features = []
        if not (
            subject
            and obj
            and rules.align(span.text, subject)
            and rules.align(span.text, obj)
        ):
            features.append("endpoints_not_in_clause")
        for side, text in (("subject", subject), ("object", obj)):
            if rules.is_anonymous(text):
                features.append(f"{side}_anonymous")
            if rules.is_channel(text) or mention_roles.get(text) in {
                "equipment_maker",
                "si_partner",
            }:
                features.append(f"{side}_channel")
            if rules.is_public(text) or mention_roles.get(text) == "public_or_research":
                features.append(f"{side}_public")
        event_at, event_text = rules.event_dates(sentence.text)
        markers = rules.sentence_markers(
            sentence.text, sentence.truncated, sentence.layer
        )
        anchors.append(
            Anchor(
                anchor_id=next_id("relation"),
                source_id=source_id,
                kind="relation",
                span=span,
                entity_text=subject,
                entity_id=rules.entity_id(subject) if subject else "",
                counterpart_text=obj,
                counterpart_id=rules.entity_id(obj) if obj else "",
                relation_type=rules.relation_type(span.text),
                relation_hint=item["relation_hint"],
                product=rules.product_name("", sentence.text),
                features=features,
                markers=markers,
                event_at=event_at,
                event_at_text=event_text,
            )
        )

    for item in candidates.get("metrics", []):
        sentence = by_id[item["sentence_id"]]
        found = rules.align(sentence.text, item["exact_text"])
        if not found:
            reject("metric", item, "span_not_found")
            continue
        span = _span(source_id, sentence, found)
        match = rules.METRIC_RE.search(span.text)
        features = []
        unit = match.group(2).replace(" ", "") if match else ""
        if unit in {"원", "만원", "억원"}:
            features.append("price")
            sales = rules.SALES_UNIT_RE.search(sentence.text)
            if sales:
                features.append(f"sales_unit:{sales.group(0)}")
            if rules.PRICE_SCOPE_RE.search(sentence.text):
                features.append("price_scope")
        owner = next(
            (
                rules.entity_id(name)
                for name, role in mention_roles.items()
                if role == "supplier" and name in sentence.text
            ),
            "",
        )
        anchors.append(
            Anchor(
                anchor_id=next_id("metric"),
                source_id=source_id,
                kind="metric",
                span=span,
                owner_entity_id=owner,
                metric_value=match.group(1) if match else "",
                unit=unit,
                measurement_conditions=(
                    sentence.text[:200]
                    if rules.CONDITION_RE.search(sentence.text)
                    else "unknown"
                ),
                features=features,
                markers=rules.sentence_markers(
                    sentence.text, sentence.truncated, sentence.layer
                ),
            )
        )

    for sentence in sentences:
        if rules.WITHDRAWAL_RE.search(sentence.text) and any(
            term in sentence.text for term in profile.scope.include_any
        ):
            text = sentence.text[:200]
            anchors.append(
                Anchor(
                    anchor_id=next_id("adverse"),
                    source_id=source_id,
                    kind="adverse",
                    span=Span(
                        source_id=source_id,
                        sentence_id=sentence.sentence_id,
                        layer=sentence.layer,
                        start=sentence.start,
                        end=sentence.start + len(text),
                        text=text,
                    ),
                    markers=rules.sentence_markers(
                        sentence.text, sentence.truncated, sentence.layer
                    ),
                )
            )
    return anchors, rejected


def _layers(record: dict, body: str, body_status: str) -> list[TextLayer]:
    layers = [
        TextLayer(
            layer="title",
            origin="naver_search",
            content_hash=sha256_hex(record["title"]),
            chars=len(record["title"]),
        ),
        TextLayer(
            layer="stored_snippet",
            origin="naver_search",
            content_hash=sha256_hex(record["snippet"]),
            chars=len(record["snippet"]),
            truncated=record["snippet"].rstrip().endswith(("...", "…")),
        ),
    ]
    if body_status != "not_attempted":
        layers.append(
            TextLayer(
                layer="reviewed_body",
                origin="auto_fetch",
                content_hash=sha256_hex(body) if body else "",
                chars=len(body),
                status=body_status,
            )
        )
    return layers


def process_articles(
    records: list[dict],
    bodies: dict[str, str],
    body_statuses: dict[str, str],
    extractor,
    profile: Profile,
) -> dict:
    """채택 기사마다 문장 분할 → 사전 확인 → 추출 → Anchor를 만들고 기업 언급 색인을 붙인다.

    반환: articles(메타데이터), extractions, anchors, rejected. extractor가 None이면 추출하지 않는다.
    """
    metas, extractions, anchors, rejected, texts = [], [], [], [], {}
    for record in records:
        sid = record["source_id"]
        body = bodies.get(sid, "")
        status = body_statuses.get(sid, "not_attempted")
        every, chosen = article_sentences(
            record["title"], record["snippet"], body, profile.budget.llm_input_chars
        )
        full_text = "\n".join([record["title"], record["snippet"], body])
        texts[sid] = full_text
        if not has_lexicon_hit(full_text, profile):
            extraction = ExtractionRecord(
                source_id=sid, status="not_extracted_no_lexicon_hit"
            )
        elif extractor is None:
            extraction = ExtractionRecord(
                source_id=sid, status="failed", error="llm_unavailable"
            )
        else:
            extraction = extractor.extract(sid, chosen)
        found, dropped = build_anchors(record, every, extraction, profile)
        extractions.append(extraction)
        anchors += found
        rejected += dropped
        layers = _layers(record, body, status)
        metas.append(
            {
                **record,
                "snippet_truncated": layers[1].truncated,
                "body_status": status,
                "layers": [layer.model_dump() for layer in layers],
                "extraction_status": extraction.status,
            }
        )
    attach_mention_index(metas, anchors, texts)
    return {
        "articles": metas,
        "extractions": extractions,
        "anchors": anchors,
        "rejected": rejected,
        "texts": texts,
    }


def attach_mention_index(
    metas: list[dict], anchors: list[Anchor], texts: dict[str, str]
) -> None:
    """자료집 전체 기업 언급 이름이 각 기사 텍스트에 나오는지 기록한다(미확인 사유 계산용)."""
    names = {
        a.entity_text: a.entity_id
        for a in anchors
        if a.kind == "mention" and len(a.entity_text) >= 2
    }
    for meta in metas:
        text = texts.get(meta["source_id"], "")
        meta["mentioned_entity_ids"] = sorted(
            {eid for name, eid in names.items() if name in text}
        )
