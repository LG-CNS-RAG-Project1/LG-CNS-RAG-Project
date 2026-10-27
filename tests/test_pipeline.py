from src.generation.report_builder import CRITERIA, build_question_links
from src.pipeline import run_pipeline
from src.schemas import IdeaDraft, MarketReport, PatentReport


def link_response(question_id="Q1"):
    return {
        "links": [
            {
                "question_id": question_id,
                "status": "connected",
                "summary": "양쪽 근거 확인",
                "criteria": [
                    {
                        "criterion": criterion,
                        "assessment": "근거 일부 확인",
                        "citation_ids": [],
                        "next_check": "실제 적용 조건 확인",
                    }
                    for criterion in CRITERIA
                ],
            }
        ]
    }


def test_question_link_holds_when_one_evidence_domain_is_missing():
    market = MarketReport(status="no_results", search_scope="none")
    patent = PatentReport(status="no_results", search_scope="none")
    links = build_question_links(
        [{"id": "Q1", "question": "검토 질문", "condition": ""}],
        market,
        patent,
        llm_fn=lambda *_: link_response(),
    )
    assert links[0].status == "hold"
    assert len(links[0].criteria) == 6


def test_pipeline_uses_both_service_contracts_and_returns_markdown(monkeypatch):
    import src.pipeline as pipeline

    monkeypatch.setattr(
        pipeline,
        "analyze_patents",
        lambda request, **kwargs: PatentReport(status="no_results", search_scope="patent"),
    )
    monkeypatch.setattr(
        pipeline,
        "run_market_research",
        lambda request, **kwargs: MarketReport(status="no_results", search_scope="market"),
    )
    draft = IdeaDraft(
        original_text="공장 검사 자동화 아이디어",
        title="검사 자동화",
        problem="검사 부담",
        technology="AI 비전 검사",
        customers="제조사",
        difference="자동 분류",
        revenue="장비 공급",
        status="complete",
    )
    result = run_pipeline(
        draft,
        [{"id": "Q1", "question": "기술 구성이 문제를 해결하는가?", "condition": "현장 확인"}],
        technology_area_id="SF-02",
        link_llm_fn=lambda *_: link_response(),
    )
    assert result.status == "partial"
    assert result.links[0].status == "hold"
    assert "# 검사 자동화" in result.markdown
