"""수집한 DART 사업보고서에서 '사업의 내용' 본문을 추출해 청크 단위 MarketDocument JSONL로 저장한다.

- 입력: data/market/raw/dart/{rcept_no}.xml·.json (dart_client 수집 결과)
- 'II. 사업의 내용'의 하위 섹션 중 설정한 섹션(사업의 개요·주요 제품·매출·주요계약·기타 참고사항)만 쓴다.
- 표는 제외하고 본문 문단만 쓴다. 표의 단위·합계 구분을 보존하는 추출은 별도 작업이다(#29).
- 섹션 본문을 chunk_size자·chunk_overlap자 겹침으로 나누고, 청크마다 MarketDocument 1건을 만든다.
  같은 섹션의 청크는 dup_group을 공유해 검색 결과에 섹션당 1건만 남는다.
- 기업-아이디어 연결은 설정의 idea_ids 중 '사업의 내용'에 idea_terms 용어가 나오는 것만 남기고,
  선정 근거(용어별 등장 횟수)를 data/market/processed/dart_selection.json에 저장한다.
- 근거 성격은 모두 기업 주장(company_claim)이다. 표를 뺀 '매출 및 수주상황' 본문은 판매 경로·
  결제 조건·판매 전략 같은 기업 설명이고, 실제 판매 실적은 표에 있다.
  공시일(published_at)과 보고 대상 사업연도(period)를 구분해 저장한다.
- 출력: data/market/processed/dart_docs.jsonl
- 시장 재무 현황용으로 '연구개발활동' 섹션의 연구개발비용 표에서 3개 연도 금액을 뽑는다
  (extract_rnd_expense).

사용 예:
    python -m src.ingestion.dart_processor
"""

import argparse
import html
import json
import re
from pathlib import Path

from src.ingestion.dart_client import CONFIG_PATH, RAW_DIR, load_dart_config
from src.schemas import MarketDocument

ROOT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_PATH = ROOT_DIR / "data" / "market" / "processed" / "dart_docs.jsonl"
SELECTION_PATH = ROOT_DIR / "data" / "market" / "processed" / "dart_selection.json"
DART_RELIABILITY = "high"
DART_LICENSE = "OpenDART 공시 원문 발췌(사업의 내용 본문, 표 제외)"
VIEWER_URL = "https://dart.fss.or.kr/dsaf001/main.do?rcpNo={rcept_no}"

_BUSINESS_RE = re.compile(
    r"<SECTION-1[^>]*>\s*<TITLE[^>]*>[^<]*사업의 내용\s*</TITLE>(.*?)</SECTION-1>",
    re.S,
)
_SECTION2_RE = re.compile(
    r"<SECTION-2[^>]*>\s*<TITLE[^>]*>(.*?)</TITLE>(.*?)</SECTION-2>", re.S
)
_TABLE_RE = re.compile(r"<TABLE-GROUP\b.*?</TABLE-GROUP>|<TABLE\b.*?</TABLE>", re.S)
_IMAGE_RE = re.compile(r"<IMAGE\b.*?</IMAGE>", re.S)
_BREAK_RE = re.compile(r"</P>|<BR\s*/?>|</TITLE>|</SPAN>", re.I)
_TAG_RE = re.compile(r"<[^>]+>")
# 청크 경계로 쓰는 줄 끝과 문장 끝('다.' 뒤 공백 1자 포함). 문장 끝 뒤에 공백 없이 이어지는 경우도 포함한다.
_BOUNDARY_RE = re.compile(r"\n|다\. ?")


def xml_to_text(fragment: str) -> str:
    """공시 XML 조각에서 표·이미지를 빼고 문단 단위 텍스트로 바꾼다."""
    fragment = _IMAGE_RE.sub("", _TABLE_RE.sub("", fragment))
    text = html.unescape(_TAG_RE.sub("", _BREAK_RE.sub("\n", fragment)))
    lines = (" ".join(line.split()) for line in text.splitlines())
    return "\n".join(line for line in lines if line)


