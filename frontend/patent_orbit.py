"""특허 검색 점수와 궤도 표시 좌표를 계산한다."""

import math


def patent_dense_similarity(evidence) -> float | None:
    """문헌에 연결된 Dense 검색 점수 중 최고값을 반환한다."""
    scores = [
        float(item.similarity)
        for item in evidence
        if item.similarity is not None and math.isfinite(float(item.similarity))
    ]
    return max(scores) if scores else None


def patent_orbit_position(index: int, count: int, similarity: float | None):
    """Dense 점수가 높을수록 안쪽에 배치하고 미제공 점수는 외곽에 둔다."""
    if count < 1:
        raise ValueError("count must be positive")
    if similarity is None:
        radius = 3.0
    else:
        if not 0 <= similarity <= 1:
            raise ValueError("similarity must be between 0 and 1")
        radius = 2.8 - 1.35 * similarity
    angle = (2 * math.pi * index / count) - math.pi / 2
    return radius * math.cos(angle), 0.78 * radius * math.sin(angle)
