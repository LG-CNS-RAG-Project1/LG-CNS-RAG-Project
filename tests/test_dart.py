import json

import pytest
import requests

from src.ingestion import dart_client
from src.ingestion.dart_client import (
    _api_error,
    pick_latest_report,
    report_period,
)
from src.ingestion.dart_processor import (
    build_company_documents,
    build_documents,
    business_sections,
    chunk_text,
    xml_to_text,
)

REPORT_CONFIG = {
    "sections": ["사업의 개요", "매출", "기타 참고사항"],
    "purchase_sections": ["매출"],
    "chunk_size": 120,
    "chunk_overlap": 20,
}
IDEA_TERMS = {"SF-01": ["협동로봇"], "SF-03": ["예지보전"]}

XML = """<DOCUMENT>
<SECTION-1><TITLE ATOC="Y">I. 회사의 개요</TITLE><P>협동로봇 회사 개요는 제외</P></SECTION-1>
<SECTION-1 ACLASS="MANDATORY">
<TITLE ATOC="Y" ENG="II. Business Description">II. 사업의 내용</TITLE>
<SECTION-2><TITLE ATOC="Y">1. 사업의 개요</TITLE>
<P>당사는 협동로봇을 제조합니다. 주요 매출처는 해외 솔루션 업체입니다.</P>
<TABLE><TBODY><TR><TD>표 안의 숫자 11,587</TD></TR></TBODY></TABLE>
</SECTION-2>
<SECTION-2><TITLE ATOC="Y">3. 원재료 및 생산설비</TITLE><P>원재료는 제외</P></SECTION-2>
<SECTION-2><TITLE ATOC="Y">4. 매출 및 수주상황</TITLE>
<P><SPAN USERMARK="B">나. 판매 경로</SPAN><SPAN>딜러를 통해 고객사에 납품합니다 &amp; 직접 판매합니다.</SPAN></P>
</SECTION-2>
</SECTION-1>
<SECTION-1><TITLE ATOC="Y">III. 재무에 관한 사항</TITLE><P>재무는 제외</P></SECTION-1>
</DOCUMENT>"""

META = {
    "name": "가상로봇",
    "stock_code": "000001",
    "rcept_no": "20260318000001",
    "report_nm": "사업보고서 (2025.12)",
    "rcept_dt": 20260318,
    "period": "2025.12",
    "collected_at": 20261030,
    "idea_ids": ["SF-01", "SF-03"],
    "reason": "협동로봇 제조",
}


def report(rcept_no, report_nm, rcept_dt):
    return {"rcept_no": rcept_no, "report_nm": report_nm, "rcept_dt": rcept_dt}


def test_report_period():
    assert report_period("[기재정정]사업보고서 (2025.12)") == "2025.12"
    assert report_period("주요사항보고서") is None


def test_pick_latest_report_prefers_latest_period_and_correction():
    reports = [
        report("1", "사업보고서 (2024.12)", "20250321"),
        report("2", "사업보고서 (2025.12)", "20260313"),
        report("3", "[기재정정]사업보고서 (2025.12)", "20260417"),
        report("4", "[기재정정]사업보고서 (2024.12)", "20260501"),
    ]

    assert pick_latest_report(reports)["rcept_no"] == "3"
    assert pick_latest_report([report("9", "기타공시", "20260101")]) is None


def test_api_error_reads_json_and_xml():
    as_json = json.dumps({"status": "013", "message": "조회된 데이타가 없습니다."})
    as_xml = "<result><status>020</status><message>요청 제한 초과</message></result>"

    assert "013" in str(_api_error("list.json", as_json.encode()))
    assert "020: 요청 제한 초과" in str(_api_error("document.xml", as_xml.encode()))


