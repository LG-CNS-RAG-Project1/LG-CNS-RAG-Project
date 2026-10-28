import json
from unittest.mock import Mock, patch

from src.ingestion.kipris_client import (
    KIPRIS_BIBLIOGRAPHY_URL,
    KIPRIS_URL,
    fetch_patent_claims,
    search_patents,
)


@patch("src.ingestion.kipris_client.requests.get")
@patch.dict("os.environ", {"KIPRIS_API_KEY": "secret-test-key"})
def test_patent_search_saves_raw_response_without_api_key(mock_get, tmp_path):
    response = Mock(
        content=b"<response><resultCode>00</resultCode></response>", status_code=200
    )
    response.raise_for_status.return_value = None
    mock_get.return_value = response

    assert search_patents("AI 비전 검사", raw_dir=tmp_path) == []

    xml_path = next(tmp_path.glob("patent_search_*.xml"))
    metadata_path = xml_path.with_suffix(".json")
    metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    assert xml_path.read_bytes() == response.content
    assert metadata["identifier"] == "AI 비전 검사"
    assert "secret-test-key" not in metadata_path.read_text(encoding="utf-8")
    assert mock_get.call_args.args[0] == KIPRIS_URL


@patch("src.ingestion.kipris_client.requests.get")
@patch.dict("os.environ", {"KIPRIS_API_KEY": "secret-test-key"})
def test_claim_lookup_saves_raw_response(mock_get, tmp_path):
    response = Mock(
        content=(
            "<response><resultCode>00</resultCode><claimInfoArray>"
            "<claimInfo><claim>1. 독립항</claim></claimInfo></claimInfoArray></response>"
        ).encode("utf-8"),
        status_code=200,
    )
    response.raise_for_status.return_value = None
    mock_get.return_value = response

    claims = fetch_patent_claims("1020260000001", raw_dir=tmp_path)

    assert claims == [{"claim_number": 1, "text": "1. 독립항"}]
    xml_path = next(tmp_path.glob("patent_claims_*.xml"))
    metadata = json.loads(xml_path.with_suffix(".json").read_text(encoding="utf-8"))
    assert metadata["identifier"] == "1020260000001"
    assert "secret-test-key" not in xml_path.with_suffix(".json").read_text(
        encoding="utf-8"
    )
    assert mock_get.call_args.args[0] == KIPRIS_BIBLIOGRAPHY_URL
