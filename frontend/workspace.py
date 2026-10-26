"""아이디어 검토 화면의 예시 자료, 비용 계산 및 보고서 구성."""

from copy import deepcopy
from math import isfinite

FIELDS = {
    "problem": "해결할 문제",
    "technology": "구현할 기술",
    "customers": "사용자 · 구매자",
    "difference": "기존 방식과의 차이",
    "revenue": "수익 방식",
}
EXAMPLE = {
    "idea": "소규모 제조라인에 붙여 쓰는 카메라 기반 불량 검사 장치",
    "problem": "작업자가 눈으로 검사하는 과정에서 작은 외관 불량을 놓친다.",
    "technology": "카메라와 조명으로 제품을 촬영하고, 영상 모델로 불량 후보를 표시한다.",
    "customers": "소규모 부품 제조사의 품질 담당자가 사용하고, 생산 책임자가 구매를 검토한다.",
    "difference": "라인 전체를 바꾸지 않고 검사 위치 한 곳에 추가 설치하는 방식을 검토한다.",
    "revenue": "장치 공급과 검사 모델 유지보수 비용을 받는 방식을 검토한다.",
}
SOURCES = [
    {
        "id": "M1",
        "kind": "시장",
        "title": "가상 고객 인터뷰 메모",
        "location": "메모 1 · 검사 업무",
        "quote": "[시연 문장] 검사 담당자는 불량 누락뿐 아니라 새 장치의 설치 중단 시간도 확인하려 한다.",
        "limit": "실제 인터뷰가 아닙니다. 구매 의사나 수요 규모를 입증하지 않습니다.",
    },
    {
        "id": "M2",
        "kind": "기업",
        "title": "가상 경쟁사 사업보고서",
        "location": "사업의 내용 · 제품 구성",
        "quote": "[시연 문장] 가상 A사는 카메라·조명·소프트웨어를 함께 공급하는 검사 시스템을 설명한다.",
        "limit": "실제 공시가 아닙니다. 매출, 고객 수, 가격은 확보하지 않았습니다.",
    },
    {
        "id": "P1",
        "kind": "특허",
        "title": "가상 문헌 · 영상 기반 검사",
        "location": "요약 · 문단 1",
        "quote": "[시연 문장] 촬영한 대상의 영상 특징을 기준 영상과 비교해 결함 후보를 출력한다.",
        "limit": "실제 특허가 아닙니다. 청구항·법적 상태 미확인으로 권리범위를 판단할 수 없습니다.",
    },
    {
        "id": "P2",
        "kind": "특허",
        "title": "가상 문헌 · 검사 조명 제어",
        "location": "요약 · 문단 2",
        "quote": "[시연 문장] 검사 대상의 표면 상태에 따라 조명의 조건을 조정한다.",
        "limit": "실제 특허가 아닙니다. 장치의 장착 방식과 모델 학습 방식은 설명되지 않았습니다.",
    },
]
MARKET = [
    (
        "수요 · 사용자",
        "품질 담당자의 불량 누락과 검사 부담",
        "사용자 가설",
        "M1",
        "실제 불량률·검사시간과 구매 의사를 인터뷰로 확인",
    ),
    (
        "경쟁 · 대체재",
        "가상 A사의 통합 검사 장치와 수작업 검사 비교",
        "예시 자료",
        "M2",
        "국내·해외 기업의 동일 사양·지원 범위 비교",
    ),
    (
        "가격 · 구매자",
        "생산 책임자가 예산과 유지보수 조건을 검토",
        "사용자 가설",
        "",
        "견적·예산 승인 절차·유지보수 비용 확보",
    ),
    (
        "도입 장벽",
        "라인 중단 시간과 현장 조명 조건",
        "검증 가설",
        "M1",
        "파일럿에서 설치 시간과 오탐·미탐을 측정",
    ),
]
PATENTS = [
    (
        "영상으로 결함 후보 검출",
        "설명 일부 대응",
        "P1",
        "청구항과 실제 구현 범위를 대조해야 함",
    ),
    (
        "표면에 맞춘 조명 조정",
        "관련 구성",
        "P2",
        "아이디어에 필요한 제어 조건을 구체화해야 함",
    ),
    (
        "기존 라인에 추가 설치",
        "현재 자료로 미확인",
        "",
        "장착 구조와 설비 연결 관계를 추가 조사",
    ),
]
TASKS = [
    "목표 고객에게 현재 업무와 문제로 발생하는 비용 확인",
    "국내·해외 경쟁 제품의 사양과 견적 비교",
    "관련 특허의 청구항과 원문 확보",
    "설치·연동·유지보수 및 납기 견적 확보",
]