_RND_SECTION_RE = re.compile(
    r"<SECTION-2[^>]*>\s*<TITLE[^>]*>[^<]*연구개발[^<]*</TITLE>(.*?)</SECTION-2>", re.S
)
_ROW_RE = re.compile(r"<TR\b.*?</TR>", re.S)
_CELL_RE = re.compile(r"<T[DHE]\b[^>]*>(.*?)</T[DHE]>", re.S)
_AMOUNT_RE = re.compile(r"^\(?-?[\d,]+\)?")
_UNIT_RE = re.compile(r"단위\s*[:：]?\s*(백만원|천원|억원|원)")
UNIT_WON = {"원": 1, "천원": 1_000, "백만원": 1_000_000, "억원": 100_000_000}
# 연구개발비용 합계 행의 이름(공백 제거). 정부보조금 차감 전 총액을 앞에 둔다.
_RND_TOTAL_LABELS = [
    re.compile(r"정부보조금차감전"),
    re.compile(r"^연구개발비용?(총계|합계)"),
    re.compile(r"^연구개발비용?계"),
    re.compile(r"^(합계|소계|계)"),
]


def _cell_text(cell: str) -> str:
    return " ".join(html.unescape(_TAG_RE.sub(" ", cell)).split())


def _amount(text: str) -> int | None:
    """'8,411,060'·'(64,470)'·'1,016,506(4.0%)'의 앞 금액을 정수로 바꾼다. '-'나 숫자가 아니면 None."""
    match = _AMOUNT_RE.match(text.replace(" ", ""))
    if not match or not any(c.isdigit() for c in match.group()):
        return None
    value = match.group().strip("()").replace(",", "")
    return -int(value) if match.group().startswith("(") else int(value)


def extract_rnd_expense(
    xml: str, fiscal_year: int
) -> tuple[dict[int, int], str] | None:
    """사업보고서 '연구개발활동' 섹션 표에서 연구개발비용 합계를 연도별 원 단위로 뽑는다.

    반환: ({사업연도: 금액(원)}, 근거 설명). 정부보조금 차감 전 총액 행을 우선하고, 차감 후 행은 쓰지
    않는다. 표 안이나 바로 위 제목에 '연구개발'이 나오는 표만 보고, 표 앞뒤의 '단위'로 원 단위로 바꾼다. 단위·합계 행·3개 연도
    금액을 갖춘 표가 없으면 None.
    연도는 표 머리의 'YYYY년'을 쓰고, 없으면 fiscal_year부터 최신순으로 본다.
    """
    section = _RND_SECTION_RE.search(xml)
    if not section:
        return None
    body = section.group(1)
    for table in re.finditer(r"<TABLE\b.*?</TABLE>", body, re.S):
        rows = [
            [_cell_text(c) for c in _CELL_RE.findall(row)]
            for row in _ROW_RE.findall(table.group())
        ]
        # 단위는 표 바로 위 문단이나 단위만 적은 작은 표에 있어, 표를 지우지 않고 태그만 뺀다.
        around = _cell_text(body[max(0, table.start() - 600) : table.start()])
        title = "".join(around[-150:].split()) + "".join("".join(r) for r in rows)
        if "연구개발" not in title.replace(" ", ""):
            continue  # 같은 섹션의 주요계약 표 등
        found = []
        for index, cells in enumerate(rows):
            amounts = [a for a in (_amount(c) for c in cells) if a is not None]
            label_cells = [c for c in cells if _amount(c) is None and c != "-"]
            label = "".join("".join(label_cells).split())
            if len(amounts) < 3 or "차감후" in label or "비율" in label[:6]:
                continue
            for rank, pattern in enumerate(_RND_TOTAL_LABELS):
                if pattern.search(label):
                    found.append((rank, index, label, amounts[:3]))
                    break
        if not found:
            continue
        _, index, label, amounts = min(found)
        unit = _UNIT_RE.findall(around) or _UNIT_RE.findall(
            " ".join(" ".join(r) for r in rows)
        )
        if not unit:
            continue
        header = " ".join(" ".join(r) for r in rows[:index])
        years = [int(y) for y in dict.fromkeys(re.findall(r"(20\d\d)년", header))]
        if len(years) < 3:
            years = [fiscal_year, fiscal_year - 1, fiscal_year - 2]
        scale = UNIT_WON[unit[-1]]
        basis = f"사업보고서 연구개발활동 표 '{label}' ({unit[-1]})"
        return {y: a * scale for y, a in zip(years[:3], amounts)}, basis
    return None


