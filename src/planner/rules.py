"""근거 후보의 판정 규칙(planner-rules-v1).

두 단계로 나뉜다.
- 원문 의존 특징(구절 정렬·표지·관계 동사 분류): refresh/reanalyze 때 anchors가 호출한다.
- 승인 판정(공급사·주장·관계·수치·반대 근거): 원문 없이 Anchor만 읽어 replay에서도 같은 결과를 낸다.

규칙은 명확한 패턴만 승인하고 애매한 후보는 사유와 함께 후보(candidate)로 남긴다.
정규식·사전이 문장 의미를 모두 확정한다고 가정하지 않으며, 구절이 원문에 있다는 확인은
그 구절이 주장을 뒷받침한다는 의미 검증과 다르다.
"""

import hashlib
import re
import unicodedata

from src.planner.schemas import Anchor, Entity, Evidence

RULE_VERSION = "planner-rules-v3"

NEGATION_RE = re.compile(
    r"않는다|않았다|않아|않고|않는|않을|못한다|못했|못하|아니다|아닌|어렵다|어려운|"
    r"어려워|불가능|불가하|한계가 있|여전히 필요"
)
PLAN_RE = re.compile(
    r"예정|계획이다|계획을|계획하|추진할|추진한다|추진 중|추진하고|추진키로|목표로|방침|할 것|"
    r"나설|키로|MOU|업무협약|협약"
)
PRONOUN_SUBJECT_RE = re.compile(
    r"(?:^|\s)(?:이\s)?(?:회사|업체|기업|동사)(?:\s?측)?(?:은|는|이|가)\s"
)
GENERIC_NAMES = {
    "회사",
    "업체",
    "기업",
    "당사",
    "동사",
    "이 회사",
    "해당 기업",
    "고객사",
    "제조사",
}
PUBLIC_NAMES = {
    "코트라",
    "KOTRA",
    "정부",
    "중기부",
    "중소벤처기업부",
    "산업부",
    "산업통상자원부",
    "과기정통부",
    "과학기술정보통신부",
    "지자체",
}
WITHDRAWAL_RE = re.compile(r"철수|중단|실패|포기|해지|철회|지연")
AFFILIATE_RE = re.compile(
    r"자회사|계열사|계열|그룹 내|그룹사|자체 라인|자사 공장|자사 생산|관계사|"
    r"현지 법인|현지법인|생산법인"
)
CHANNEL_RE = re.compile(
    r"장비사|장비 업체|장비업체|OEM|\bSI\b|SI 업체|SI업체|시스템 통합|협력사|파트너사|총판|대리점"
)
SUPPLY_VERB_RE = re.compile(
    r"출시|공급|개발|선보|선봬|공개|납품|수주|제공|판매|내놓|탑재|구현|내세|갖췄|갖춘|"
    r"넣었|고도화|론칭|수행|설계|구축해|구축한다|구축하고"
)
SPOKESPERSON_RE = r"\s*(?:대표|대표이사|CEO|사장)"
COMPOUND_RE = re.compile(r"(?:와|과)\s|,|·|및\s")
RESEARCH_SUFFIXES = ("연구진", "연구팀", "교수팀", "교수", "연구원장")
ADOPT_VERB_RE = re.compile(r"도입|적용|사용|가동|운영")
SUBJECT_RE = r"\s*(?:은|는|이|가|측은|측이|측도|도)\s"
PUBLIC_SUFFIXES = (
    "부",
    "청",
    "처",
    "진흥원",
    "테크노파크",
    "대학교",
    "대학",
    "연구원",
    "연구소",
    "센터",
    "재단",
    "협회",
    "공단",
    "공사",
    "위원회",
    "시청",
    "도청",
    "군청",
    "구청",
)
ANON_DESCRIPTORS = {
    "국내",
    "국내외",
    "해외",
    "글로벌",
    "주요",
    "대형",
    "중견",
    "중소",
    "한",
    "일부",
    "복수",
    "복수의",
    "다수",
    "다수의",
    "2차전지",
    "이차전지",
    "배터리",
    "전자부품",
    "반도체",
    "자동차",
    "부품",
    "소재",
    "식품",
    "제조",
    "대기업",
    "완성차",
    "고객",
}
ANON_NOUNS = (
    "고객사",
    "제조사",
    "제조업체",
    "업체",
    "기업",
    "회사",
    "공장",
    "생산라인",
    "양산라인",
)
GENERIC_PRODUCT_WORDS = {
    "ai",
    "비전",
    "비전검사",
    "검사",
    "외관",
    "외관검사",
    "머신비전",
    "딥러닝",
    "솔루션",
    "플랫폼",
    "시스템",
    "장비",
    "모듈",
    "검사기",
    "검사장비",
    "소프트웨어",
    "자동화",
    "품질",
    "스마트",
    "기반",
    "통합",
    "기술",
    "제품",
}
RELATION_TYPES = [
    ("withdrawal", re.compile(r"철수|중단|해지|철회|실패")),
    ("plan", PLAN_RE),
    ("repeat", re.compile(r"추가 발주|추가 수주|재계약|확대 적용|추가 도입|추가 공급")),
    (
        "operation",
        re.compile(
            r"가동 중|가동하고|운영 중|운영하고|양산 적용|양산라인에 적용|사용 중"
        ),
    ),
    (
        "install",
        re.compile(
            r"설치|구축을 완료|구축 완료|구축했|도입했|도입을 완료|납품을 완료|적용했"
        ),
    ),
    ("contract", re.compile(r"계약|수주")),
    ("poc", re.compile(r"실증|PoC|시범|파일럿|검증|테스트")),
    ("joint_dev", re.compile(r"공동 개발|공동개발|함께 개발|협력해 개발")),
    ("supply", re.compile(r"공급|납품|도입|구축|적용")),
]
TRANSACTION_TYPES = {"supply", "contract", "install", "operation", "repeat"}
RELATION_LABELS = {
    "supply": "공급·도입 보도",
    "contract": "계약 보도",
    "install": "설치·구축 보도",
    "operation": "운영 보도",
    "repeat": "추가 발주 보도",
    "poc": "실증·검증",
    "plan": "계획·협약",
    "joint_dev": "공동 개발",
    "withdrawal": "철수·중단",
}
DATE_RE = re.compile(r"(20\d{2})\s*년\s*(\d{1,2})\s*월\s*(\d{1,2})\s*일")
RELATIVE_DATE_RE = re.compile(
    r"(?:지난|오는)\s*\d{1,2}\s*일|\d{1,2}\s*일\s*(?:밝혔|발표)"
)
METRIC_RE = re.compile(
    r"(\d+(?:[.,]\d+)?)\s*(%|퍼센트|시간|분|초|배|억\s?원|만\s?원|원|건|대|개사|곳)"
)
CONDITION_RE = re.compile(
    r"조건에서|조건으로|기준으로|대비|테스트에서|시험에서|측정 결과|측정한 결과|"
    r"실험에서|환경에서|평가에서"
)
SALES_UNIT_RE = re.compile(r"대당|1대|한 대|라인|프로젝트|시스템|계약|세트|연간")
PRICE_SCOPE_RE = re.compile(r"설치|유지보수|라이선스|보증|포함|구독|임대|리스")
LEGAL_RE = re.compile(
    r"\(주\)|㈜|주식회사|\(유\)|유한회사|\(사\)|사단법인|재단법인|"
    r"\bCo\.,?\s*Ltd\.?|\bInc\.?|\bCorp\.?",
    re.I,
)
QUOTE_MAP = str.maketrans(
    {
        "‘": "'",
        "’": "'",
        "“": '"',
        "”": '"',
        "「": '"',
        "」": '"',
        "『": '"',
        "』": '"',
        "ㆍ": "·",
        "•": "·",
        "・": "·",
    }
)