def example_costs():
    return deepcopy(
        [
            {
                "항목": "산업용 카메라",
                "수량": 2,
                "단가(만원)": 80.0,
                "근거 / 가정": "시연 가정 · 실제 견적 아님",
                "납기": "미확인",
            },
            {
                "항목": "조명과 렌즈",
                "수량": 1,
                "단가(만원)": 35.0,
                "근거 / 가정": "시연 가정 · 실제 견적 아님",
                "납기": "미확인",
            },
            {
                "항목": "처리 장치",
                "수량": 1,
                "단가(만원)": 120.0,
                "근거 / 가정": "시연 가정 · 실제 견적 아님",
                "납기": "미확인",
            },
            {
                "항목": "설치·설비 연동",
                "수량": 1,
                "단가(만원)": None,
                "근거 / 가정": "현장 견적 필요",
                "납기": "미확인",
            },
        ]
    )


def empty_costs():
    return [
        {
            "항목": "견적 요청 항목",
            "수량": 1,
            "단가(만원)": None,
            "근거 / 가정": "",
            "납기": "미확인",
        }
    ]


def cost_summary(rows):
    """빈 금액을 0원으로 간주하지 않고 유효한 입력만 부분 합산한다."""
    total, missing, errors = 0.0, [], []
    for row in rows:
        name = str(row.get("항목") or "이름 없는 항목").strip()
        quantity, price = row.get("수량"), row.get("단가(만원)")
        if quantity is None or price is None:
            missing.append(name)
            continue
        try:
            quantity, price = float(quantity), float(price)
            if not isfinite(quantity) or not isfinite(price):
                raise ValueError
            if quantity <= 0 or not quantity.is_integer() or price < 0:
                raise ValueError
        except (ValueError, TypeError):
            errors.append(name)
            continue
        total += quantity * price
    return {"total": total, "missing": missing, "errors": errors}


def is_example(brief):
    return brief == EXAMPLE


def md(value):
    """사용자 텍스트가 다운로드 문서의 HTML 또는 표 구조가 되지 않게 한다."""
    from html import escape

    return escape(str(value)).replace("|", "\\|").replace("\n", " / ")


def export_report(brief, rows, note, done):
    sample = is_example(brief)
    cost = cost_summary(rows)
    lines = [
        "# 아이디어 사업 검토 노트",
        "",
        (
            "시연 자료 · 실제 검색/AI 분석 API 미연결"
            if sample
            else "사용자 작성 브리프 · 실제 검색/AI 분석 API 미연결"
        ),
        "",
        f"## {md(brief['idea'])}",
    ]
    lines += [
        f"- {label}: {md(brief[key]) or '미입력'}" for key, label in FIELDS.items()
    ]
    if sample:
        lines += ["", "## 시장·기업 조사 (가상 예시)"]
        lines += [
            f"- {title}: {claim} [{status}] {citation} — 다음 확인: {gap}"
            for title, claim, status, citation, gap in MARKET
        ]
        lines += ["", "## 특허 구성 비교 (가상 예시)"]
        lines += [
            f"- {part}: {status} {citation} — {gap}"
            for part, status, citation, gap in PATENTS
        ]
        lines += [
            "",
            "## 연결해서 볼 질문",
            "- 설치 부담이 구매 장벽이라면, 추가 설치 구조를 검토하고 설치·연동 견적을 함께 확보한다.",
            "- 시장 수요·기술 차별성·사업성은 아직 검증되지 않았다.",
            "",
            "## 근거 모음",
        ]
        lines += [
            f"- [{s['id']}] {s['title']} / {s['location']}\n  {s['quote']}\n  한계: {s['limit']}"
            for s in SOURCES
        ]
    else:
        lines += [
            "",
            "## 조사 상태",
            "자료 수집 전. 사용자 입력에 예시 분석이나 가상 근거를 적용하지 않았습니다.",
        ]
    lines += [
        "",
        "## 구현 비용",
        "금액 단위: 만원. 사용자 입력/시연 가정이며 실제 견적 여부는 별도 확인해야 합니다.",
        f"입력 금액 소계: {cost['total']:,.1f}만원 (총사업비 아님)",
    ]
    for row in rows:
        price = row.get("단가(만원)")
        lines.append(
            f"- {md(row.get('항목', ''))}: 수량 {md(row.get('수량'))}, 단가 {md(price) if price is not None else '미확인'} / {md(row.get('근거 / 가정', ''))} / 납기 {md(row.get('납기', '미확인'))}"
        )
    lines += [
        f"미입력 항목: {', '.join(map(md, cost['missing'])) or '없음'}",
        f"오류 항목: {', '.join(map(md, cost['errors'])) or '없음'}",
        "세금·배송·설치·개발·운영비는 표에 입력한 항목만 반영합니다. 수익성·회수기간은 산출하지 않습니다.",
        "",
        "## 다음 조사",
        *[f"- [{'x' if task in done else ' '}] {task}" for task in TASKS],
        "",
        "## 팀 검토 메모",
        md(note) or "미작성",
    ]
    return "\n".join(lines)