def business_sections(xml: str, keywords: list[str]) -> list[tuple[str, str]]:
    """'사업의 내용'에서 제목에 keywords가 들어간 하위 섹션의 (제목, 본문)을 원문 순서대로 반환한다.

    '사업의 내용' 장이 없으면 빈 목록이다.
    """
    match = _BUSINESS_RE.search(xml)
    if not match:
        return []
    sections = []
    for raw_title, body in _SECTION2_RE.findall(match.group(1)):
        title = " ".join(html.unescape(_TAG_RE.sub("", raw_title)).split())
        if any(k in title for k in keywords):
            text = xml_to_text(body)
            if text:
                sections.append((title, text))
    return sections


def next_chunk_start(text: str, start: int, end: int, overlap: int) -> int:
    """다음 청크 시작 위치. 겹침 구간(end-overlap ~ end) 안의 첫 줄·문장 끝 바로 뒤에서 시작해
    청크가 문장 중간에서 시작하지 않게 한다. 겹침 구간에 줄·문장 끝이 없으면 end-overlap이다.
    """
    back = max(end - overlap, start + 1)
    boundary = _BOUNDARY_RE.search(text, back, end)
    return boundary.end() if boundary else back


def chunk_text(text: str, size: int, overlap: int) -> list[str]:
    """텍스트를 size자 이하 청크로 나눈다. 가능하면 줄·문장 끝에서 자르고, 다음 청크는 최대
    overlap자 겹치되 줄·문장 시작에서 시작한다."""
    chunks, start = [], 0
    while start < len(text):
        end = min(start + size, len(text))
        if end < len(text):
            window = start + size // 2
            cuts = [m.end() for m in _BOUNDARY_RE.finditer(text, window, end)]
            if cuts:
                end = cuts[-1]
        chunk = text[start:end].strip()
        if chunk:
            chunks.append(chunk)
        if end >= len(text):
            break
        start = next_chunk_start(text, start, end, overlap)
    return chunks


def matched_terms(text: str, idea_terms: dict[str, list[str]]) -> dict[str, dict]:
    """아이디어별 용어 등장 횟수를 센다. {idea_id: {용어: 횟수}} (0회 용어 제외)."""
    return {
        idea_id: {t: text.count(t) for t in terms if text.count(t)}
        for idea_id, terms in idea_terms.items()
    }


def fiscal_period(period: str | None) -> str | None:
    """'2025.12' 형식의 사업연도 말을 'FY2025'로 바꾼다."""
    return f"FY{period[:4]}" if period else None


