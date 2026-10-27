import os
import xml.etree.ElementTree as ET

import requests
from dotenv import load_dotenv

load_dotenv()

KIPRIS_URL = (
    "https://plus.kipris.or.kr/openapi/rest/" "patUtiModInfoSearchSevice/freeSearchInfo"
)
KIPRIS_BIBLIOGRAPHY_URL = (
    "https://plus.kipris.or.kr/openapi/rest/"
    "patUtiModInfoSearchSevice/getBibliographyDetailInfoSearch"
)


class KiprisAPIError(Exception):
    """KIPRIS API 호출 또는 응답 처리 오류."""


def _get_text(element, tag):
    value = element.findtext(tag)
    return value.strip() if value else None


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1].lower()


def parse_claims_xml(content: bytes | str) -> list[dict]:
    """KIPRIS 서지상세 XML의 청구항 항목을 번호와 원문으로 추출한다."""
    try:
        root = ET.fromstring(content)
    except ET.ParseError as exc:
        raise KiprisAPIError("KIPRIS 청구항 XML 응답 파싱 실패") from exc

    claim_nodes = []
    number_names = {"claimnumber", "claimno", "claimnum", "petitionclauseserialnumber"}
    text_names = {"claimtext", "claimcontent", "claim", "petitionclause"}
    for node in root.iter():
        fields = {
            _local_name(child.tag): (child.text or "").strip()
            for child in node.iter()
            if child is not node and len(child) == 0 and (child.text or "").strip()
        }
        number = next((fields[name] for name in number_names if fields.get(name)), None)
        text = next((fields[name] for name in text_names if fields.get(name)), None)
        if number and text and number.isdigit():
            claim_nodes.append({"claim_number": int(number), "text": text})

    unique = {}
    for claim in claim_nodes:
        unique.setdefault(claim["claim_number"], claim)
    return [unique[number] for number in sorted(unique)]


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
            "source_url": (
                _get_text(item, "SourceUrl")
                or _get_text(item, "DetailLink")
                or _get_text(item, "KiprisUrl")
            ),
            "claims": None,
            "source": "KIPRIS Plus",
        }

        patents.append(patent)

    return patents


def fetch_patent_claims(application_number: str) -> list[dict]:
    """출원번호로 KIPRIS 서지상세의 청구항 원문을 조회한다.

    KIPRIS Plus에서 특허·실용 공개/등록공보 API 이용 승인이 필요하다.
    """
    if not application_number or not application_number.strip():
        raise ValueError("출원번호가 비어 있습니다.")
    api_key = os.getenv("KIPRIS_API_KEY")
    if not api_key:
        raise KiprisAPIError("KIPRIS_API_KEY가 설정되지 않았습니다.")
    try:
        response = requests.get(
            KIPRIS_BIBLIOGRAPHY_URL,
            params={
                "accessKey": api_key,
                "applicationNumber": application_number.strip(),
            },
            timeout=20,
        )
        response.raise_for_status()
    except requests.RequestException as exc:
        raise KiprisAPIError(f"KIPRIS 청구항 HTTP 요청 실패: {exc}") from exc
    try:
        root = ET.fromstring(response.content)
    except ET.ParseError as exc:
        raise KiprisAPIError("KIPRIS 청구항 XML 응답 파싱 실패") from exc
    result_code = root.findtext(".//resultCode")
    if result_code and result_code != "00":
        result_message = root.findtext(".//resultMsg")
        raise KiprisAPIError(
            f"KIPRIS 청구항 API 오류: {result_code} - {result_message}"
        )
    return parse_claims_xml(response.content)
