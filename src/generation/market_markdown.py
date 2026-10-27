"""MarketReport를 종합 보고서의 '시장 조사 및 분석 결과' 마크다운 섹션으로 바꾼다.

LLM을 부르지 않고 보고서 내용만 옮긴다. 판정·문장·근거를 바꾸거나 요약하지 않는다.
인용 번호는 UI와 같은 시장 근거 ID(M:{citation_id})로 쓴다.

사용 예:
    python -m src.generation.market_markdown data/samples/market_reports/SF-01.json
    python -m src.generation.market_markdown data/samples/market_reports/SF-01.json --out SF-01.md
"""

import argparse
from datetime import datetime
from pathlib import Path

from src.retrieval.market_relevance import DIMENSION_LABELS
from src.schemas import MarketEvidence, MarketReport

SECTION_TITLE = "시장 조사 및 분석 결과"

VERDICT_LABELS = {
    "confirmed": "확인됨",
    "signal_only": "신호만 확인",
    "unverified": "미확인",
}
CLAIM_LABELS = {
    "fact": "사실",
    "user_claim": "사용자 주장",
    "ai_hypothesis": "AI 가설",
}
NATURE_LABELS = {
    "direct_demand": "직접 수요",
    "purchase_signal": "구매 신호",
    "indirect_demand": "간접 수요",
    "business_signal": "사업 신호",
    "estimate": "추정치",
    "company_claim": "기업 주장",
}
GRADE_LABELS = {"high": "상", "medium": "중", "low": "하"}

EVIDENCE_NOTE = (
    "뉴스·기업 자료는 사업 신호이며 고객의 구매 의사를 직접 보여 주는 근거가 아니다. "
    "수요 '확인됨'은 고객 검증 자료(인터뷰·설문·파일럿·LOI)가 있을 때만 나온다."
)


def citation(citation_id: int) -> str:
    """시장 근거 인용 표기. UI의 근거 ID(M:번호)와 같다."""
    return f"M:{citation_id}"


def format_date(value: int | None) -> str:
    """YYYYMMDD 정수를 YYYY-MM-DD로 바꾼다. 값이 없으면 '미확인'."""
    if not value:
        return "미확인"
    return datetime.strptime(str(value), "%Y%m%d").strftime("%Y-%m-%d")


def cell(text: str | None) -> str:
    """표 칸에 넣을 수 있게 줄바꿈과 '|'를 정리한다."""
    return " ".join(str(text or "").split()).replace("|", "\\|")


def evidence_row(e: MarketEvidence) -> str:
    """근거 1건을 근거 목록 표의 한 행으로 만든다."""
    title = f"[{cell(e.title)}]({e.url})" if e.url else cell(e.title)
    return (
        f"| {citation(e.citation_id)} | {title} | {cell(e.publisher)}"
        f" | {format_date(e.published_at)} | {NATURE_LABELS[e.evidence_nature]}"
        f" | {GRADE_LABELS[e.reliability]}·{GRADE_LABELS[e.recency]}"
        f" | {cell(e.quote)} |"
    )


def market_report_to_markdown(report: MarketReport, heading_level: int = 2) -> str:
    """MarketReport를 마크다운 섹션 문자열로 바꾼다.

    heading_level은 섹션 제목의 '#' 개수이며, 하위 제목은 한 단계 아래로 쓴다.
    completed가 아니면 상태와 미확인 사항·오류 안내만 쓴다.
    """
    h, sub = "#" * heading_level, "#" * (heading_level + 1)
    lines = [
        f"{h} {SECTION_TITLE}",
        "",
        f"- 분석 기준일: {format_date(report.data_as_of)}",
        f"- 검색 범위: {cell(report.search_scope)}",
    ]

    if report.status == "no_results":
        lines += ["", "검색 범위에서 시장 근거를 찾지 못해 차원별 판정을 하지 않았다."]
    elif report.status == "error":
        lines += [
            "",
            "시장 조사 중 오류가 발생해 결과를 만들지 못했다.",
            f"- 오류: {cell(report.error_message)}",
        ]
    else:
        lines += _dimension_sections(report, sub)

    if report.unknowns:
        lines += ["", f"{sub} 미확인 사항", ""]
        lines += [f"- {cell(u)}" for u in report.unknowns]

    if report.status == "completed" and report.evidence:
        lines += [
            "",
            f"{sub} 근거 목록",
            "",
            "| 번호 | 제목 | 출처 | 발행일 | 근거 성격 | 신뢰도·최신성 | 인용문 |",
            "|---|---|---|---|---|---|---|",
        ]
        lines += [evidence_row(e) for e in report.evidence]
        lines += ["", f"> {EVIDENCE_NOTE}"]
    return "\n".join(lines) + "\n"


def _dimension_sections(report: MarketReport, sub: str) -> list[str]:
    """판정 요약 표와 차원별 문장·검증 과제를 만든다."""
    lines = [
        "",
        f"{sub} 차원별 판정 요약",
        "",
        "| 차원 | 판정 | 인용 근거 |",
        "|---|---|---|",
    ]
    for d in report.dimensions:
        cited = dict.fromkeys(i for c in d.claims for i in c.citation_ids)
        refs = ", ".join(citation(i) for i in cited) or "-"
        lines.append(
            f"| {DIMENSION_LABELS[d.dimension]} | {VERDICT_LABELS[d.verdict]} | {refs} |"
        )

    for d in report.dimensions:
        lines += [
            "",
            f"{sub} {DIMENSION_LABELS[d.dimension]}: {VERDICT_LABELS[d.verdict]}",
            "",
        ]
        if not d.claims:
            lines.append("- 근거로 쓸 수 있는 문장이 없다.")
        for c in d.claims:
            refs = " ".join(f"[{citation(i)}]" for i in c.citation_ids)
            lines.append(
                f"- [{CLAIM_LABELS[c.claim_type]}] {cell(c.statement)}"
                + (f" {refs}" if refs else "")
            )
        if d.next_check:
            lines.append(f"- 다음 검증 과제: {cell(d.next_check)}")
    return lines


def main() -> None:
    """MarketReport JSON 파일을 마크다운으로 바꿔 출력하거나 저장한다."""
    parser = argparse.ArgumentParser(description="MarketReport JSON → 마크다운 섹션")
    parser.add_argument("report", type=Path, help="MarketReport JSON 파일")
    parser.add_argument(
        "--out", type=Path, help="마크다운 저장 경로 (없으면 화면 출력)"
    )
    args = parser.parse_args()

    report = MarketReport.model_validate_json(args.report.read_text(encoding="utf-8"))
    markdown = market_report_to_markdown(report)
    if args.out:
        args.out.write_text(markdown, encoding="utf-8")
        print(f"-> {args.out}")
    else:
        print(markdown)


if __name__ == "__main__":
    main()