# 원문 의존 특징 ----------------------------------------------------------------
def normalize_name(text: str) -> str:
    """기업명 정규화: NFC, 법인 표기 제거, 공백 정리, 양끝 문장부호 제거."""
    name = unicodedata.normalize("NFC", text or "")
    name = LEGAL_RE.sub("", name)
    return " ".join(name.split()).strip(" ,·'\"‘’“”()")


def mention_name(text: str) -> tuple[str, str]:
    """LLM 언급 구절에서 기업명만 남긴다. (이름, 거부 사유).

    '(대표 ...)' 같은 괄호 설명을 떼고, 문장 전체가 온 경우 첫 주어(이름+은/는/이/가)만 쓴다.
    여러 기관을 묶은 언급('A와 B', 'A·B')과 연구진·교수 언급은 기업명으로 쓰지 않는다.
    """
    name = normalize_name(re.split(r"[(（]", text or "", maxsplit=1)[0])
    parts = split_parties(name)
    if len(parts) > 1 and all(len(p) <= 20 and len(p.split()) <= 2 for p in parts):
        return "", "compound_mention"
    if len(name) > 25 or len(name.split()) > 3:
        lead = re.match(r"^\s*(\S{2,20}?)(?:은|는|이|가)\s", normalize_name(text))
        if not lead:
            return "", "mention_not_a_name"
        name = normalize_name(lead.group(1))
    if not name:
        return "", "empty_name"
    if COMPOUND_RE.search(name):
        return "", "compound_mention"
    if name.endswith(RESEARCH_SUFFIXES):
        return "", "research_team_mention"
    if name in GENERIC_NAMES:
        return "", "generic_noun_mention"
    return name, ""


