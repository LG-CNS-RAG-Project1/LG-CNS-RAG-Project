"""기업 비교 UI용 가상 자료와 외부 호출 없는 요청 검증·보고서."""

from copy import deepcopy
from datetime import date

SECTORS = [
    "설비 관리",
    "품질 검사",
    "생산 운영",
    "공정 제어",
    "공장 물류",
    "데이터·통합",
]
DEFAULT_QUESTION = "두 기업의 설비 관리 사업과 기술 접근은 어떻게 다른가요?"
SCENARIOS = ["기본 비교", "일부 자료 없음", "검색 결과 없음", "수집 오류"]


def default_request() -> dict:
    """가상 예시가 적용되는 고정 조사 범위를 반환한다."""
    return {
        "companies": ["가상 A사", "가상 B사"],
        "sector": "설비 관리",
        "start_date": "2024-01-01",
        "end_date": "2026-10-22",
        "question": DEFAULT_QUESTION,
        "role": "솔루션 공급기업",
    }


def validate_request(request: dict) -> list[str]:
    """비교 대상·질문·기간의 필수 조건을 확인한다."""
    errors = []
    companies = request.get("companies", [])
    if (
        not isinstance(companies, list)
        or len(companies) != 2
        or any(not isinstance(name, str) or not name.strip() for name in companies)
    ):
        errors.append("비교할 기업 두 곳을 입력해 주세요.")
    elif companies[0].strip().casefold() == companies[1].strip().casefold():
        errors.append("서로 다른 기업 두 곳을 입력해 주세요.")
    question = request.get("question", "")
    if not isinstance(question, str) or not question.strip():
        errors.append("비교하고 싶은 질문을 입력해 주세요.")
    if request.get("sector") not in SECTORS:
        errors.append("분석할 기술 분야를 선택해 주세요.")
    try:
        start = date.fromisoformat(str(request.get("start_date", "")))
        end = date.fromisoformat(str(request.get("end_date", "")))
        if start > end:
            errors.append("시작일은 종료일보다 늦을 수 없습니다.")
    except (TypeError, ValueError):
        errors.append("분석 기간의 시작일과 종료일을 확인해 주세요.")
    return errors


def _evidence() -> list[dict]:
    """실재 문헌으로 오인되지 않는 출처 패널 예시를 만든다."""
    examples = [
        (
            "D-A",
            "가상 A사",
            "사업",
            "설비 모니터링 사업 소개",
            "2025-03-20",
            "사업 소개 · 공급 범위",
            "설비 상태를 한 화면에 모아 점검하고 이상 알림을 제공하는 운영 서비스를 제안한다.",
            "사업 설명 예시입니다. 실제 고객사·매출·도입 실적은 확인하지 않았습니다.",
        ),
        (
            "D-B",
            "가상 B사",
            "사업",
            "유지보수 의사결정 지원 소개",
            "2025-03-25",
            "사업 소개 · 공급 범위",
            "장비별 변화 추이를 분석해 정비 우선순위를 정하는 의사결정 지원 서비스를 제안한다.",
            "사업 설명 예시입니다. 현장 성과나 상용화 여부를 입증하지 않습니다.",
        ),
        (
            "P-A",
            "가상 A사",
            "특허",
            "진동 신호 기반 상태 감지",
            "2024-07-12",
            "가상 특허 · 기술 구성",
            "설비의 진동 신호를 기준 상태와 비교하고, 차이가 설정 범위를 벗어나면 알림을 생성한다.",
            "실재 특허가 아닙니다. 고장 시점 예측이나 제품 적용을 의미하지 않습니다.",
        ),
        (
            "P-B",
            "가상 B사",
            "특허",
            "운전 이력 기반 변화 추이 분석",
            "2024-09-18",
            "가상 특허 · 기술 구성",
            "설비의 전류와 운전 이력을 함께 분석해 상태 변화 추이를 산출하고 점검 순서를 제안한다.",
            "실재 특허가 아닙니다. 가상 A사보다 성능이 우수하다는 근거는 없습니다.",
        ),
        (
            "M-A",
            "가상 A사",
            "시장",
            "설비 운영 담당자 요구 예시",
            "2025-06-10",
            "가상 조사 메모 · 도입 조건",
            "운영 담당자는 기존 센서와의 연결 여부, 알림 발생 시 확인 절차를 도입 조건으로 검토한다.",
            "화면 구성용 가상 메모입니다. 실제 인터뷰나 구매 의사 조사 결과가 아닙니다.",
        ),
        (
            "M-B",
            "가상 B사",
            "시장",
            "정비 계획 담당자 요구 예시",
            "2025-06-10",
            "가상 조사 메모 · 도입 조건",
            "정비 계획 담당자는 운전 이력 확보와 점검 우선순위의 설명 가능성을 도입 조건으로 검토한다.",
            "화면 구성용 가상 메모입니다. 시장 규모·도입 수요를 추정할 수 없습니다.",
        ),
    ]
    return [
        {
            "id": item[0],
            "company": item[1],
            "kind": item[2],
            "title": f"[가상 문헌] {item[3]}",
            "date": item[4],
            "section": item[5],
            "quote": f"[시연용 문장] {item[6]}",
            "limitation": item[7],
        }
        for item in examples
    ]


