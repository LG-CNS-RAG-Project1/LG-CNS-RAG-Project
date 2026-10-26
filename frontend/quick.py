"""단계형 조사 화면의 공통 입력·문헌·보고서 규칙."""

from frontend.workspace import EXAMPLE, SOURCES, md

DEMO_TEXT = "\n".join(
    [
        EXAMPLE["problem"],
        EXAMPLE["technology"],
        EXAMPLE["customers"],
        EXAMPLE["difference"],
    ]
)
DEMO_PARTS = [
    "카메라와 조명으로 제품 촬영",
    "영상 모델로 불량 후보 표시",
    "기존 생산라인 한 곳에 추가 설치",
]


def candidates(text):
    return (
        [
            dict(
                s,
                entity="시연용 가상 대상",
                period="미확인",
                published_at=None,
                source_url=None,
                version="시연 초안",
            )
            for s in SOURCES
        ]
        if text == DEMO_TEXT
        else []
    )


def validate_parts(parts):
    if not 1 <= len(parts) <= 7:
        return "핵심 구성은 1~7개로 작성해 주세요."
    values = [p.strip() for p in parts]
    if not all(values):
        return "빈 구성을 작성하거나 삭제해 주세요."
    if len(set(values)) != len(values):
        return "중복 구성은 하나로 정리해 주세요."
    return None


def selected_sources(text, ids):
    return [s for s in candidates(text) if s["id"] in ids]


def report(text, title, parts, ids, memo, questions=None, links=None):
    sources = selected_sources(text, ids)
    lines = [
        "# 시장·특허 종합 검토 보고서",
        "",
        "시연용 가상 자료 · 실제 검색/AI 분석 미연결",
        "",
        f"## {md(title) or '이름 없는 아이디어'}",
        md(text),
        "",
        "## 확정한 핵심 구성",
    ]
    lines += [f"{i}. {md(p)}" for i, p in enumerate(parts, 1)]
    for heading, kinds in [("특허·기술", {"특허"}), ("시장·기업", {"시장", "기업"})]:
        rows = [s for s in sources if s["kind"] in kinds]
        lines += ["", f"## {heading}"]
        if not rows:
            lines += ["선택 근거 없음 · 해당 영역 판단 보류"]
        for s in rows:
            lines += [
                f"### [{s['id']}] {s['title']}",
                f"원문 위치: {s['location']}",
                s["quote"],
                f"한계: {s['limit']}",
            ]
    if questions:
        lines += [
            "",
            "## 질문별 연결 검토",
            "| 질문 | 시장 근거 | 관련 구성 | 특허 근거 | 상태 |",
            "|---|---|---|---|---|",
        ]
        for item in review_rows(text, parts, ids, questions, links or {}):
            lines.append(
                f"| {md(item['question'])} | {md(', '.join(item['market_ids']) or '없음')} | {md(', '.join(item['component_ids']) or '없음')} | {md(', '.join(item['patent_ids']) or '없음')} | {md(item['status'])} |"
            )
            lines += [
                f"### {md(item['question'])}",
                f"도입 조건: {md(item['condition']) or '미입력'}",
                f"연결 유형: {md(item['relation'])}",
                f"사용자 연결 이유: {md(item['reason']) or '미작성'}",
                f"조건 차이·한계: {md(item['conditions']) or '미확인'}",
                f"반대 근거·충돌: {md(item['counter_reason']) or '반대 근거를 조사하지 않음'}",
                f"추가 검증: {md(item['next_check']) or '양쪽 원문과 적용 조건 확인'}",
            ]
            for source_id in dict.fromkeys(
                item["market_ids"] + item["patent_ids"] + item["counter_ids"]
            ):
                source = next(s for s in sources if s["id"] == source_id)
                lines += [
                    f"- [{source_id}] {source['title']} / {source['location']}",
                    source["quote"],
                    f"  대상: {source.get('entity','미확인')} · 기준 시점: {source.get('period','미확인')} · {source['limit']}",
                ]
    lines += [
        "",
        "시장 수요·기술 우위·제품 적용·특허성은 아직 확인되지 않았다.",
        "",
        "## 다음 검증",
        "- 실제 시장 자료의 출처·발행일과 고객 구매 조건 확보",
        "- 특허 원문·청구항·권리 상태와 구성별 대응 검토",
        "- 필요한 장비·설치·운영 견적 확인",
        "",
        "## 검토 메모",
        md(memo) or "미작성",
    ]
    return "\n".join(lines)


