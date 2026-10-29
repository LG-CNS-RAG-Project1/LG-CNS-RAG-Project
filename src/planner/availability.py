"""후속 도표(고객·공정 후보, 같은 사례 진행 이력, 가격·성과 점도표)의 표시 가능 여부.

필수 데이터가 없으면 도표를 그리지 않고 누락 항목과 확보 방법(질문 ID·질의·회사 입력)을 반환한다.
"""

from collections import defaultdict

from src.planner.schemas import ChartAvailability, Edge, Evidence


def case_events(edges: list[Edge]) -> dict[tuple, list[Edge]]:
    """같은 공급사·같은 실명 상대의 승인 관계를 묶는다(익명·계열은 제외)."""
    cases = defaultdict(list)
    for edge in edges:
        if (
            edge.status == "approved"
            and edge.counterpart_kind == "named"
            and not edge.affiliate
        ):
            cases[(edge.supplier_id, edge.counterpart_id)].append(edge)
    return cases


def check_followup_charts(
    edges: list[Edge], evidence: list[Evidence]
) -> list[ChartAvailability]:
    results = [
        ChartAvailability(
            chart_id="segment_candidates",
            label="고객·공정 후보 비교표",
            available=False,
            missing=[
                "기사별 공정·검사 대상·결함의 확정 추출(현재 규칙 미구현)",
                "당사 고객 접근성·데이터 접근·수행 역량(회사 입력)",
            ],
            how_to_obtain=[
                "M1·M2 질의로 공정·검사 대상이 명시된 도입 기사 확보",
                "M4: 접근 가능한 고객·데이터·현장 수행 역량을 회사가 입력",
            ],
            question_ids=["M1", "M2", "M4"],
        )
    ]
    timelines = [
        events
        for events in case_events(edges).values()
        if len({e.relation_type for e in events}) >= 2
        and all(e.event_at for e in events)
    ]
    results.append(
        ChartAvailability(
            chart_id="case_timeline",
            label="같은 사례 진행 이력도",
            available=bool(timelines),
            missing=(
                []
                if timelines
                else [
                    "같은 공급사·같은 실명 고객의 서로 다른 단계 사건 2건 이상",
                    "각 사건의 사건일(발행일과 별도)",
                ]
            ),
            how_to_obtain=(
                []
                if timelines
                else [
                    "D4: '{고객} {제품} 운영 추가 발주' 질의로 후속 단계 확인",
                    "T1: 기사 본문에서 실제 사건일 확인",
                ]
            ),
            question_ids=["D4", "T1"],
        )
    )
    prices = defaultdict(list)
    for item in evidence:
        if item.kind != "metric" or item.review_status != "approved":
            continue
        if "price" not in item.markers:
            continue
        unit = next((m for m in item.markers if m.startswith("sales_unit:")), "")
        if (
            unit
            and "price_scope" in item.markers
            and "reviewer_approved" in item.reasons
        ):
            prices[unit].append(item)
    comparable = [items for items in prices.values() if len(items) >= 2]
    results.append(
        ChartAvailability(
            chart_id="price_dotplot",
            label="비교 조건이 같은 가격·성과 점도표",
            available=bool(comparable),
            missing=(
                []
                if comparable
                else [
                    "판매 단위·포함 범위를 검토자가 확인한 같은 조건의 가격 수치 2건 이상",
                    "통화·수량·기간·설치/유지보수 포함 여부",
                ]
            ),
            how_to_obtain=(
                []
                if comparable
                else [
                    "E1·E2 질의로 판매 단위와 포함 범위가 명시된 가격 기사 확보",
                    "가격 근거가 같은 판매 단위·범위인지 검토해 승인(review)",
                    "장비 가격과 프로젝트 계약 총액은 같은 축에 두지 않음",
                ]
            ),
            question_ids=["E1", "E2"],
        )
    )
    return results
