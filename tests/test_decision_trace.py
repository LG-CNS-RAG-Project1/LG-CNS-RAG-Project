"""판단별 인용을 분리하고 기록 복원 뒤에도 원문 연결을 유지한다."""

import json

from streamlit.testing.v1 import AppTest

from frontend.decision_trace import DecisionTrace, decision_trace
from frontend.workspace_view import validate_records
from src.pipeline import PipelineReport
from src.schemas import MarketEvidence, MarketReport, PatentEvidence, PatentReport
from src.generation.executive_review import ExecutiveReview, IntegratedFinding


def trace():
    result = PipelineReport(
        status="partial",
        title="검토",
        patent=PatentReport(
            status="completed",
            search_scope="test",
            evidence=[
                PatentEvidence(
                    citation_id=1,
                    patent_id="p1",
                    title="센서 특허",
                    section="abstract",
                    quote="센서의 진동을 분석한다.",
                    source_url="https://example.com/p1",
                )
            ],
        ),
        market=MarketReport(
            status="completed",
            search_scope="test",
            evidence=[
                MarketEvidence(
                    citation_id=1,
                    source_id="dart:corp1:2025",
                    source_type="dart",
                    title="사업의 내용",
                    publisher="공시기업",
                    quote="사업보고서 발췌 문장",
                    section="II. 사업의 내용",
                    published_at=20260331,
                    period="FY2025",
                    reliability="medium",
                    recency="medium",
                    directness="low",
                    evidence_nature="company_claim",
                )
            ],
        ),
        executive_review=ExecutiveReview(
            recommendation="research_more",
            scope="추가 확인",
            confidence="low",
            decision_summary="시장 근거 보완",
            integrated_findings=[
                IntegratedFinding(
                    label="기술",
                    judgment="구성 대조 필요",
                    business_implication="추가 검색",
                    evidence_ids=["P:1", "M:1"],
                    kind="interpretation",
                )
            ],
        ),
    )
    return decision_trace(result)


def test_trace_preserves_missing_reference_without_linking_wrong_source():
    data = DecisionTrace.model_validate(trace())
    assert data.findings[0].refs == ["P:1", "M:1"]
    assert [s.ref for s in data.sources] == ["P:1", "M:1"]
    assert data.sources[0].quote == "센서의 진동을 분석한다."
    assert "DART 사업보고서" in data.sources[1].location
    assert "공시기업" in data.sources[1].location
    assert "FY2025" in data.sources[1].location
    assert "II. 사업의 내용" in data.sources[1].location


def test_trace_drilldown_handles_missing_original():
    data = trace()
    data["sources"] = [source for source in data["sources"] if source["ref"] != "M:1"]
    app = AppTest.from_string(
        "from frontend.decision_trace import render_decision_trace\n"
        f"render_decision_trace({data!r})"
    ).run()
    assert not app.exception
    assert app.text[0].value == "센서의 진동을 분석한다."
    app.selectbox(key="trace_source_0").select("M:1").run()
    assert not app.exception
    assert any("원문이 현재 결과에 없습니다" in x.value for x in app.warning)
    assert not app.text


def test_history_trace_roundtrip_remains_optional_for_older_records():
    item = dict(
        title="검토",
        raw="입력",
        markdown="결과",
        appendix="",
        saved_at="test",
        id="1",
        demo=False,
        rows=[],
        patent_count=1,
        market_count=0,
        decision_trace=trace(),
    )
    raw = json.dumps(dict(format="idealens-records-v1", records=[item])).encode()
    assert validate_records(raw)[0]["decision_trace"] == trace()
    item.pop("decision_trace")
    raw = json.dumps(dict(format="idealens-records-v1", records=[item])).encode()
    assert validate_records(raw)[0] == item
