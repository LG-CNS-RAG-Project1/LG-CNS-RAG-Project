import pytest
from pydantic import ValidationError

from src.schemas import (
    PatentReport,
    PatentEvidence,
    PatentComparison,
)


def test_valid_patent_report():
    report = PatentReport(
        status="completed",
        search_scope="스마트팩토리 사전 수집 특허",
        evidence=[
            PatentEvidence(
                citation_id=1,
                patent_id="sample-1",
                title="테스트용 가상 특허",
                section="abstract",
                quote="설비 진동 데이터를 분석한다.",
            )
        ],
        comparisons=[
            PatentComparison(
                citation_id=1,
                similarity="진동 데이터 분석",
                difference="예측 방식은 확인 필요",
                uncertainty="청구항 미확보",
            )
        ],
    )

    assert report.status == "completed"
    assert len(report.evidence) == 1


def test_invalid_citation():
    with pytest.raises(ValidationError):
        PatentReport(
            status="completed",
            search_scope="테스트",
            evidence=[],
            comparisons=[
                PatentComparison(
                    citation_id=99,
                    similarity="유사점",
                    difference="차이점",
                    uncertainty="미확인",
                )
            ],
        )


def test_no_results():
    report = PatentReport(
        status="no_results",
        search_scope="스마트팩토리 특허",
    )

    assert report.evidence == []
    assert report.comparisons == []
