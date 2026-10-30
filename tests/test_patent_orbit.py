import pytest
import requests
from unittest.mock import Mock, patch

from frontend.patent_orbit import (
    kipris_drawing_url,
    fetch_kipris_drawing,
    fetch_first_kipris_drawing,
    drawing_image_metadata,
    patent_dense_similarity,
    patent_orbit_position,
    tooltip_text,
)
from src.schemas import PatentEvidence


def _evidence(score):
    return PatentEvidence(
        citation_id=1,
        patent_id="P1",
        title="특허",
        section="abstract",
        quote="검색 근거",
        similarity=score,
    )


def test_patent_similarity_uses_highest_dense_score_and_preserves_missing():
    assert patent_dense_similarity([_evidence(0.4), _evidence(0.8)]) == 0.8
    assert patent_dense_similarity([_evidence(None)]) is None
    assert patent_dense_similarity([]) is None


@pytest.mark.parametrize(
    ("score", "expected_radius"), [(0, 2.8), (1, 1.45), (None, 3.0)]
)
def test_orbit_radius_boundaries(score, expected_radius):
    x, y = patent_orbit_position(0, 4, score)
    assert x == pytest.approx(0, abs=1e-12)
    assert abs(y) == pytest.approx(0.78 * expected_radius)


def test_higher_similarity_is_closer_to_center():
    low_x, low_y = patent_orbit_position(1, 4, 0.2)
    high_x, high_y = patent_orbit_position(1, 4, 0.9)
    assert (high_x**2 + high_y**2) < (low_x**2 + low_y**2)


def test_kipris_drawing_url_requires_kipris_host_and_uses_https():
    assert (
        kipris_drawing_url("http://plus.kipris.or.kr/openapi/fileToss.jsp?arg=figure")
        == "https://plus.kipris.or.kr/openapi/fileToss.jsp?arg=figure"
    )
    assert kipris_drawing_url("https://example.com/figure.png") is None
    assert kipris_drawing_url("javascript:alert(1)") is None


@patch("frontend.patent_orbit.requests.get")
def test_fetch_kipris_drawing_checks_image_type_and_size(mock_get):
    response = Mock(status_code=200)
    response.headers = {"Content-Type": "application/octet-stream;charset=UTF-8"}
    jpeg = bytes.fromhex("ffd8ffe000104a46494600010101006000600000ffdb0043")
    response.iter_content.return_value = [jpeg]
    mock_get.return_value = response
    assert fetch_kipris_drawing("https://plus.kipris.or.kr/figure") == (jpeg, "ok")
    mock_get.assert_called_once_with(
        "https://plus.kipris.or.kr/figure",
        timeout=(3, 8),
        stream=True,
        allow_redirects=False,
    )
    response.close.assert_called_once()

    response.iter_content.return_value = [b"12345"]
    assert fetch_kipris_drawing("https://plus.kipris.or.kr/figure", max_bytes=4) == (
        None,
        "too_large",
    )


@pytest.mark.parametrize(
    ("status", "content_type", "body", "expected_status"),
    [
        (200, "text/html", b"<html>error</html>", "non_image_response"),
        (200, "image/png", b"<html>error</html>", "invalid_image"),
        (200, "image/jpeg", b"", "invalid_image"),
        (302, "image/jpeg", bytes.fromhex("ffd8ff"), "redirect"),
    ],
)
@patch("frontend.patent_orbit.requests.get")
def test_fetch_kipris_drawing_rejects_errors_and_redirects(
    mock_get, status, content_type, body, expected_status
):
    response = Mock(status_code=status)
    response.headers = {"Content-Type": content_type}
    response.iter_content.return_value = [body] if body else []
    mock_get.return_value = response

    assert fetch_kipris_drawing("https://plus.kipris.or.kr/figure") == (
        None,
        expected_status,
    )
    mock_get.assert_called_once()
    assert mock_get.call_args.kwargs["allow_redirects"] is False
    response.close.assert_called_once()


@patch(
    "frontend.patent_orbit.fetch_kipris_drawing",
    side_effect=[(None, "http_error"), (b"jpeg", "ok")],
)
def test_fetch_first_kipris_drawing_falls_back_from_original_to_thumbnail(mock_fetch):
    result = fetch_first_kipris_drawing(
        (
            "https://plus.kipris.or.kr/drawing",
            "https://plus.kipris.or.kr/thumbnail",
        )
    )
    assert result == (b"jpeg", "ok", "https://plus.kipris.or.kr/thumbnail")
    assert [call.args[0] for call in mock_fetch.call_args_list] == [
        "https://plus.kipris.or.kr/drawing",
        "https://plus.kipris.or.kr/thumbnail",
    ]


@patch("frontend.patent_orbit.fetch_kipris_drawing", return_value=(None, "http_error"))
def test_fetch_first_kipris_drawing_skips_missing_urls_and_reports_failure(mock_fetch):
    assert fetch_first_kipris_drawing(("https://plus.kipris.or.kr/thumb", None)) == (
        None,
        "http_error",
        None,
    )
    mock_fetch.assert_called_once_with(
        "https://plus.kipris.or.kr/thumb", max_bytes=8_000_000
    )
    assert fetch_first_kipris_drawing((None, None)) == (None, "missing_url", None)


def test_drawing_image_metadata_limits_display_width_without_upscaling():
    from io import BytesIO
    from PIL import Image

    content = BytesIO()
    Image.new("RGB", (621, 405)).save(content, format="JPEG")
    assert drawing_image_metadata(content.getvalue()) == (621, 405, 621, "JPEG")
    content = BytesIO()
    Image.new("RGB", (1600, 900)).save(content, format="JPEG")
    assert drawing_image_metadata(content.getvalue()) == (1600, 900, 900, "JPEG")


@patch("frontend.patent_orbit.requests.get", side_effect=requests.Timeout)
def test_fetch_kipris_drawing_reports_network_failure(mock_get):
    assert fetch_kipris_drawing("https://plus.kipris.or.kr/figure") == (
        None,
        "network_error",
    )
    mock_get.assert_called_once()


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("청구항 1 구성에 직접 대응", "청구항 1 구성에 직접 대응"),
        ("  관련 구성 확인  ", "관련 구성 확인"),
        (None, "우선 확인 이유 미제공"),
        (float("nan"), "우선 확인 이유 미제공"),
        (float("inf"), "우선 확인 이유 미제공"),
        ("NaN", "우선 확인 이유 미제공"),
        ("nan", "우선 확인 이유 미제공"),
        (" None ", "우선 확인 이유 미제공"),
        ("null", "우선 확인 이유 미제공"),
        ("   ", "우선 확인 이유 미제공"),
    ],
)
def test_tooltip_text_replaces_missing_and_nan_values(value, expected):
    assert tooltip_text(value, "우선 확인 이유 미제공") == expected


@pytest.mark.parametrize("score", [-0.01, 1.01])
def test_orbit_rejects_out_of_range_similarity(score):
    with pytest.raises(ValueError, match="between 0 and 1"):
        patent_orbit_position(0, 4, score)
