from unittest.mock import Mock, patch

import pytest

from src.ingestion.kipris_client import (
    KIPRIS_BIBLIOGRAPHY_URL,
    KiprisAPIError,
    fetch_patent_claims,
    parse_claims_xml,
)
from src.ingestion.patent_processor import (
    build_chunks,
    structure_claims,
    to_patent_document,
)
from src.retrieval.adapters import patent_to_search_document
from src.retrieval.patent_store import to_chroma_record
from src.schemas import PatentDocument

CLAIMS_XML = """
<response><header><resultCode>00</resultCode></header><body><claimInfoArray>
  <claimInfo><claimNumber>1</claimNumber><claimText>비전 카메라를 포함하는 검사 장치.</claimText></claimInfo>
  <claimInfo><claimNumber>2</claimNumber><claimText>제1항에 있어서, 결함을 분류하는 장치.</claimText></claimInfo>
</claimInfoArray></body></response>
""".encode("utf-8")

KIPRIS_BIBLIOGRAPHY_XML = """
<response>
  <header><resultCode>00</resultCode><resultMsg>NORMAL SERVICE.</resultMsg></header>
  <body><item>
    <applicationNumber>10-2025-0017269</applicationNumber>
    <claimCount>2</claimCount>
    <claimInfoArray>
      <claimInfo><claim>1. 안전 협업 제어 시스템.</claim></claimInfo>
      <claimInfo><claim>2. 제1항에 있어서, 비전 처리 엔진을 포함하는 시스템.</claim></claimInfo>
    </claimInfoArray>
  </item></body>
</response>
""".encode("utf-8")


def test_parse_claims_xml_preserves_claim_numbers_and_text():
    assert parse_claims_xml(CLAIMS_XML) == [
        {"claim_number": 1, "text": "비전 카메라를 포함하는 검사 장치."},
        {"claim_number": 2, "text": "제1항에 있어서, 결함을 분류하는 장치."},
    ]


def test_parse_claims_xml_rejects_invalid_xml():
    with pytest.raises(KiprisAPIError, match="XML 응답 파싱"):
        parse_claims_xml(b"<bad>")


def test_parse_claims_xml_handles_live_kipris_claim_info_shape():
    assert parse_claims_xml(KIPRIS_BIBLIOGRAPHY_XML) == [
        {"claim_number": 1, "text": "1. 안전 협업 제어 시스템."},
        {
            "claim_number": 2,
            "text": "2. 제1항에 있어서, 비전 처리 엔진을 포함하는 시스템.",
        },
    ]


@patch("src.ingestion.kipris_client.requests.get")
@patch.dict("os.environ", {"KIPRIS_API_KEY": "test-key"})
def test_fetch_patent_claims_uses_application_number_and_parses(mock_get):
    response = Mock(content=KIPRIS_BIBLIOGRAPHY_XML)
    response.raise_for_status.return_value = None
    mock_get.return_value = response

    claims = fetch_patent_claims("1020230030067", raw_dir=None)

    assert len(claims) == 2
    mock_get.assert_called_once_with(
        KIPRIS_BIBLIOGRAPHY_URL,
        params={"ServiceKey": "test-key", "applicationNumber": "1020230030067"},
        timeout=20,
    )


def test_structure_claims_identifies_dependent_references():
    claims = structure_claims(
        [
            {"claim_number": 1, "text": "비전 검사 장치."},
            {"claim_number": 2, "text": "제1항에 있어서, 카메라를 포함하는 장치."},
            {
                "claim_number": 3,
                "text": "제1항 내지 제2항 중 어느 한 항에 있어서 제어부를 포함하는 장치.",
            },
        ],
        version_id="KR102345678B1",
    )

    assert claims[0].claim_type == "independent"
    assert claims[1].claim_type == "dependent"
    assert claims[1].depends_on == [1]
    assert claims[2].depends_on == [1, 2]
    assert all(claim.version_id == "KR102345678B1" for claim in claims)


def test_structure_claims_recognizes_claim_wording_without_trailing_hangul():
    claims = structure_claims(
        [
            {"claim_number": 1, "text": "기본 장치."},
            {"claim_number": 2, "text": "청구항 1에 있어서, 센서를 포함하는 장치."},
        ]
    )

    assert claims[1].claim_type == "dependent"
    assert claims[1].depends_on == [1]


def test_deleted_claims_are_excluded_from_searchable_claims():
    claims = structure_claims(
        [
            {"claim_number": 1, "text": "비전 검사 장치."},
            {"claim_number": 2, "text": "삭제"},
            {"claim_number": 3, "text": "3. 삭제."},
            {"claim_number": 4, "text": "제1항에 있어서, 제어부를 포함하는 장치."},
        ]
    )
    assert [claim.claim_number for claim in claims] == [1, 4]


