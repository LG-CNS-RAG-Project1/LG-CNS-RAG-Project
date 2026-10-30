import pytest

from frontend.patent_orbit import patent_dense_similarity, patent_orbit_position
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


@pytest.mark.parametrize("score", [-0.01, 1.01])
def test_orbit_rejects_out_of_range_similarity(score):
    with pytest.raises(ValueError, match="between 0 and 1"):
        patent_orbit_position(0, 4, score)