def test_get_error_does_not_expose_api_key(monkeypatch):
    monkeypatch.setenv("DART_API_KEY", "secret-dart-key")
    monkeypatch.setattr(dart_client, "load_dotenv", lambda *a, **k: None)

    class Response:
        status_code = 500

    monkeypatch.setattr(dart_client.requests, "get", lambda *a, **k: Response())
    with pytest.raises(RuntimeError) as http_error:
        dart_client._get("list.json", {})

    def fail(*args, **kwargs):
        raise requests.ConnectionError(
            "https://opendart.fss.or.kr/api?crtfc_key=secret-dart-key"
        )

    monkeypatch.setattr(dart_client.requests, "get", fail)
    with pytest.raises(RuntimeError) as network_error:
        dart_client._get("list.json", {})

    assert "secret-dart-key" not in str(http_error.value)
    assert "secret-dart-key" not in str(network_error.value)


def test_xml_to_text_drops_tables_and_unescapes():
    text = xml_to_text(
        "<P>본문 &amp; 설명</P><TABLE><TR><TD>표 값</TD></TR></TABLE><P>둘째</P>"
    )

    assert text == "본문 & 설명\n둘째"


def test_business_sections_selects_configured_sections():
    sections = business_sections(XML, REPORT_CONFIG["sections"])

    assert [title for title, _ in sections] == ["1. 사업의 개요", "4. 매출 및 수주상황"]
    assert "11,587" not in sections[0][1]
    assert "나. 판매 경로\n딜러를 통해 고객사에 납품합니다 & 직접 판매합니다." == (
        sections[1][1]
    )
    assert business_sections("<DOCUMENT></DOCUMENT>", ["사업의 개요"]) == []


def test_chunk_text_overlaps_and_respects_size():
    text = "가나다라마바사아자차. " * 30
    chunks = chunk_text(text, 100, 20)

    assert all(len(c) <= 100 for c in chunks)
    assert len(chunks) > 1
    assert chunks[0][-10:].strip() in chunks[1]
    assert chunk_text("짧은 글", 100, 20) == ["짧은 글"]


def test_build_company_documents_links_ideas_by_terms():
    documents, selection = build_company_documents(META, XML, REPORT_CONFIG, IDEA_TERMS)

    assert selection["linked_idea_ids"] == ["SF-01"]
    assert selection["matched_terms"]["SF-03"] == {}
    assert {d.evidence_nature for d in documents if "매출" in d.title} == {
        "purchase_signal"
    }
    overview = next(d for d in documents if "사업의 개요" in d.title)
    assert overview.evidence_nature == "company_claim"
    assert overview.source_type == "dart"
    assert overview.period == "FY2025"
    assert overview.published_at == 20260318
    assert overview.idea_ids == ["SF-01"]
    assert overview.source_id == "dart-20260318000001-1-0"
    assert overview.dup_group == "dart-20260318000001-1"
    assert overview.text.startswith("가상로봇 사업보고서(FY2025) 1. 사업의 개요\n")
    assert overview.url.endswith("rcpNo=20260318000001")


def test_build_company_documents_skips_unlinked_company():
    documents, selection = build_company_documents(
        {**META, "idea_ids": ["SF-03"]}, XML, REPORT_CONFIG, IDEA_TERMS
    )

    assert documents == []
    assert selection["linked_idea_ids"] == []


def test_build_documents_uses_current_config(tmp_path):
    raw = tmp_path / "raw"
    raw.mkdir()
    (raw / f"{META['rcept_no']}.xml").write_text(XML, encoding="utf-8")
    (raw / f"{META['rcept_no']}.json").write_text(
        json.dumps({**META, "idea_ids": ["SF-03"]}), encoding="utf-8"
    )
    (raw / "99990101000001.json").write_text(
        json.dumps({**META, "stock_code": "999999", "rcept_no": "99990101000001"}),
        encoding="utf-8",
    )
    config = tmp_path / "dart.yaml"
    config.write_text(
        json.dumps(
            {
                "report": REPORT_CONFIG,
                "idea_terms": IDEA_TERMS,
                "companies": [
                    {
                        "name": "가상로봇",
                        "stock_code": "000001",
                        "idea_ids": ["SF-01"],
                        "reason": "협동로봇 제조",
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    documents, selections = build_documents(raw, config)

    assert [s["name"] for s in selections] == ["가상로봇"]
    assert selections[0]["linked_idea_ids"] == ["SF-01"]
    assert documents and all(d.idea_ids == ["SF-01"] for d in documents)