def build_demo(request: dict, scenario: str = "기본 비교") -> dict:
    """고정 예시만 시연하고 다른 입력에는 분석 미연결 상태를 반환한다."""
    if scenario not in SCENARIOS:
        raise ValueError("지원하지 않는 시연 상태입니다.")
    result = {
        "request": deepcopy(request),
        "status": "unconnected",
        "rows": [],
        "evidence": [],
        "findings": [],
        "unknowns": [],
    }
    errors = validate_request(request)
    if errors:
        result["unknowns"] = errors
        return result
    expected = default_request()
    if any(request.get(key) != value for key, value in expected.items()):
        result["findings"] = [
            "분석 요청을 정리했습니다. 실제 자료 연결 후 비교 결과를 확인할 수 있습니다."
        ]
        result["unknowns"] = [
            "입력한 기업·기간·질문에 대한 실제 검색과 분석은 아직 수행하지 않았습니다.",
            "가상 예시를 입력한 기업의 분석 결과로 대체하지 않습니다.",
        ]
        return result
    if scenario == "검색 결과 없음":
        result["status"] = "no_results"
        result["findings"] = [
            "선택한 범위에서 근거를 찾지 못한 상황을 보여주는 시연입니다."
        ]
        result["unknowns"] = [
            "검색 결과가 없다는 것은 해당 기업의 기술이 존재하지 않는다는 뜻이 아닙니다."
        ]
        return result
    if scenario == "수집 오류":
        result["status"] = "error"
        result["findings"] = ["자료 수집에 실패한 상황을 보여주는 시연입니다."]
        result["unknowns"] = [
            "수집 실패를 검색 결과 없음으로 처리하지 않습니다. 연결 상태를 확인한 뒤 다시 요청합니다."
        ]
        return result
    result.update(
        status="demo",
        rows=[
            {
                "label": "사업 방향",
                "a": "설비 상태 모니터링과 이상 알림",
                "b": "상태 변화 분석과 정비 우선순위 지원",
                "citations": ["D-A", "D-B"],
            },
            {
                "label": "기술 접근",
                "a": "진동 신호를 기준 상태와 비교",
                "b": "전류·운전 이력의 변화 추이 분석",
                "citations": ["P-A", "P-B"],
            },
            {
                "label": "도입 조건",
                "a": "기존 센서 연계와 알림 확인 절차",
                "b": "운전 이력 확보와 결과 설명 가능성",
                "citations": ["M-A", "M-B"],
            },
        ],
        evidence=_evidence(),
        findings=[
            "가상 A사는 현재 상태의 확인과 알림에, 가상 B사는 변화 추이와 정비 계획에 초점을 둡니다.",
            "두 방식은 입력 데이터와 활용 목적이 다릅니다. 기술의 우열은 이 자료만으로 판단하지 않습니다.",
        ],
        unknowns=[
            "특허에 나타난 기술이 실제 판매 제품에 적용되는지는 추가 확인이 필요합니다.",
            "고객사 도입 사례·정확도·고장률 개선 실적은 확인하지 않았습니다.",
            "공시·제품자료와 특허의 관계는 원문과 시점을 맞춰 검토해야 합니다.",
        ],
    )
    if scenario == "일부 자료 없음":
        result["status"] = "partial"
        result["evidence"] = [e for e in result["evidence"] if e["kind"] != "시장"]
        result["rows"][-1] = {
            "label": "도입 조건",
            "a": "미확인 · 시장 자료 없음",
            "b": "미확인 · 시장 자료 없음",
            "citations": [],
        }
        result["unknowns"].insert(
            0,
            "시장 자료를 확보하지 못한 상황의 시연입니다. 사업·기술 근거만 표시합니다.",
        )
    return result


def report_markdown(result: dict) -> str:
    """화면과 같은 범위·근거·미확인 사항을 시연 표시와 함께 내보낸다."""
    request = result["request"]
    lines = [
        "# 스마트팩토리 기업 비교 · 시연 보고서",
        "",
        "> 시연용 데이터입니다. 실제 특허·공시·시장 검색 및 AI 분석을 수행하지 않았습니다.",
        "",
        "## 조사 범위",
        f"- 기업: {' / '.join(request.get('companies', []))}",
        f"- 기업 역할: {request.get('role', '')}",
        f"- 기술 분야: {request.get('sector', '')}",
        f"- 기간: {request.get('start_date', '')} ~ {request.get('end_date', '')}",
        f"- 비교 질문: {request.get('question', '')}",
        f"- 화면 상태: {result['status']}",
        "",
        "## 비교 결과",
        "",
    ]
    if result["rows"]:
        for row in result["rows"]:
            lines.extend(
                [
                    f"### {row['label']}",
                    f"- 가상 A사: {row['a']}",
                    f"- 가상 B사: {row['b']}",
                    f"- 근거: {', '.join(row['citations']) or '미확인'}",
                    "",
                ]
            )
    else:
        lines.extend(["표시할 분석 결과가 없습니다.", ""])
    lines.extend(["## 핵심 요약", *[f"- {item}" for item in result["findings"]], ""])
    lines.extend(["## 가상 문헌 근거", ""])
    for evidence in result["evidence"]:
        lines.extend(
            [
                f"### {evidence['id']} · {evidence['title']}",
                f"- 기업·유형: {evidence['company']} · {evidence['kind']}",
                f"- 예시 날짜·위치: {evidence['date']} · {evidence['section']}",
                f"> {evidence['quote']}",
                f"- 확인 범위: {evidence['limitation']}",
                "",
            ]
        )
    lines.extend(
        ["## 미확인 사항과 다음 조사", *[f"- {item}" for item in result["unknowns"]]]
    )
    return "\n".join(lines)