def entity_id(name: str) -> str:
    key = normalize_name(name).replace(" ", "").lower()
    return "org-" + hashlib.sha1(key.encode("utf-8")).hexdigest()[:10]


def align(sentence: str, exact: str) -> list[tuple[int, int]]:
    """exact가 sentence의 연속 구절인지 찾는다(따옴표·가운뎃점·공백만 정규화, 퍼지 없음).

    반환은 원 문장 기준 (start, end) 목록이며 없으면 빈 목록이다.
    """
    chars, index, previous_space = [], [], False
    for i, char in enumerate(sentence):
        char = char.translate(QUOTE_MAP)
        if char.isspace():
            if previous_space or not chars:
                continue
            char, previous_space = " ", True
        else:
            previous_space = False
        chars.append(char)
        index.append(i)
    normalized = "".join(chars)
    target = " ".join(
        unicodedata.normalize("NFC", exact or "").translate(QUOTE_MAP).split()
    )
    if not target:
        return []
    found, start = [], 0
    while (k := normalized.find(target, start)) >= 0:
        found.append((index[k], index[k + len(target) - 1] + 1))
        start = k + 1
    return found


def is_public(name: str) -> bool:
    name = normalize_name(name)
    return name in PUBLIC_NAMES or name.endswith(PUBLIC_SUFFIXES)


def is_anonymous(text: str) -> bool:
    """고유명 없이 업종·규모 수식어와 일반 명사로만 된 상대(예: '국내 이차전지 제조사', 'A사')."""
    words = normalize_name(text).split()
    if len(words) == 1 and re.fullmatch(r"[A-Z]사", words[0]):
        return True
    if not words:
        return False
    last = re.sub(r"들$", "", words[-1])
    head = words[:-1]
    for noun in ANON_NOUNS:
        if last.endswith(noun):
            prefix = last[: -len(noun)]
            if prefix and prefix not in ANON_DESCRIPTORS:
                return False
            return all(word in ANON_DESCRIPTORS for word in head)
    return False


def ends_with_generic_noun(text: str) -> bool:
    last = re.sub(r"들$", "", (normalize_name(text).split() or [""])[-1])
    return any(last.endswith(noun) for noun in ANON_NOUNS)


def split_parties(text: str) -> list[str]:
    """'A · B · C', 'A, B', 'A와 B'처럼 나열된 상대를 나눈다. 나눌 수 없으면 원문 하나."""
    parts = [
        normalize_name(p) for p in re.split(r"\s*(?:·|,|및|와\s|과\s)\s*", text or "")
    ]
    parts = [p for p in parts if len(p) >= 2]
    return parts if len(parts) > 1 else [normalize_name(text)]


def is_channel(text: str) -> bool:
    return bool(CHANNEL_RE.search(text or ""))


def relation_type(clause: str) -> str:
    """관계 동사 분류. 철수·계획 표지가 다른 동사보다 앞선다. 동사가 없으면 빈 값(동시 언급)."""
    for name, pattern in RELATION_TYPES:
        if pattern.search(clause):
            return name
    return ""


def product_name(product_text: str, sentence: str) -> str:
    """제품명 승인: 문장에 그대로 있고, 따옴표 안이거나 일반 명사만으로 이뤄지지 않을 때."""
    name = " ".join((product_text or "").split()).strip("'\"‘’“”「」")
    if not name or not align(sentence, name):
        return ""
    quoted = re.search(
        r"['‘\"“「『]\s*" + re.escape(name) + r"\s*['’\"”」』]", sentence
    )
    words = {w.lower() for w in re.split(r"[\s·]+", name) if w}
    if quoted or not words <= GENERIC_PRODUCT_WORDS:
        return name
    return ""


