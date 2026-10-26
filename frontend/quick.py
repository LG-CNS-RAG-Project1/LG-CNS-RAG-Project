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
    return [dict(s) for s in SOURCES] if text == DEMO_TEXT else []


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


def report(text, title, parts, ids, memo):
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
    lines += [
        "",
        "## 시장 요구와 기술의 연결",
        "검증할 가설: 구매·도입 조건과 기술 구성이 양립하는지 선택한 원문을 대조한다.",
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
