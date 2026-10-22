from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from src.ingestion.kipris_client import (
    KiprisAPIError,
    search_patents,
)
from src.schemas import (
    PatentReport,
    PatentEvidence,
    PatentComparison,
)

# ============================================================
# KIPRIS PLUS API 테스트
# ============================================================

SAMPLE_XML = """
<response>
    <header>
        <resultCode>00</resultCode>
        <resultMsg>success</resultMsg>
    </header>
    <body>
        <PatentUtilityInfo>
            <ApplicationNumber>1020230030067</ApplicationNumber>
            <InventionName>스마트팩토리 안전 시스템</InventionName>
            <Abstract>협동로봇의 안전거리를 분석한다.</Abstract>
            <Applicant>테스트 기업</Applicant>
        </PatentUtilityInfo>
    </body>
</response>
"""


class TestKiprisClient:
    """KIPRIS Plus API 테스트"""

    @patch("src.ingestion.kipris_client.requests.get")
    @patch.dict(
        "os.environ",
        {"KIPRIS_API_KEY": "test-key"},
    )
    def test_search_success(self, mock_get):
        response = Mock()
        response.content = SAMPLE_XML.encode("utf-8")
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        patents = search_patents("스마트팩토리", limit=3)

        assert len(patents) == 1
        assert patents[0]["application_number"] == "1020230030067"
        assert patents[0]["title"] == "스마트팩토리 안전 시스템"
        assert patents[0]["abstract"] == "협동로봇의 안전거리를 분석한다."
        assert patents[0]["applicant"] == "테스트 기업"

        mock_get.assert_called_once()

    def test_empty_keyword(self):
        with pytest.raises(ValueError):
            search_patents("")

    def test_invalid_limit(self):
        with pytest.raises(ValueError):
            search_patents("스마트팩토리", limit=0)

    @patch("src.ingestion.kipris_client.requests.get")
    @patch.dict(
        "os.environ",
        {"KIPRIS_API_KEY": "test-key"},
    )
    def test_api_error(self, mock_get):
        response = Mock()
        response.content = b"""
        <response>
            <resultCode>31</resultCode>
            <resultMsg>DEADLINE_HAS_EXPIRED_ERROR</resultMsg>
        </response>
        """
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        with pytest.raises(KiprisAPIError):
            search_patents("스마트팩토리")

    @patch("src.ingestion.kipris_client.requests.get")
    @patch.dict(
        "os.environ",
        {"KIPRIS_API_KEY": "test-key"},
    )
    def test_duplicate_patents(self, mock_get):
        duplicated_xml = """
        <response>
            <resultCode>00</resultCode>
            <resultMsg>success</resultMsg>
            <PatentUtilityInfo>
                <ApplicationNumber>12345</ApplicationNumber>
                <InventionName>특허 A</InventionName>
            </PatentUtilityInfo>
            <PatentUtilityInfo>
                <ApplicationNumber>12345</ApplicationNumber>
                <InventionName>특허 A</InventionName>
            </PatentUtilityInfo>
        </response>
        """

        response = Mock()
        response.content = duplicated_xml.encode("utf-8")
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        patents = search_patents("스마트팩토리")

        assert len(patents) == 1
        assert patents[0]["application_number"] == "12345"

    @patch("src.ingestion.kipris_client.requests.get")
    @patch.dict(
        "os.environ",
        {"KIPRIS_API_KEY": "test-key"},
    )
    def test_no_results(self, mock_get):
        response = Mock()
        response.content = b"""
        <response>
            <resultCode>00</resultCode>
            <resultMsg>success</resultMsg>
        </response>
        """
        response.raise_for_status.return_value = None
        mock_get.return_value = response

        patents = search_patents("검색결과없는기술")

        assert patents == []


# ============================================================
# 특허 Pydantic 스키마 테스트
# ============================================================


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


# 추후 구현 예정
# class TestPatentProcessor:
#     """특허 데이터 정제 테스트"""

# class TestPatentRetrieval:
#     """ChromaDB 검색 테스트"""
