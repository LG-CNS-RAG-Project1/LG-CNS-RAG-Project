from unittest.mock import Mock, patch

import pytest
from pydantic import ValidationError

from src.ingestion.kipris_client import (
    KiprisAPIError,
    search_patents,
)
from src.schemas import PatentReport, PatentEvidence, PatentComparison, PatentDocument

from src.ingestion.patent_processor import (
    build_chunks,
    to_patent_document,
    build_documents,
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


# ============================================================
# 특허 데이터 정제 테스트
# ============================================================


def test_to_patent_document():
    raw = {
        "application_number": "1020240001234",
        "title": "진동 기반 설비 고장 예측",
        "abstract": "진동 데이터를 분석하여 설비 고장을 예측한다.",
        "claims": None,
        "applicant": "테스트 기업",
        "source": "KIPRIS Plus",
    }

    patent = to_patent_document(raw)

    assert patent.patent_id == "1020240001234"
    assert patent.application_number == "1020240001234"
    assert patent.title == "진동 기반 설비 고장 예측"
    assert patent.abstract == raw["abstract"]
    assert patent.claims == ""
    assert patent.applicant == "테스트 기업"


def test_to_patent_document_without_application_number():
    with pytest.raises(ValueError, match="출원번호"):
        to_patent_document({"title": "출원번호 없는 특허"})


def test_build_chunks():
    patent = PatentDocument(
        patent_id="1020240001234",
        title="진동 기반 설비 고장 예측",
        abstract="진동 데이터를 분석하여 설비 고장을 예측한다.",
        claims="진동 센서와 AI 모델을 포함하는 고장 예측 장치.",
    )

    chunks = build_chunks([patent])

    assert len(chunks) == 2

    assert chunks[0].chunk_id == "1020240001234_abstract_0"
    assert chunks[0].patent_id == patent.patent_id
    assert chunks[0].section == "abstract"
    assert chunks[0].text == patent.abstract
    assert chunks[0].chunk_index == 0

    assert chunks[1].chunk_id == "1020240001234_claims_0"
    assert chunks[1].patent_id == patent.patent_id
    assert chunks[1].section == "claims"
    assert chunks[1].text == patent.claims
    assert chunks[1].chunk_index == 0


def test_build_chunks_without_claims():
    patent = PatentDocument(
        patent_id="1020240005678",
        title="AI 품질 검사",
        abstract="영상 데이터를 분석하여 불량품을 검출한다.",
    )

    chunks = build_chunks([patent])

    assert len(chunks) == 1
    assert chunks[0].section == "abstract"
    assert chunks[0].chunk_id == "1020240005678_abstract_0"


def test_build_chunks_without_content():
    patent = PatentDocument(
        patent_id="1020240009999",
        title="본문 없는 특허",
        abstract="",
        claims="",
    )

    assert build_chunks([patent]) == []


def test_build_documents_deduplication():
    records = [
        {
            "application_number": "1020240001234",
            "title": "진동 기반 고장 예측",
            "abstract": "진동 데이터를 분석한다.",
        },
        {
            "application_number": "1020240001234",
            "title": "중복 특허",
            "abstract": "중복 데이터",
        },
        {
            "application_number": "1020240005678",
            "title": "AI 품질 검사",
            "abstract": "영상 데이터를 분석한다.",
        },
        {
            "application_number": None,
            "title": "출원번호 없는 특허",
        },
    ]

    documents = build_documents(records)

    assert len(documents) == 2
    assert [doc.patent_id for doc in documents] == [
        "1020240001234",
        "1020240005678",
    ]
    assert documents[0].title == "진동 기반 고장 예측"


# class TestPatentRetrieval:
#     """ChromaDB 검색 테스트"""