def criteria_hits(text: str, criteria) -> dict[str, str]:
    hits = {}
    for criterion in criteria:
        if any(term in text for term in criterion.strong):
            hits[criterion.id] = "strong"
        elif any(term in text for term in criterion.weak):
            hits[criterion.id] = "weak"
    return hits


def mention_features(name: str, sentence: str, title: str, offering_terms) -> list[str]:
    """공급사 승인에 쓰는 특징: 제목 첫머리, 주어+공급 동사, 제공물 표현, 공공 기관, 부정."""
    features = []
    escaped = re.escape(name)
    if name and name in title:
        features.append("in_title")
    if re.match(r"\s*" + escaped + r"\s*[,，]", title):
        features.append("headline_lead")
    subject = re.search(escaped + SUBJECT_RE, sentence)
    if subject and SUPPLY_VERB_RE.search(sentence[subject.end() :]):
        features.append("subject_supply")
    if re.search(escaped + SPOKESPERSON_RE, f"{title}\n{sentence}"):
        features.append("spokesperson")
    if subject and ADOPT_VERB_RE.search(sentence[subject.end() :]):
        features.append("subject_adopt")
    if any(term in sentence for term in offering_terms):
        features.append("offering_term")
    if is_public(name):
        features.append("public_marker")
    return features


def sentence_markers(text: str, sentence_truncated: bool, layer: str) -> list[str]:
    markers = []
    if NEGATION_RE.search(text):
        markers.append("negated")
    if PLAN_RE.search(text):
        markers.append("planned")
    if WITHDRAWAL_RE.search(text):
        markers.append("withdrawal")
    if AFFILIATE_RE.search(text):
        markers.append("affiliate")
    if sentence_truncated:
        markers.append("truncated")
    if layer == "title":
        markers.append("title_only")
    return markers


def event_dates(sentence: str) -> tuple[str, str]:
    """같은 문장의 절대 날짜만 event_at으로 쓴다. 상대 표현은 텍스트로만 남긴다."""
    match = DATE_RE.search(sentence)
    if match:
        year, month, day = (int(x) for x in match.groups())
        return f"{year:04d}-{month:02d}-{day:02d}", ""
    relative = RELATIVE_DATE_RE.search(sentence)
    return "", relative.group(0) if relative else ""


# 승인 판정 ---------------------------------------------------------------------
def _layer(span) -> str:
    return "reviewed_body" if span.layer == "reviewed_body" else "stored_snippet"


def approve_suppliers(anchors: list[Anchor]) -> tuple[dict, dict, list[Evidence]]:
    """기사별 승인 공급사와 엔터티 목록, 공급사 근거를 만든다."""
    approved_in: dict[str, set[str]] = {}
    entities: dict[str, Entity] = {}
    roles: dict[str, set[str]] = {}
    evidence = []
    for anchor in anchors:
        if anchor.kind != "mention" or not anchor.entity_id:
            continue
        features = set(anchor.features)
        reasons = []
        if anchor.candidate_role != "supplier":
            reasons.append(f"role_{anchor.candidate_role}")
        if not features & {"headline_lead", "subject_supply", "spokesperson"}:
            reasons.append("supplier_pattern_not_matched")
        if "subject_adopt" in features and "subject_supply" not in features:
            reasons.append("adopter_pattern")
        if "offering_term" not in features:
            reasons.append("no_offering_term")
        if "public_marker" in features:
            reasons.append("public_or_research")
        if "negated" in anchor.markers or "withdrawal" in anchor.markers:
            reasons.append("negated_or_withdrawal")
        ok = not reasons
        entity = entities.setdefault(
            anchor.entity_id,
            Entity(
                entity_id=anchor.entity_id,
                name=anchor.entity_text,
                role=anchor.candidate_role,
                approved=False,
            ),
        )
        roles.setdefault(anchor.entity_id, set()).add(anchor.candidate_role)
        if anchor.source_id not in entity.source_ids:
            entity.source_ids.append(anchor.source_id)
        if ok:
            entity.approved = True
            approved_in.setdefault(anchor.source_id, set()).add(anchor.entity_id)
        else:
            entity.reasons = sorted(set(entity.reasons) | set(reasons))
        if anchor.candidate_role == "supplier":
            evidence.append(
                Evidence(
                    evidence_id=f"ev:{anchor.anchor_id}",
                    anchor_id=anchor.anchor_id,
                    source_id=anchor.source_id,
                    kind="supplier",
                    span=anchor.span,
                    evidence_layer=_layer(anchor.span),
                    statement_kind="reported_event",
                    review_status="approved" if ok else "candidate",
                    reasons=reasons,
                    supplier_id=anchor.entity_id,
                    markers=list(anchor.markers),
                )
            )
    for entity in entities.values():
        entity.role = "|".join(sorted(roles[entity.entity_id]))
        if entity.approved:
            entity.reasons = []
        entity.source_ids.sort()
    return approved_in, entities, evidence


