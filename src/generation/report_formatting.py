"""Shared safe text formatting for generated report content."""

import html
import re
from datetime import datetime

from src.schemas import MarketReport, PatentReport

REPORT_STATUS_LABELS = {
    "completed": "완료",
    "partial": "부분 완료",
    "no_results": "결과 없음",
    "error": "오류",
}
RUN_STATE_LABELS = {
    **REPORT_STATUS_LABELS,
    "skipped": "실행 안 함",
    "timeout": "시간 초과",
}
CLAIM_TYPE_LABELS = {"independent": "독립", "dependent": "종속"}
PATENT_RELEVANCE_LABELS = {
    "high": "높음",
    "medium": "보통",
    "low": "낮음",
    "insufficient": "근거 부족",
}
PATENT_COMPONENT_STATUS_LABELS = {
    "overlap": "직접 대응",
    "partial": "부분 대응",
    "different": "차이 확인",
    "not_found": "제공 근거에서 미발견",
    "uncertain": "근거 부족",
}
PATENTABILITY_STATUS_LABELS = {
    "overlap_concern": "유사 청구항 주의",
    "potentially_distinct": "차별 구성 신호",
    "insufficient_evidence": "판단 근거 부족",
}
CONFIDENCE_LABELS = {"low": "낮음", "medium": "보통", "high": "높음"}

_MD_ESCAPES = {
    "\\": "\\\\",
    "`": "\\`",
    "*": "\\*",
    "_": "\\_",
    "[": "\\[",
    "]": "\\]",
    "$": "\\$",
    "#": "\\#",
}
_INLINE = str.maketrans(_MD_ESCAPES)
_TABLE = str.maketrans({**_MD_ESCAPES, "|": "\\|"})
_SAFE_URL = re.compile(r"https?://[^\s()<>\"'`]+")


def escape_md(value, *, table: bool = True) -> str:
    """외부·사용자 텍스트를 한 줄 마크다운 텍스트로 만든다. HTML·링크·수식 해석을 막는다.

    table=False는 표 칸 처리를 별도로 하는 렌더러(market_markdown.cell)에 넘길 때 쓴다.
    """
    text = html.escape(" ".join(str(value or "").split()), quote=False)
    return text.translate(_TABLE if table else _INLINE)


def safe_url(url: str | None) -> str | None:
    """http(s) 주소만 링크로 허용한다. 그 밖의 값은 None."""
    if url and _SAFE_URL.fullmatch(url.strip()):
        return url.strip()
    return None


def _format_yyyymmdd(value) -> str | None:
    """날짜 숫자를 보고서 표시용 ISO 날짜로 바꾸거나 비운다."""
    digits = re.sub(r"\D", "", str(value or ""))[:8]
    if len(digits) != 8:
        return None
    try:
        return datetime.strptime(digits, "%Y%m%d").strftime("%Y-%m-%d")
    except ValueError:
        return None


def evidence_period(market: MarketReport, patent: PatentReport) -> str:
    """보고서에 쓰인 근거의 발행일(특허는 공개일, 없으면 출원일) 범위."""
    dates = [_format_yyyymmdd(e.published_at) for e in market.evidence]
    dates += [
        _format_yyyymmdd(e.publication_date or e.application_date)
        for e in patent.evidence
    ]
    dates = sorted(d for d in dates if d)
    if not dates:
        return "미확인"
    return dates[0] if dates[0] == dates[-1] else f"{dates[0]} ~ {dates[-1]}"


def patent_location(evidence) -> str:
    """특허 근거의 원문 위치(청구항 번호·유형·인용항 또는 초록)."""
    if evidence.section != "claims":
        return "초록"
    if not evidence.claim_number:
        return "청구항(번호 미확인)"
    kind = CLAIM_TYPE_LABELS.get(evidence.claim_type or "", "유형 미확인")
    refs = (
        f", 인용 {'·'.join(str(n) for n in evidence.depends_on)}항"
        if evidence.depends_on
        else ""
    )
    return f"청구항 {evidence.claim_number} ({kind}{refs})"


def escaped_market_report(market: MarketReport) -> MarketReport:
    """시장 보고서의 외부 텍스트를 이스케이프하고 http(s)가 아닌 링크를 뺀 사본."""

    def esc(value):
        """시장 보고서의 문자열 하나를 안전한 Markdown 텍스트로 변환한다."""
        return escape_md(value, table=False) if value else value

    return market.model_copy(
        update={
            "search_scope": esc(market.search_scope),
            "error_message": esc(market.error_message),
            "unknowns": [esc(item) for item in market.unknowns],
            "evidence": [
                e.model_copy(
                    update={
                        "title": esc(e.title),
                        "publisher": esc(e.publisher),
                        "quote": esc(e.quote),
                        "section": esc(e.section),
                        "url": safe_url(e.url),
                    }
                )
                for e in market.evidence
            ],
            "dimensions": [
                d.model_copy(
                    update={
                        "next_check": esc(d.next_check),
                        "claims": [
                            c.model_copy(update={"statement": esc(c.statement)})
                            for c in d.claims
                        ],
                    }
                )
                for d in market.dimensions
            ],
        }
    )
