import os
import xml.etree.ElementTree as ET

import requests
from dotenv import load_dotenv

load_dotenv()

KIPRIS_URL = (
    "https://plus.kipris.or.kr/openapi/rest/" "patUtiModInfoSearchSevice/freeSearchInfo"
)


class KiprisAPIError(Exception):
    """KIPRIS API 호출 또는 응답 처리 오류."""


def _get_text(element, tag):
    value = element.findtext(tag)
    return value.strip() if value else None


def search_patents(keyword: str, limit: int = 20) -> list[dict]:
    """키워드로 특허를 검색하고 정제된 목록을 반환한다."""

    if not keyword.strip():
        raise ValueError("검색어가 비어 있습니다.")

    if not 1 <= limit <= 500:
        raise ValueError("limit는 1~500 사이여야 합니다.")

    api_key = os.getenv("KIPRIS_API_KEY")

    if not api_key:
        raise KiprisAPIError("KIPRIS_API_KEY가 설정되지 않았습니다.")

    params = {
        "accessKey": api_key,
        "word": keyword.strip(),
        "patent": "true",
        "utility": "true",
        "docsStart": 1,
        "docsCount": limit,
    }

    try:
        response = requests.get(
            KIPRIS_URL,
            params=params,
            timeout=20,
        )
        response.raise_for_status()

    except requests.RequestException as exc:
        raise KiprisAPIError(f"KIPRIS HTTP 요청 실패: {exc}") from exc

    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise KiprisAPIError("KIPRIS XML 응답 파싱 실패") from exc

    result_code = root.findtext(".//resultCode")
    result_message = root.findtext(".//resultMsg")

    if result_code != "00":
        raise KiprisAPIError(f"KIPRIS API 오류: {result_code} - {result_message}")

    patents = []
    seen = set()

    for item in root.findall(".//PatentUtilityInfo"):
        application_number = _get_text(item, "ApplicationNumber")

        if not application_number:
            continue

        if application_number in seen:
            continue

        seen.add(application_number)

        patent = {
            "application_number": application_number,
            "title": _get_text(item, "InventionName"),
            "abstract": _get_text(item, "Abstract"),
            "applicant": _get_text(item, "Applicant"),
            "application_date": _get_text(item, "ApplicationDate"),
            "publication_number": (
                _get_text(item, "OpeningNumber") or _get_text(item, "PublicNumber")
            ),
            "registration_number": _get_text(item, "RegistrationNumber"),
            "claims": None,
            "source": "KIPRIS Plus",
        }

        patents.append(patent)

    return patents