def evaluate_claim(anchor: Anchor, approved_in: dict) -> Evidence:
    """주장 근거: 주체가 그 기사의 승인 공급사로 확인돼야 승인한다."""
    suppliers = approved_in.get(anchor.source_id, set())
    reasons, supplier, basis = [], "", ""
    if anchor.owner_entity_id:
        if anchor.owner_entity_id in suppliers:
            supplier, basis = anchor.owner_entity_id, "owner_text"
        else:
            reasons.append("owner_not_approved_supplier")
    elif len(suppliers) == 1 and "other_subject" not in anchor.features:
        supplier, basis = next(iter(suppliers)), "single_supplier_in_article"
    else:
        reasons.append("owner_unconfirmed")
    return Evidence(
        evidence_id=f"ev:{anchor.anchor_id}",
        anchor_id=anchor.anchor_id,
        source_id=anchor.source_id,
        kind="claim",
        span=anchor.span,
        evidence_layer=_layer(anchor.span),
        statement_kind="supplier_claim",
        review_status="candidate" if reasons else "approved",
        reasons=reasons + ([f"owner_basis:{basis}"] if basis else []),
        supplier_id=supplier,
        product=anchor.product,
        criteria=dict(anchor.criteria),
        markers=list(anchor.markers),
    )


def evaluate_relation(
    anchor: Anchor, approved_in: dict, approved_anywhere: set[str] = frozenset()
) -> Evidence:
    """관계 근거: 관계 동사가 있고 한쪽이 승인 공급사여야 승인한다.

    그 기사에서 승인된 공급사를 먼저 쓰고, 없으면 다른 기사에서 승인된 공급사가 한쪽에만
    있을 때 그쪽을 공급사로 본다(사유 supplier_approved_in_other_article).
    동사가 없는 동시 언급은 간선을 만들지 않는다(co_mention, 감사용).
    """
    suppliers = approved_in.get(anchor.source_id, set())
    reasons, notes = [], []
    if not anchor.relation_type:
        reasons.append("co_mention_no_relation_verb")
    if "endpoints_not_in_clause" in anchor.features:
        reasons.append("endpoints_not_in_clause")
    sides = [anchor.entity_id, anchor.counterpart_id]
    local = [side for side in sides if side and side in suppliers]
    elsewhere = [side for side in sides if side and side in approved_anywhere]
    if len(local) == 1 or (local and local[0] == sides[0]):
        supplier = local[0]
    elif len(elsewhere) == 1:
        supplier = elsewhere[0]
        notes.append("supplier_approved_in_other_article")
    else:
        supplier = ""
        reasons.append("supplier_unresolved")
    if "negated" in anchor.markers and anchor.relation_type != "withdrawal":
        reasons.append("negated")
    if supplier:
        side = "subject" if supplier == anchor.counterpart_id else "object"
        if (
            f"{side}_is_mention" not in anchor.features
            and f"{side}_anonymous" not in anchor.features
        ):
            reasons.append("counterpart_not_an_organization")
    if "relation_on_topic" not in anchor.features:
        reasons.append("off_topic_relation")
    return Evidence(
        evidence_id=f"ev:{anchor.anchor_id}",
        anchor_id=anchor.anchor_id,
        source_id=anchor.source_id,
        kind="relation",
        span=anchor.span,
        evidence_layer=_layer(anchor.span),
        statement_kind="reported_event",
        review_status="candidate" if reasons else "approved",
        reasons=reasons + notes,
        supplier_id=supplier,
        product=anchor.product,
        markers=list(anchor.markers),
    )


