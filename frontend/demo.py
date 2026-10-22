"""API를 호출하지 않는 화면 검증용 예시 결과."""

from src.schemas import PatentEvidence, PatentReport, StructuredIdea


def build_demo(idea: StructuredIdea) -> dict:
    """사용자 입력과 명확히 구분되는 가상 근거를 반환한다."""
    patent = PatentReport(
        status="completed",
        search_scope="가상 문헌 1건 · 실제 KIPRIS 검색 미수행",
        evidence=[
            PatentEvidence(
                citation_id=1,
                patent_id="DEMO-001",
                title="[가상 문헌] 센서 기반 설비 상태 모니터링",
                section="abstract",
                quote="[시연용 문장] 센서에서 측정한 신호를 기준 상태와 비교한다.",
            )
        ],
        unknowns=["실제 선행특허, 청구항 및 권리 상태를 확인해야 합니다."],
    )
    return {"idea": idea.model_dump(), "patent": patent.model_dump()}


def report_markdown(result: dict) -> str:
    """다운로드에도 시연 표시와 검증 한계를 유지한다."""
    idea = StructuredIdea.model_validate(result["idea"])
    patent = PatentReport.model_validate(result["patent"])
    return "\n".join(
        [
            "# IdeaLens 시연 보고서",
            "",
            "> 시연용 데이터입니다. 실제 특허·시장 검색 및 AI 분석을 수행하지 않았습니다.",
            "",
            "## 사용자 입력 (검증되지 않은 설명)",
            f"- 제목: {idea.title}",
            f"- 해결할 문제: {idea.problem}",
            f"- 기술·해결 방식: {idea.technology}",
            f"- 대상 고객: {idea.customers}",
            "",
            "## 가상 특허 근거",
            *[f"- {e.patent_id} / {e.title}: {e.quote}" for e in patent.evidence],
            "",
            "## 미확인 사항과 다음 검증",
            *[f"- {item}" for item in patent.unknowns],
            "- 시장 자료 미연결: 실제 고객의 구매 의사와 도입 조건을 확인해야 합니다.",
            "- 특허 유사성만으로 등록 가능성·침해 여부·사업성을 판단하지 않습니다.",
        ]
    )