def test_claims_become_individual_index_chunks_with_location_metadata():
    patent = to_patent_document(
        {
            "application_number": "1020230030067",
            "title": "비전 검사 장치",
            "abstract": "카메라 영상을 처리한다.",
            "publication_number": "KR102345678A",
            "claims": [
                {"claim_number": 1, "text": "비전 카메라를 포함하는 검사 장치."},
                {"claim_number": 2, "text": "제1항에 있어서, 제어부를 포함하는 장치."},
            ],
        }
    )
    chunks = build_chunks([patent])
    claim_chunks = [chunk for chunk in chunks if chunk.section == "claims"]
    search_doc = patent_to_search_document(claim_chunks[1], patent)
    chunk_id, indexed_text, metadata = to_chroma_record(claim_chunks[1], patent)

    assert [chunk.claim_number for chunk in claim_chunks] == [1, 2]
    assert claim_chunks[1].chunk_id == "1020230030067_claim_2"
    assert search_doc.metadata["depends_on"] == [1]
    assert search_doc.metadata["version_id"] == "KR102345678A"
    assert chunk_id == claim_chunks[1].chunk_id
    assert indexed_text == claim_chunks[1].text
    assert metadata["depends_on"] == "1"
    assert metadata["claim_number"] == 2


def test_unparsed_claim_text_is_not_invented_as_a_numbered_claim():
    assert structure_claims("청구항 번호가 없는 임의 텍스트") == []


def test_select_claims_includes_referenced_parent_claims():
    from types import SimpleNamespace
    from src.services.patent_service import _select_claims

    claims = structure_claims(
        [
            {"claim_number": 1, "text": "일반 검사 장치."},
            {"claim_number": 2, "text": "제1항에 있어서, 센서를 제어하는 제어부."},
            {
                "claim_number": 3,
                "text": "제2항에 있어서, 카메라 데이터를 분류하는 장치.",
            },
        ]
    )
    selected = _select_claims(
        SimpleNamespace(
            technical_components=["카메라 데이터 분류"], technology="", problem=""
        ),
        claims,
        limit=3,
    )
    assert [claim.claim_number for claim in selected] == [1, 2, 3]


def test_select_claims_keeps_dependent_claim_for_explicit_parent_warning():
    from types import SimpleNamespace
    from src.services.patent_service import _select_claims

    claims = structure_claims(
        [
            {"claim_number": 1, "text": "일반 검사 장치."},
            {
                "claim_number": 3,
                "text": "제2항에 있어서, 카메라 데이터를 분류하는 장치.",
            },
        ]
    )
    selected = _select_claims(
        SimpleNamespace(
            technical_components=["카메라 데이터 분류"], technology="", problem=""
        ),
        claims,
        limit=5,
    )
    assert [claim.claim_number for claim in selected] == [1, 3]


def test_patent_context_builder_keeps_claim_chain_within_budget():
    from types import SimpleNamespace

    from src.ingestion.patent_processor import structure_claims
    from src.services.patent_service import _build_patent_context

    claims = structure_claims(
        [
            {"claim_number": 1, "text": "센서와 제어기를 포함하는 검사 장치."},
            {"claim_number": 2, "text": "제1항에 있어서, 영상을 분석하는 장치."},
            {"claim_number": 3, "text": "제2항에 있어서, 이상을 분류하는 장치."},
        ]
    )
    idea = SimpleNamespace(
        technical_components=["영상을 분석하고 이상을 분류"], technology="", problem=""
    )

    selected, estimated_tokens, notes = _build_patent_context(
        idea, claims, max_tokens=200, max_claims=5
    )

    assert [claim.claim_number for claim in selected] == [1, 2, 3]
    assert estimated_tokens <= 200
    assert notes == []


def test_patent_context_builder_drops_dependent_chain_when_parent_exceeds_budget():
    from types import SimpleNamespace

    from src.ingestion.patent_processor import structure_claims
    from src.services.patent_service import _build_patent_context

    claims = structure_claims(
        [
            {
                "claim_number": 1,
                "text": "센서와 제어기를 포함하는 검사 장치." + "구성" * 300,
            },
            {"claim_number": 2, "text": "제1항에 있어서, 영상을 분석하는 장치."},
        ]
    )
    idea = SimpleNamespace(
        technical_components=["영상을 분석"], technology="", problem=""
    )

    selected, estimated_tokens, notes = _build_patent_context(
        idea, claims, max_tokens=80, max_claims=5
    )

    assert selected == []
    assert estimated_tokens == 0
    assert any("문맥 토큰 예산을 초과해 제외" in note for note in notes)


def test_estimated_patent_context_token_count_handles_mixed_language():
    from src.services.patent_service import _estimate_text_tokens

    assert _estimate_text_tokens("  vision   검사 device ") >= 3
    assert _estimate_text_tokens(" ") == 0
