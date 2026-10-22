from unittest.mock import Mock, patch

import pytest

from src.ingestion.kipris_client import (
    KiprisAPIError,
    search_patents,
)

# class TestPatentSchema:
#    """특허 Pydantic 스키마 테스트"""

# KIPRIS PLUS API 테스트
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


# class TestPatentProcessor:
#   """특허 데이터 정제 테스트"""


# class TestPatentRetrieval:
#    """ChromaDB 검색 테스트"""
