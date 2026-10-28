"""완성된 아이디어를 특허·시장 조사와 근거 연결 보고서로 실행한다."""

from pydantic import BaseModel, Field

from src.generation.idea_parser import build_requests
from src.generation.report_builder import (
    QuestionLink,
    build_question_links,
    integrated_report_markdown,
)
from src.schemas import IdeaDraft, MarketReport, PatentReport
from src.services.market_service import run_market_research
from src.services.patent_service import analyze_patents


class PipelineReport(BaseModel):
    status: str
    title: str
    patent: PatentReport
    market: MarketReport
    links: list[QuestionLink] = Field(default_factory=list)
    markdown: str = ""
    errors: list[str] = Field(default_factory=list)


def run_pipeline(
    draft: IdeaDraft,
    questions: list[dict],
    *,
    technical_components: list[str] | None = None,
    technology_area_id: str | None = None,
    patent_kwargs: dict | None = None,
    market_kwargs: dict | None = None,
    link_llm_fn=None,
) -> PipelineReport:
    """확정된 IdeaDraft로 두 조사와 질문별 통합 근거 보고서를 실행한다."""
    patent_request, market_request = build_requests(draft)
    patent_request.technology_area_id = technology_area_id
    if technical_components is not None:
        patent_request.idea.technical_components = technical_components
        market_request.idea.technical_components = technical_components
    patent_kwargs = patent_kwargs or {}
    market_kwargs = market_kwargs or {}
    patent = analyze_patents(patent_request, **patent_kwargs)
    market = run_market_research(market_request, **market_kwargs)
    errors = []
    links = []
    try:
        links = build_question_links(questions, market, patent, llm_fn=link_llm_fn)
    except Exception as exc:
        errors.append(f"검토 질문 연결 생성 실패: {exc}")
        links = [
            QuestionLink(
                question_id=item["id"],
                status="hold",
                summary="질문별 연결 결과를 생성하지 못해 판단을 보류합니다.",
                criteria=[
                    {
                        "criterion": criterion,
                        "assessment": "미확인",
                        "citation_ids": [],
                        "next_check": "시장·특허 근거 연결을 다시 실행",
                    }
                    for criterion in [
                        "사용 맥락",
                        "해결 과제",
                        "기술 구성",
                        "요구 성능",
                        "도입 제약",
                        "근거 범위",
                    ]
                ],
            )
            for item in questions
        ]
    markdown = integrated_report_markdown(draft.title, questions, links, market, patent)
    statuses = {patent.status, market.status}
    status = "completed" if statuses == {"completed"} and not errors else "partial"
    return PipelineReport(
        status=status,
        title=draft.title,
        patent=patent,
        market=market,
        links=links,
        markdown=markdown,
        errors=errors,
    )
