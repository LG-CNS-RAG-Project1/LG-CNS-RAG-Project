import hashlib
import json
import os
import re
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from pathlib import Path

import requests
from dotenv import load_dotenv

load_dotenv()

KIPRIS_URL = (
    "https://plus.kipris.or.kr/openapi/rest/" "patUtiModInfoSearchSevice/freeSearchInfo"
)
KIPRIS_BIBLIOGRAPHY_URL = (
    "https://plus.kipris.or.kr/kipo-api/kipi/"
    "patUtiModInfoSearchSevice/getBibliographyDetailInfoSearch"
)
ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_DIR = ROOT_DIR / "data" / "patents" / "raw"


class KiprisAPIError(Exception):
    """KIPRIS API 호출 또는 응답 처리 오류."""


def _save_raw_response(
    response,
    operation: str,
    identifier: str,
    raw_dir: Path | None = RAW_DIR,
) -> Path | None:
    """응답 XML과 비밀정보를 제외한 조회 메타데이터를 로컬에 남긴다."""
    if raw_dir is None:
        return None
    raw_dir.mkdir(parents=True, exist_ok=True)
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    digest = hashlib.sha256(identifier.encode("utf-8")).hexdigest()[:12]
    stem = f"{operation}_{digest}_{timestamp}"
    xml_path = raw_dir / f"{stem}.xml"
    xml_path.write_bytes(response.content)
    metadata = {
        "operation": operation,
        "identifier": identifier,
        "fetched_at_utc": timestamp,
        "http_status": getattr(response, "status_code", None),
        "response_file": xml_path.name,
    }
    (raw_dir / f"{stem}.json").write_text(
        json.dumps(metadata, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    return xml_path


def _get_text(element, tag):
    value = element.findtext(tag)
    return value.strip() if value else None


def _classification_codes(value: str | None) -> list[str]:
    """KIPRIS 분류 코드 목록을 분리하면서 원본 코드 표기는 유지한다."""
    return list(
        dict.fromkeys(item.strip() for item in (value or "").split("|") if item.strip())
    )


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
        if _local_name(node.tag) == "claiminfo":
            claim_text = next(
                (
                    (child.text or "").strip()
                    for child in node.iter()
                    if child is not node
                    and _local_name(child.tag) in text_names
                    and (child.text or "").strip()
                ),
                None,
            )
            if claim_text:
                match = re.match(
                    r"^\s*(?:【\s*청구항\s*)?(\d+)\s*(?:】|[.)．、])\s*",
                    claim_text,
                )
                if match:
                    claim_nodes.append(
                        {"claim_number": int(match.group(1)), "text": claim_text}
                    )
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


def search_patents(
    keyword: str,
    limit: int = 20,
    raw_dir: Path | None = RAW_DIR,
) -> list[dict]:
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
        _save_raw_response(response, "patent_search", keyword.strip(), raw_dir)
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
            "ipc_codes": _classification_codes(
                _get_text(item, "InternationalpatentclassificationNumber")
            ),
            "cpc_codes": _classification_codes(
                _get_text(item, "CooperativepatentclassificationNumber")
                or _get_text(item, "CPCNumber")
            ),
            "application_date": _get_text(item, "ApplicationDate"),
            "publication_date": _get_text(item, "OpeningDate")
            or _get_text(item, "OpenDate"),
            "public_date": _get_text(item, "PublicDate"),
            "publication_number": (
                _get_text(item, "OpeningNumber") or _get_text(item, "PublicNumber")
            ),
            "registration_number": _get_text(item, "RegistrationNumber"),
            "source_url": (
                _get_text(item, "SourceUrl")
                or _get_text(item, "DetailLink")
                or _get_text(item, "KiprisUrl")
            ),
            "representative_drawing_url": (
                _get_text(item, "DrawingPath") or _get_text(item, "ImagePath")
            ),
            "representative_thumbnail_url": (
                _get_text(item, "ThumbnailPath")
                or _get_text(item, "ThumbnailImagePath")
            ),
            "representative_drawing_caption": _get_text(item, "DrawingName")
            or _get_text(item, "RepresentativeDrawingName"),
            "claims": None,
            "source": "KIPRIS Plus",
        }

        patents.append(patent)

    return patents


def fetch_patent_claims(
    application_number: str,
    raw_dir: Path | None = RAW_DIR,
) -> list[dict]:
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
                "ServiceKey": api_key,
                "applicationNumber": application_number.strip(),
            },
            timeout=20,
        )
        _save_raw_response(
            response, "patent_claims", application_number.strip(), raw_dir
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
