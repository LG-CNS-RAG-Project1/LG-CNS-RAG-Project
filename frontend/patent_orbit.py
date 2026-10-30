"""특허 검색 점수와 궤도 표시 좌표를 계산한다."""

import math
from io import BytesIO
from urllib.parse import urlsplit, urlunsplit

import requests
from PIL import Image


def patent_dense_similarity(evidence) -> float | None:
    """문헌에 연결된 Dense 검색 점수 중 최고값을 반환한다."""
    scores = []
    for item in evidence:
        try:
            score = float(item.similarity)
        except (TypeError, ValueError):
            continue
        if math.isfinite(score) and 0 <= score <= 1:
            scores.append(score)
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


def fetch_kipris_drawing(
    value: str | None, max_bytes: int = 8_000_000
) -> tuple[bytes | None, str]:
    """허용된 KIPRIS 이미지 링크에서 그림을 가져오고 실패 유형을 반환한다."""
    url = kipris_drawing_url(value)
    if not url:
        return None, "invalid_source"
    response = None
    try:
        response = requests.get(url, timeout=(3, 8), stream=True, allow_redirects=False)
        if 300 <= response.status_code < 400:
            return None, "redirect"
        if response.status_code != 200:
            return None, "http_error"
        content_type = response.headers.get("Content-Type", "").split(";", 1)[0]
        content_type = content_type.strip().lower()
        if not (
            content_type.startswith("image/")
            or content_type in {"application/octet-stream", "binary/octet-stream"}
        ):
            return None, "non_image_response"
        content_length = response.headers.get("Content-Length", "")
        if content_length.isdigit() and int(content_length) > max_bytes:
            return None, "too_large"
        content = bytearray()
        for chunk in response.iter_content(chunk_size=64_000):
            content.extend(chunk)
            if len(content) > max_bytes:
                return None, "too_large"
        image = bytes(content)
        return (image, "ok") if _has_image_signature(image) else (None, "invalid_image")
    except requests.RequestException:
        return None, "network_error"
    finally:
        if response is not None:
            response.close()


def _has_image_signature(content: bytes) -> bool:
    """HTML 오류 페이지나 임의 바이너리를 걸러내고 지원 이미지 서명을 확인한다."""
    if content.startswith(b"\xff\xd8\xff"):
        return True
    if content.startswith(b"\x89PNG\r\n\x1a\n"):
        return True
    if content.startswith((b"GIF87a", b"GIF89a", b"BM")):
        return True
    if content.startswith((b"II*\x00", b"MM\x00*")):
        return True
    return (
        len(content) >= 12 and content.startswith(b"RIFF") and content[8:12] == b"WEBP"
    )


def fetch_first_kipris_drawing(
    urls: tuple[str | None, ...], max_bytes: int = 8_000_000
) -> tuple[bytes | None, str, str | None]:
    """원본 도면을 우선 확인하고 실패하면 같은 문헌의 썸네일을 반환한다."""
    last_status = "missing_url"
    for url in dict.fromkeys(value for value in urls if value):
        image, status = fetch_kipris_drawing(url, max_bytes=max_bytes)
        if image:
            return image, "ok", url
        last_status = status
    return None, last_status, None


def drawing_image_metadata(
    content: bytes, max_width: int = 900
) -> tuple[int, int, int, str]:
    """도면의 실제 픽셀 크기와 확대하지 않는 표시 폭을 반환한다."""
    with Image.open(BytesIO(content)) as image:
        width, height = image.size
        image_format = image.format or "unknown"
    return width, height, min(width, max_width), image_format


def tooltip_text(value, fallback: str) -> str:
    """Altair hover 텍스트에서 null·NaN 값이 문자열로 노출되지 않게 정리한다."""
    if value is None:
        return fallback
    if isinstance(value, (int, float)) and not math.isfinite(float(value)):
        return fallback
    text = str(value).strip()
    if text.casefold() in {"", "nan", "none", "null"}:
        return fallback
    return text
