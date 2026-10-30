"""특허 검색 점수와 궤도 표시 좌표를 계산한다."""

import math
from urllib.parse import urlsplit, urlunsplit

import requests


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


def kipris_drawing_url(value: str | None) -> str | None:
    """KIPRIS 도면 파일 링크만 HTTPS로 정규화해 허용한다."""
    if not value:
        return None
    try:
        parsed = urlsplit(value.strip())
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname != "plus.kipris.or.kr"
            or parsed.username
            or parsed.password
            or parsed.port not in {None, 80, 443}
        ):
            return None
        return urlunsplit(("https", parsed.netloc, parsed.path, parsed.query, ""))
    except ValueError:
        return None


def fetch_kipris_drawing(value: str | None, max_bytes: int = 8_000_000) -> bytes | None:
    """허용된 KIPRIS 이미지 링크에서 제한된 크기의 그림만 가져온다."""
    url = kipris_drawing_url(value)
    if not url:
        return None
    response = None
    try:
        response = requests.get(url, timeout=(3, 8), stream=True, allow_redirects=False)
        if response.status_code != 200 or not response.headers.get(
            "Content-Type", ""
        ).lower().startswith("image/"):
            return None
        content = bytearray()
        for chunk in response.iter_content(chunk_size=64_000):
            content.extend(chunk)
            if len(content) > max_bytes:
                return None
        return bytes(content) if content else None
    except requests.RequestException:
        return None
    finally:
        if response is not None:
            response.close()
