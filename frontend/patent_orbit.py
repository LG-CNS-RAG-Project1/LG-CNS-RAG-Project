"""특허 점수의 안전한 표시와 유사도 기반 궤도 좌표를 계산한다."""

import math


def _score(value) -> float | None:
    try:
        score = float(value)
    except (TypeError, ValueError):
        return None
    return score if math.isfinite(score) and 0 <= score <= 1 else None


def patent_dense_similarity(evidence) -> float | None:
    """특허에 연결된 Dense 점수 중 유효한 최고값을 반환한다."""
    scores = [_score(item.similarity) for item in evidence]
    valid_scores = [score for score in scores if score is not None]
    return max(valid_scores) if valid_scores else None


def patent_semantic_similarity(evidence) -> float | None:
    """특허에 저장된 임베딩 의미 유사도 중 유효한 최고값을 반환한다."""
    scores = [_score(getattr(item, "semantic_similarity", None)) for item in evidence]
    valid_scores = [score for score in scores if score is not None]
    return max(valid_scores) if valid_scores else None


def dense_similarity_text(value) -> str:
    score = _score(value)
    return f"{score:.3f} · Dense 점수 (확률 아님)" if score is not None else "미제공"


def semantic_similarity_text(value) -> str:
    score = _score(value)
    return f"{score:.3f}" if score is not None else "계산 불가"


def patent_orbit_position(index: int, count: int, similarity: float | None):
    """의미 유사도가 높을수록 아이디어 중심에 가까운 좌표를 반환한다."""
    if count < 1:
        raise ValueError("count must be positive")
    if similarity is None:
        radius = 3.0
    else:
        score = _score(similarity)
        if score is None:
            raise ValueError("similarity must be between 0 and 1")
        radius = 2.8 - 1.35 * score
    angle = (2 * math.pi * index / count) - math.pi / 2
    return radius * math.cos(angle), 0.78 * radius * math.sin(angle)
