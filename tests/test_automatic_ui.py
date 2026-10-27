"""자동 시연 판단의 적용 범위와 팀 보고서 인용 경계를 검증한다."""

from copy import deepcopy
import pytest
from pydantic import ValidationError
from frontend.automatic import automatic_links, report_evidence, CRITERIA
from frontend.quick import DEMO_TEXT, DEMO_PARTS, DEMO_QUESTIONS, report

IDS = ["M1", "M2", "P1", "P2"]


def test_demo_results_include_criteria_and_keep_uncertainty():
    links = automatic_links(DEMO_TEXT, DEMO_PARTS, IDS, DEMO_QUESTIONS)
    assert links["Q2"]["relation"] == "해결 방식 관련"
    for link in links.values():
        assert link["origin"] == "demo_rule"
        assert [x["criterion"] for x in link["assessment"]] == CRITERIA
        assert all(set(x["source_ids"]) <= set(IDS) for x in link["assessment"])
    output = report(DEMO_TEXT, "검토", DEMO_PARTS, IDS, "", DEMO_QUESTIONS, links)
    assert "시연 자동 초안" in output
    assert all(c in output for c in CRITERIA)


@pytest.mark.parametrize("change", ["text", "parts", "question", "condition"])
def test_changed_inputs_cannot_reuse_preset_judgment(change):
    text, parts, questions = DEMO_TEXT, list(DEMO_PARTS), deepcopy(DEMO_QUESTIONS)
    if change == "text":
        text += " 다른 상황"
    elif change == "parts":
        parts[0] += " 변경"
    else:
        questions[0][change] += " 변경"
    link = automatic_links(text, parts, IDS, questions)["Q1"]
    assert link["origin"] == "automatic_pending"
    assert not link["market_ids"] and not link["patent_ids"]


def test_removed_evidence_does_not_survive_automatic_judgment():
    link = automatic_links(DEMO_TEXT, DEMO_PARTS, ["M1", "M2", "P2"], DEMO_QUESTIONS)[
        "Q2"
    ]
    assert link["patent_ids"] == []
    assert link["relation"] == "연결 판단 보류"
    assert all("P1" not in x["source_ids"] for x in link["assessment"])


def reports():
    market = dict(
        status="completed",
        search_scope="시장 범위",
        evidence=[
            dict(
                citation_id=1,
                source_id="SRC-1",
                source_type="news",
                title="시장 문헌",
                publisher="발행 기관",
                quote="원문 인용",
                published_at=20260502,
                reliability="medium",
                recency="high",
                directness="low",
                evidence_nature="business_signal",
            )
        ],
    )
    patent = dict(
        status="completed",
        search_scope="특허 범위",
        evidence=[
            dict(
                citation_id=1,
                patent_id="KR-DEMO",
                title="기술 문헌",
                section="abstract",
                quote="기술 인용",
            )
        ],
    )
    return market, patent


def test_team_reports_preserve_namespaced_citations_and_unknowns():
    market, patent = reports()
    result = report_evidence(market, patent)
    assert [r["id"] for r in result["evidence"]] == ["M:1", "P:1"]
    assert result["evidence"][0]["quote"] == "원문 인용"
    assert result["evidence"][0]["published_at"] == 20260502
    assert result["evidence"][1]["period"] == "미확인"
    assert result["market_scope"] == "시장 범위"


def test_invalid_team_citation_is_rejected():
    market, patent = reports()
    patent["comparisons"] = [
        dict(citation_id=2, similarity="유사", difference="차이", uncertainty="미확인")
    ]
    with pytest.raises(ValidationError):
        report_evidence(market, patent)


@pytest.mark.parametrize("status", ["no_results", "error"])
def test_non_completed_reports_do_not_create_results(status):
    market, patent = reports()
    market["status"] = patent["status"] = status
    market["evidence"] = patent["evidence"] = []
    if status == "error":
        market["error_message"] = patent["error_message"] = "Search failed"
    assert report_evidence(market, patent)["evidence"] == []