def build_company_documents(
    meta: dict, xml: str, report_config: dict, idea_terms: dict[str, list[str]]
) -> tuple[list[MarketDocument], dict]:
    """보고서 1건을 청크 MarketDocument 목록과 선정 근거(selection) 사전으로 바꾼다.

    '사업의 내용'에 idea_terms 용어가 없는 아이디어는 연결하지 않으며, 연결된 아이디어가
    하나도 없으면 문서를 만들지 않는다.
    """
    sections = business_sections(xml, report_config["sections"])
    full_text = "\n".join(text for _, text in sections)
    terms = matched_terms(full_text, idea_terms)
    linked = [i for i in meta["idea_ids"] if terms.get(i)]
    selection = {
        "name": meta["name"],
        "rcept_no": meta["rcept_no"],
        "report_nm": meta["report_nm"],
        "reason": meta["reason"],
        "configured_idea_ids": meta["idea_ids"],
        "linked_idea_ids": linked,
        "matched_terms": {i: terms.get(i, {}) for i in meta["idea_ids"]},
        "sections": [title for title, _ in sections],
    }
    if not linked:
        return [], selection

    period = fiscal_period(meta.get("period"))
    documents = []
    for section_no, (title, text) in enumerate(sections, 1):
        doc_title = f"{meta['name']} 사업보고서({period}) {title}"
        group = f"dart-{meta['rcept_no']}-{section_no}"
        for chunk_no, chunk in enumerate(
            chunk_text(
                text, report_config["chunk_size"], report_config["chunk_overlap"]
            )
        ):
            documents.append(
                MarketDocument(
                    source_id=f"{group}-{chunk_no}",
                    source_type="dart",
                    title=doc_title,
                    publisher=f"{meta['name']} (DART 사업보고서)",
                    text=f"{doc_title}\n{chunk}",
                    url=VIEWER_URL.format(rcept_no=meta["rcept_no"]),
                    published_at=meta["rcept_dt"],
                    period=period,
                    collected_at=meta["collected_at"],
                    section=f"II. 사업의 내용 > {title} (본문, 표 제외)",
                    reliability=DART_RELIABILITY,
                    evidence_nature="company_claim",
                    dup_group=group,
                    license=DART_LICENSE,
                    idea_ids=linked,
                )
            )
    return documents, selection


def build_documents(
    raw_dir: Path = RAW_DIR, config_path: Path = CONFIG_PATH
) -> tuple[list[MarketDocument], list[dict]]:
    """raw_dir의 사업보고서를 MarketDocument 목록과 기업별 선정 근거 목록으로 만든다.

    관련 아이디어·선정 이유는 현재 설정을 따르며, 설정에 없는 기업의 원본은 건너뛴다.
    """
    config = load_dart_config(config_path)
    companies = {c["stock_code"]: c for c in config["companies"]}
    documents, selections = [], []
    for meta_path in sorted(raw_dir.glob("*.json")):
        if meta_path.name == "corp_codes.json":
            continue
        meta = json.loads(meta_path.read_text(encoding="utf-8"))
        company = companies.get(meta["stock_code"])
        if company is None:
            continue
        meta = {**meta, "idea_ids": company["idea_ids"], "reason": company["reason"]}
        xml = (raw_dir / f"{meta['rcept_no']}.xml").read_text(encoding="utf-8")
        docs, selection = build_company_documents(
            meta, xml, config["report"], config["idea_terms"]
        )
        documents.extend(docs)
        selections.append({**selection, "chunks": len(docs)})
    return documents, selections


def save_jsonl(documents: list[MarketDocument], path: Path = OUTPUT_PATH) -> Path:
    """MarketDocument 목록을 한 줄에 1건씩 JSONL로 저장한다. 기존 파일은 덮어쓴다."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for document in documents:
            f.write(document.model_dump_json() + "\n")
    return path


def main() -> None:
    """DART 원본을 정제해 dart_docs.jsonl·dart_selection.json으로 저장하고 기업별 결과를 출력한다."""
    parser = argparse.ArgumentParser(description="DART 사업보고서 정제")
    parser.add_argument("--raw-dir", type=Path, default=RAW_DIR)
    parser.add_argument("--output", type=Path, default=OUTPUT_PATH)
    args = parser.parse_args()

    documents, selections = build_documents(args.raw_dir)
    path = save_jsonl(documents, args.output)
    SELECTION_PATH.write_text(
        json.dumps(selections, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    for s in selections:
        dropped = sorted(set(s["configured_idea_ids"]) - set(s["linked_idea_ids"]))
        print(
            f"{s['name']}: 청크 {s['chunks']} · 연결 {s['linked_idea_ids']}"
            + (f" · 용어 없음으로 제외 {dropped}" if dropped else "")
            + f" · {s['matched_terms']}"
        )
    print(f"documents {len(documents)} -> {path}")


if __name__ == "__main__":
    main()
