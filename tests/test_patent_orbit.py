import math

import pytest

from frontend.patent_orbit import (
    patent_dense_similarity,
    patent_orbit_position,
    patent_semantic_similarity,
    semantic_similarity_text,
)
from src.schemas import PatentEvidence


def _evidence(dense=None, semantic=None):
    return PatentEvidence(
        citation_id=1,
        patent_id="P-1",
        title="특허",
        section="abstract",
        quote="초록",
        similarity=dense,
        semantic_similarity=semantic,
    )


@pytest.mark.parametrize(
    ("score", "radius"),
    [(0.0, 2.8), (1.0, 1.45), (None, 3.0)],
)
def test_orbit_radius_uses_semantic_score_boundaries(score, radius):
    x, y = patent_orbit_position(0, 4, score)
    assert x == pytest.approx(0, abs=1e-12)
    assert abs(y) == pytest.approx(0.78 * radius)


def test_higher_semantic_similarity_places_planet_closer_to_idea():
    low = patent_orbit_position(1, 4, 0.2)
    high = patent_orbit_position(1, 4, 0.9)
    assert math.dist(high, (0, 0)) < math.dist(low, (0, 0))


def test_dense_score_is_displayed_separately_from_orbit_similarity():
    evidence = [_evidence(dense=0.99, semantic=0.2)]
    assert patent_dense_similarity(evidence) == pytest.approx(0.99)
    assert patent_semantic_similarity(evidence) == pytest.approx(0.2)
    assert semantic_similarity_text(patent_semantic_similarity(evidence)) == "0.200"
    assert patent_orbit_position(
        0, 4, patent_semantic_similarity(evidence)
    ) == pytest.approx(patent_orbit_position(0, 4, 0.2))


def test_missing_semantic_score_is_not_inferred_from_dense_score():
    evidence = [_evidence(dense=0.91)]
    assert patent_semantic_similarity(evidence) is None
    assert patent_orbit_position(
        0, 4, patent_semantic_similarity(evidence)
    ) == pytest.approx(patent_orbit_position(0, 4, None))


@pytest.mark.parametrize("score", [-0.1, 1.1, float("nan"), "nan", "bad"])
def test_orbit_rejects_invalid_semantic_score(score):
    with pytest.raises(ValueError):
        patent_orbit_position(0, 1, score)
