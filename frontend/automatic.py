"""자동 연결 화면의 시연 규칙과 팀 결과 모델의 경계 변환.

시연 규칙은 정확히 일치하는 예시만 처리한다. 실제 의미 분석을 대신하지 않는다.
"""

from frontend.quick import DEMO_TEXT, DEMO_PARTS, DEMO_QUESTIONS, candidates
from src.schemas import MarketReport, PatentReport

CRITERIA = [
    "사용 맥락",
    "해결 과제",
    "기술 구성",
    "요구 성능",
    "도입 제약",
    "근거 범위",
]


def report_evidence(market_payload, patent_payload):
    """팀의 인용 검증 모델을 통과한 근거를 영역별 식별자로 변환한다."""
    market = MarketReport.model_validate(market_payload)
    patent = PatentReport.model_validate(patent_payload)
    rows = []
    if market.status == "completed":
        for e in market.evidence:
            rows.append(
                dict(
                    id=f"M:{e.citation_id}",
                    kind="시장",
                    title=e.title,
                    quote=e.quote,
                    location=e.section or "미확인",
                    entity=e.publisher,
                    period=e.period or "미확인",
                    published_at=e.published_at,
                    source_url=e.url,
                    version="미확인",
                    limit="실제 고객 수요·제품 적용은 별도 검증",
                    native_id=e.source_id,
                    nature=e.evidence_nature,
                )
            )
    if patent.status in {"completed", "partial"}:
        for e in patent.evidence:
            rows.append(
                dict(
                    id=f"P:{e.citation_id}",
                    kind="특허",
                    title=e.title,
                    quote=e.quote,
                    location=e.section,
                    entity="출원인·제품 연결 미확인",
                    period="미확인",
                    published_at=None,
                    source_url=e.source_url,
                    version="미확인",
                    limit="특허 기재가 제품 성능·사업성을 검증하지 않음",
                    native_id=e.patent_id,
                    nature="기술 문헌",
                )
            )
    return {
        "evidence": rows,
        "market_status": market.status,
        "patent_status": patent.status,
        "market_scope": market.search_scope,
        "patent_scope": patent.search_scope,
    }


def automatic_links(text, parts, selected, questions):
    """사전 작성 예시를 자동 배치하고 변경된 입력에는 판단 보류를 반환한다."""
    available = {s["id"]: s for s in candidates(text) if s["id"] in selected}
    links = {}
    for q in questions:
        link = dict(
            question_id=q["id"],
            component_ids=[],
            market_ids=[],
            patent_ids=[],
            relation="연결 판단 보류",
            reason="실제 연결 분석 모듈이 미연결이므로 이 질문의 의미 관계를 판정하지 않았습니다.",
            conditions="사용 환경·성능·도입 조건과 원문 범위를 확인해야 합니다.",
            counter_ids=[],
            counter_reason="반대 근거는 아직 조사하지 않았습니다.",
            next_check="시장·특허 분석 결과와 연결 판단 모듈 연결",
            origin="automatic_pending",
            assessment=[
                {
                    "criterion": c,
                    "result": "미확인",
                    "reason": "실제 분석 미연결",
                    "source_ids": [],
                }
                for c in CRITERIA
            ],
        )
        matching = next(
            (
                i
                for i, x in enumerate(DEMO_QUESTIONS)
                if x["question"] == q["question"] and x["condition"] == q["condition"]
            ),
            None,
        )
        if text == DEMO_TEXT and parts == DEMO_PARTS and matching is not None:
            market_id, patent_id = ("M1", "P2") if matching == 0 else ("M2", "P1")
            link.update(
                origin="demo_rule",
                market_ids=[market_id] if market_id in available else [],
                patent_ids=[patent_id] if patent_id in available else [],
                component_ids=["C3"] if matching == 0 else ["C1", "C2"],
                relation="연결 판단 보류" if matching == 0 else "해결 방식 관련",
                reason=(
                    "시장 예시는 설치 중단 시간의 확인 필요성을 언급하지만 특허 예시의 조명 제어 문장에는 설치 방식·시간이 없습니다. 설치 부담 충족 여부는 판단 보류합니다."
                    if matching == 0
                    else "가상 기업 자료의 카메라·조명 구성과 특허의 영상 비교 방식은 사용자 기술 구성과 관련됩니다. 그러나 고객의 요구 성능과 동일 조건 시험값은 없어 성능 충족 여부는 판단 보류합니다."
                ),
                counter_reason=(
                    "설치 시간이 짧다는 주장이나 실제 연동 실험은 확보하지 않았습니다."
                    if matching == 0
                    else "기업 자체 설명과 특허의 기술 설명뿐이며 고객 구매 의사·성능 검증은 없습니다."
                ),
                next_check=(
                    "설치 시간·장착 방식·설비 연동 견적 확인"
                    if matching == 0
                    else "목표 불량 유형과 동일 조건의 오탐·미탐 시험 확보"
                ),
            )
            link["assessment"] = [
                {
                    "criterion": "사용 맥락",
                    "result": "부분 관련",
                    "reason": "사용자 제조라인 설명과 가상 자료를 대조한 예시 규칙",
                    "source_ids": [market_id] if market_id in available else [],
                },
                {
                    "criterion": "해결 과제",
                    "result": "추가 확인",
                    "reason": "예시의 과제 관련성이 실제 고객 수요 검증을 뜻하지 않음",
                    "source_ids": link["market_ids"],
                },
                {
                    "criterion": "기술 구성",
                    "result": "일부 관련" if matching == 1 else "정보 부족",
                    "reason": "영상 비교와 촬영 구성은 관련될 수 있으나 설치 구조를 입증하지 않음",
                    "source_ids": link["patent_ids"],
                },
                {
                    "criterion": "요구 성능",
                    "result": "미확인",
                    "reason": "동일 조건의 성능 측정값 없음",
                    "source_ids": [],
                },
                {
                    "criterion": "도입 제약",
                    "result": "미확인",
                    "reason": "설치·운영 조건과 비용 검증 없음",
                    "source_ids": link["market_ids"],
                },
                {
                    "criterion": "근거 범위",
                    "result": "검증 불가",
                    "reason": "가상 자료이며 실제 기업·시점·원문 URL 미확인",
                    "source_ids": list(
                        dict.fromkeys(link["market_ids"] + link["patent_ids"])
                    ),
                },
            ]
            if not link["market_ids"] or not link["patent_ids"]:
                link.update(
                    relation="연결 판단 보류",
                    reason="이 질문에 대응하는 시장·특허 예시 중 한쪽이 제외돼 통합 판단을 보류합니다.",
                )
        links[q["id"]] = link
    return links