def evaluate_metric(anchor: Anchor, approved_in: dict) -> Evidence:
    """수치 근거: 값과 단위가 원문 구절에 있으면 승인한다. 조건이 없으면 unknown으로 둔다."""
    suppliers = approved_in.get(anchor.source_id, set())
    owner = anchor.owner_entity_id if anchor.owner_entity_id in suppliers else ""
    reasons = [] if anchor.metric_value and anchor.unit else ["no_value_or_unit"]
    features = [
        f
        for f in anchor.features
        if f == "price" or f.startswith(("sales_unit", "price_"))
    ]
    if anchor.measurement_conditions != "unknown":
        features.append("conditions_stated")
    return Evidence(
        evidence_id=f"ev:{anchor.anchor_id}",
        anchor_id=anchor.anchor_id,
        source_id=anchor.source_id,
        kind="metric",
        span=anchor.span,
        evidence_layer=_layer(anchor.span),
        statement_kind="supplier_claim" if owner else "reported_event",
        review_status="candidate" if reasons else "approved",
        reasons=reasons,
        supplier_id=owner,
        markers=list(anchor.markers) + features,
    )


def evaluate_adverse(anchor: Anchor) -> Evidence:
    return Evidence(
        evidence_id=f"ev:{anchor.anchor_id}",
        anchor_id=anchor.anchor_id,
        source_id=anchor.source_id,
        kind="adverse",
        span=anchor.span,
        evidence_layer=_layer(anchor.span),
        statement_kind="reported_event",
        review_status="approved",
        markers=list(anchor.markers),
    )


def apply_reviews(evidence: list[Evidence], reviews: list[dict]) -> list[Evidence]:
    """검토 결정 적용: reject는 후보로 내리고, approve는 필요한 주체가 있을 때만 승인한다."""
    decisions = {}
    for review in reviews:
        decisions[review["evidence_id"]] = review
    result = []
    for item in evidence:
        review = decisions.get(item.evidence_id)
        if review is None:
            result.append(item)
            continue
        note = review.get("reason", "")
        if review["decision"] == "reject":
            item = item.model_copy(
                update={
                    "review_status": "candidate",
                    "reasons": item.reasons + ["reviewer_rejected"],
                    "reviewer_note": note,
                }
            )
        elif review["decision"] == "approve":
            needs_supplier = item.kind in {"claim", "relation"}
            if needs_supplier and not item.supplier_id:
                item = item.model_copy(
                    update={
                        "reasons": item.reasons + ["approval_not_applicable"],
                        "reviewer_note": note,
                    }
                )
            else:
                item = item.model_copy(
                    update={
                        "review_status": "approved",
                        "reasons": item.reasons + ["reviewer_approved"],
                        "reviewer_note": note,
                    }
                )
        result.append(item)
    return result


def supplier_index(evidence: list[Evidence]) -> dict[str, set[str]]:
    """승인된 공급사 근거에서 기사별 승인 공급사 집합을 만든다."""
    index: dict[str, set[str]] = {}
    for item in evidence:
        if item.kind == "supplier" and item.review_status == "approved":
            index.setdefault(item.source_id, set()).add(item.supplier_id)
    return index


def evaluate_evidence(
    anchors: list[Anchor], reviews: list[dict] | None = None
) -> tuple[list[Evidence], dict[str, Entity], dict[str, set[str]]]:
    """Anchor 전체를 판정한다. 공급사 검토를 먼저 반영한 뒤 주장·관계·수치를 판정한다."""
    reviews = reviews or []
    _, entities, supplier_evidence = approve_suppliers(anchors)
    supplier_evidence = apply_reviews(supplier_evidence, reviews)
    approved_in = supplier_index(supplier_evidence)
    approved_ids = {eid for ids in approved_in.values() for eid in ids}
    for entity in entities.values():
        entity.approved = entity.entity_id in approved_ids
        if entity.approved:
            entity.role, entity.reasons = "supplier", []
    evidence = list(supplier_evidence)
    for anchor in anchors:
        if anchor.kind == "claim":
            evidence.append(evaluate_claim(anchor, approved_in))
        elif anchor.kind == "relation":
            evidence.append(evaluate_relation(anchor, approved_in, approved_ids))
        elif anchor.kind == "metric":
            evidence.append(evaluate_metric(anchor, approved_in))
        elif anchor.kind == "adverse":
            evidence.append(evaluate_adverse(anchor))
    supplier_ids = {e.evidence_id for e in supplier_evidence}
    others = apply_reviews(
        [e for e in evidence if e.evidence_id not in supplier_ids], reviews
    )
    evidence = supplier_evidence + others
    evidence.sort(key=lambda e: e.evidence_id)
    return evidence, entities, approved_in
