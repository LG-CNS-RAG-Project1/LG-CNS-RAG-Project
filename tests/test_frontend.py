"""가상 근거의 오인 방지와 비교 화면의 주요 흐름을 확인한다."""

import pytest

from frontend.demo import build_demo, default_request, report_markdown, validate_request


@pytest.mark.parametrize(
    "change",
    [
        {"companies": ["", "가상 B사"]},
        {"companies": ["같은 기업", " 같은 기업 "]},
        {"question": "  "},
        {"start_date": "2027-01-01"},
        {"end_date": "잘못된 날짜"},
    ],
)
def test_invalid_request_has_no_claims(change):
    request = default_request() | change
    assert validate_request(request)
    result = build_demo(request)
    assert result["status"] == "unconnected"
    assert not result["evidence"]
    assert not result["rows"]


@pytest.mark.parametrize(
    "change",
    [
        {"companies": ["실제 입력 기업", "가상 B사"]},
        {"sector": "품질 검사"},
        {"question": "실제 제품 적용은?"},
        {"start_date": "2025-01-01"},
        {"role": "도입 제조기업"},
    ],
)
def test_fixture_is_never_relabelled_as_custom_analysis(change):
    request = default_request() | change
    result = build_demo(request)
    assert not validate_request(request)
    assert result["status"] == "unconnected"
    assert not result["rows"] and not result["evidence"]
    assert result["request"] == request


def test_demo_citations_are_complete_and_report_is_labelled():
    request = default_request()
    result = build_demo(request)
    ids = {item["id"] for item in result["evidence"]}
    assert ids == {"D-A", "D-B", "P-A", "P-B", "M-A", "M-B"}
    assert all(set(row["citations"]) <= ids for row in result["rows"])
    assert all("가상 문헌" in item["title"] for item in result["evidence"])
    assert all("시연용 문장" in item["quote"] for item in result["evidence"])
    assert all("source_url" not in item for item in result["evidence"])
    request["companies"][0] = "변경된 기업"
    assert result["request"]["companies"][0] == "가상 A사"
    report = report_markdown(result)
    assert "시연용 데이터" in report and "실제 특허·공시·시장 검색" in report
    assert all(e["quote"] in report for e in result["evidence"])
    assert all(item in report for item in result["unknowns"])
    assert "2024-01-01 ~ 2026-10-22" in report


def test_partial_data_removes_market_claims_and_citations():
    result = build_demo(default_request(), "일부 자료 없음")
    assert result["status"] == "partial"
    assert all(e["kind"] != "시장" for e in result["evidence"])
    market = result["rows"][-1]
    assert "미확인" in market["a"] and "미확인" in market["b"]
    assert not market["citations"]


@pytest.mark.parametrize(
    "scenario,status", [("검색 결과 없음", "no_results"), ("수집 오류", "error")]
)
def test_no_results_and_collection_error_remain_distinct(scenario, status):
    result = build_demo(default_request(), scenario)
    assert result["status"] == status
    assert not result["rows"] and not result["evidence"]
    assert result["unknowns"]