RELATIONS = [
    "연결 판단 보류",
    "해결 방식 관련",
    "도입 조건과 충돌 가능",
    "차별화 검토 대상",
    "사업 방향 관련",
]
DEMO_QUESTIONS = [
    {
        "id": "Q1",
        "question": "기존 생산라인의 설치 부담을 줄일 수 있는가?",
        "condition": "설치 중단 시간·추가 장치·설비 연동 조건 확인",
    },
    {
        "id": "Q2",
        "question": "고객에게 필요한 불량 검출 성능을 만족하는가?",
        "condition": "불량 유형·촬영 환경·오탐·미탐의 시험 조건 확인",
    },
]


def validate_questions(questions):
    if not 1 <= len(questions) <= 5:
        return "검토 질문은 1~5개로 작성해 주세요."
    values = [q["question"].strip() for q in questions]
    if not all(values) or len(values) != len(set(values)):
        return "빈 질문 또는 중복 질문을 정리해 주세요."
    return None


def review_rows(text, parts, ids, questions, links):
    """선택 집합과 질문·구성을 재검증하고 가설과 부족 영역을 구분한다."""
    sources = {s["id"]: s for s in selected_sources(text, ids)}
    component_ids = {f"C{i}" for i in range(1, len(parts) + 1)}
    rows = []
    for q in questions:
        link = links.get(q["id"], {})
        market = [
            i
            for i in link.get("market_ids", [])
            if i in sources and sources[i]["kind"] != "특허"
        ]
        patents = [
            i
            for i in link.get("patent_ids", [])
            if i in sources and sources[i]["kind"] == "특허"
        ]
        comps = [i for i in link.get("component_ids", []) if i in component_ids]
        counter = [i for i in link.get("counter_ids", []) if i in sources]
        required = (
            market
            and patents
            and comps
            and link.get("reason", "").strip()
            and link.get("relation") != "연결 판단 보류"
        )
        status = (
            "사용자 연결 가설 · 원문 검증 전"
            if required
            else "통합 판단 보류 · 질문별 근거 부족"
        )
        rows.append(
            dict(
                q,
                market_ids=market,
                patent_ids=patents,
                component_ids=comps,
                counter_ids=counter,
                relation=link.get("relation", "연결 판단 보류"),
                reason=link.get("reason", ""),
                conditions=link.get("conditions", ""),
                counter_reason=link.get("counter_reason", ""),
                next_check=link.get("next_check", ""),
                status=status,
            )
        )
    return rows


def validate_link(link, text, parts, selected, questions):
    if link.get("question_id") not in {q["id"] for q in questions}:
        return "현재 검토 질문을 선택해 주세요."
    sources = {s["id"]: s for s in selected_sources(text, selected)}
    for field, patent in [("market_ids", False), ("patent_ids", True)]:
        for source_id in link.get(field, []):
            if (
                source_id not in sources
                or (sources[source_id]["kind"] == "특허") != patent
            ):
                return "선택 목록에 있는 해당 영역의 근거만 연결할 수 있습니다."
    if any(i not in sources for i in link.get("counter_ids", [])):
        return "반대 근거는 선택 목록에서 골라 주세요."
    if any(
        i not in {f"C{n}" for n in range(1, len(parts) + 1)}
        for i in link.get("component_ids", [])
    ):
        return "현재 구성만 선택해 주세요."
    if link.get("relation") not in RELATIONS:
        return "연결 유형을 확인해 주세요."
    if not link.get("next_check", "").strip():
        return "추가 검증 과제를 작성해 주세요."
    if link.get("relation") != "연결 판단 보류" and not link.get("reason", "").strip():
        return "연결 유형의 이유를 작성해 주세요."
    return None
