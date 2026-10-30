import pytest
from unittest.mock import Mock, patch

from frontend.patent_orbit import (
    kipris_drawing_url,
    fetch_kipris_drawing,
    patent_dense_similarity,
    patent_orbit_position,
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
    response.headers = {"Content-Type": "image/png"}
    response.iter_content.return_value = [b"png-data"]
    mock_get.return_value = response
    assert fetch_kipris_drawing("https://plus.kipris.or.kr/figure") == b"png-data"
    mock_get.assert_called_once_with(
        "https://plus.kipris.or.kr/figure",
        timeout=(3, 8),
        stream=True,
        allow_redirects=False,
    )
    response.close.assert_called_once()

    response.iter_content.return_value = [b"12345"]
    assert fetch_kipris_drawing("https://plus.kipris.or.kr/figure", max_bytes=4) is None


@pytest.mark.parametrize("score", [-0.01, 1.01])
def test_orbit_rejects_out_of_range_similarity(score):
    with pytest.raises(ValueError, match="between 0 and 1"):
        patent_orbit_position(0, 4, score)
