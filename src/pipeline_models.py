"""파이프라인 준비 상태와 분석 결과의 데이터 계약."""

from typing import Literal

from pydantic import BaseModel, Field
from src.generation.business_review import BusinessReview
from src.generation.business_canvas import BusinessCanvas
from src.generation.swot import SwotAnalysis
from src.generation.executive_models import ExecutiveReview
from src.generation.question_links import QuestionLink
from src.schemas import (
    CostScenarioTotals,
    ImplementationCostEstimate,
    MarketReport,
    PatentReport,
)

RunState = Literal["completed", "partial", "no_results", "error", "skipped", "timeout"]


class IndexState(BaseModel):
    """선택한 색인의 위치·컬렉션·건수와 확인 실패 이유."""

    location: Literal["local", "remote"]
    collection: str
    count: int | None = None  # None이면 열지 못함(reason 참고)
    area_counts: dict[str, int] = Field(default_factory=dict)
    reason: str | None = None


class Readiness(BaseModel):
    """외부 키 설정과 시장·특허 색인의 실행 준비 요약."""

    keys: dict[str, bool]  # 인증 정보와 provider 설정 여부. 실제 값은 담지 않는다
    chroma: Literal["local", "remote"]
    market_index: IndexState
    patent_index: IndexState
    market_runnable: bool
    patent_mode: Literal["local+kipris", "kipris_only", "local_only", "none"]
    market_collected_at: int | None = None
    reasons: list[str] = Field(default_factory=list)


class PartRun(BaseModel):
    """한 분석 영역의 상태, 소요 시간, 사용자용 오류 안내."""

    state: RunState
    seconds: float | None = None
    message: str | None = None


class SourceAnalysis(BaseModel):
    """시장·특허 조사 결과. 질문만 바뀌면 이 결과를 재사용해 연결만 다시 만든다."""

    patent: PatentReport
    market: MarketReport
    patent_run: PartRun
    market_run: PartRun
    readiness: Readiness | None = None
    analyzed_on: int
    total_seconds: float


class PipelineReport(BaseModel):
    """특허·시장 분석을 통합한 화면·저장용 최종 보고서."""

    status: str
    title: str
    patent: PatentReport
    market: MarketReport
    links: list[QuestionLink] = Field(default_factory=list)
    markdown: str = ""
    business_review: BusinessReview | None = None
    executive_review: ExecutiveReview | None = None
    swot: SwotAnalysis | None = None
    canvas: BusinessCanvas | None = None
    errors: list[str] = Field(default_factory=list)
    patent_run: PartRun | None = None
    market_run: PartRun | None = None
    readiness: Readiness | None = None
    analyzed_on: int | None = None
    cost_estimate: ImplementationCostEstimate | None = None
    cost_totals: CostScenarioTotals | None = None


class Cancelled(RuntimeError):
    """영역 제한 시간이 지난 뒤 새 외부 호출을 막을 때 낸다."""
