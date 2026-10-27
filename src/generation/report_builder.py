"""시장·특허 근거를 검토 질문 및 6개 기준에 연결해 통합 보고서를 구성한다."""

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

from src.generation.market_markdown import market_report_to_markdown
from src.schemas import IDEA_FIELDS, IdeaDraft, MarketReport, PatentReport

ROOT_DIR = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT_DIR / "prompts" / "report_generation.md"
MODEL = "gpt-4o-mini"
CRITERIA = [
    "사용 맥락",
    "해결 과제",
    "기술 구성",
    "요구 성능",
    "도입 제약",
    "근거 범위",
]
LINK_ATTEMPTS = 2
HOLD_SUMMARY = "질문별 연결 결과를 생성하지 못해 판단을 보류합니다."
BOTH_SIDES_SUMMARY = "시장·특허 양쪽 근거가 연결되지 않아 통합 판단을 보류합니다."

FIELD_LABELS = {
    "problem": "문제",
    "technology": "기술",
    "customers": "고객",
    "difference": "차별점",
    "revenue": "수익모델",
}
SOURCE_LABELS = {
    "extracted": "입력에서 추출",
    "user_answer": "재질문 답변",
    "unknown": "모름",
}
LINK_STATUS_LABELS = {"connected": "연결", "partial": "부분 연결", "hold": "판단 보류"}
REPORT_STATUS_LABELS = {"completed": "완료", "no_results": "결과 없음", "error": "오류"}
RUN_STATE_LABELS = {
    **REPORT_STATUS_LABELS,
    "skipped": "실행 안 함",
    "timeout": "시간 초과",
}
CLAIM_TYPE_LABELS = {"independent": "독립", "dependent": "종속"}

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


class CriterionLink(BaseModel):
    criterion: str
    assessment: str
    citation_ids: list[str] = Field(default_factory=list)
    next_check: str


class QuestionLink(BaseModel):
    question_id: str
    status: str = Field(pattern="^(connected|partial|hold)$")
    summary: str
    criteria: list[CriterionLink]


class LinkBatch(BaseModel):
    links: list[QuestionLink]


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


def hold_link(question_id: str, summary: str = HOLD_SUMMARY) -> QuestionLink:
    """6개 기준을 모두 '미확인'으로 둔 보류 연결을 만든다."""
    return QuestionLink(
        question_id=question_id,
        status="hold",
        summary=summary,
        criteria=[
            CriterionLink(
                criterion=criterion,
                assessment="미확인",
                citation_ids=[],
                next_check="시장·특허 근거 연결을 다시 실행",
            )
            for criterion in CRITERIA
        ],
    )


def call_report_llm(system_prompt: str, user_text: str) -> dict:
    load_dotenv(ROOT_DIR / ".env")
    response = OpenAI().chat.completions.create(
        model=MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
    )
    return json.loads(response.choices[0].message.content)


def _evidence_ids(market: MarketReport, patent: PatentReport) -> tuple[set, set]:
    market_ids = {f"M:{item.citation_id}" for item in market.evidence}
    patent_ids = {f"P:{item.citation_id}" for item in patent.evidence}
    return market_ids, patent_ids


def _apply_hold_rule(link: QuestionLink, market_ids: set, patent_ids: set) -> None:
    used = {cid for criterion in link.criteria for cid in criterion.citation_ids}
    if not (market_ids and patent_ids) or not (used & market_ids and used & patent_ids):
        link.status = "hold"
        link.summary = BOTH_SIDES_SUMMARY


def _link_payload(questions: list[dict], market: MarketReport, patent: PatentReport):
    return {
        "questions": questions,
        "market": market.model_dump(),
        "patent": patent.model_dump(),
        "criteria": CRITERIA,
    }


def build_question_links(
    questions: list[dict],
    market: MarketReport,
    patent: PatentReport,
    llm_fn: Callable | None = None,
) -> list[QuestionLink]:
    """검토 질문을 근거와 연결한다. 양쪽 영역 중 하나라도 비면 해당 질문은 보류한다."""
    if not questions:
        return []
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    payload = _link_payload(questions, market, patent)
    batch = LinkBatch.model_validate(
        (llm_fn or call_report_llm)(prompt, json.dumps(payload, ensure_ascii=False))
    )
    wanted_ids = [item["id"] for item in questions]
    actual_ids = [link.question_id for link in batch.links]
    if set(actual_ids) != set(wanted_ids) or len(actual_ids) != len(wanted_ids):
        raise ValueError("Question evidence links must map one-to-one to questions")
    market_ids, patent_ids = _evidence_ids(market, patent)
    allowed_ids = market_ids | patent_ids
    for link in batch.links:
        if len(link.criteria) != len(CRITERIA) or {
            c.criterion for c in link.criteria
        } != set(CRITERIA):
            raise ValueError("Each question needs all six evidence criteria")
        for criterion in link.criteria:
            unknown = set(criterion.citation_ids) - allowed_ids
            if unknown:
                raise ValueError(f"Unknown integrated citation ids: {sorted(unknown)}")
        _apply_hold_rule(link, market_ids, patent_ids)
    return batch.links


def salvage_question_links(
    raw, questions: list[dict], market: MarketReport, patent: PatentReport
) -> tuple[list[QuestionLink], list[str]]:
    """검증에 실패한 LLM 응답에서 쓸 수 있는 질문 연결만 살린다.

    6개 기준을 모두 갖춘 질문은 허용되지 않은 인용 ID만 빼고 남기며, 나머지 질문은 보류한다.
    """
    market_ids, patent_ids = _evidence_ids(market, patent)
    allowed_ids = market_ids | patent_ids
    candidates = {}
    for item in (raw or {}).get("links", []) if isinstance(raw, dict) else []:
        try:
            link = QuestionLink.model_validate(item)
        except ValueError:
            continue
        candidates.setdefault(link.question_id, link)
    links, held = [], []
    for question in questions:
        link = candidates.get(question["id"])
        if link is None or {c.criterion for c in link.criteria} != set(CRITERIA):
            links.append(hold_link(question["id"]))
            held.append(question["id"])
            continue
        link.criteria = [
            next(c for c in link.criteria if c.criterion == name) for name in CRITERIA
        ]
        for criterion in link.criteria:
            criterion.citation_ids = [
                cid for cid in criterion.citation_ids if cid in allowed_ids
            ]
        _apply_hold_rule(link, market_ids, patent_ids)
        links.append(link)
    warnings = [f"질문 연결 형식 오류로 보류한 질문: {', '.join(held)}"] if held else []
    return links, warnings


def link_questions_with_retry(
    questions: list[dict],
    market: MarketReport,
    patent: PatentReport,
    llm_fn: Callable | None = None,
    attempts: int = LINK_ATTEMPTS,
) -> tuple[list[QuestionLink], list[str]]:
    """질문 연결을 검증하며 최대 attempts회 생성하고, 그래도 실패하면 질문 단위로 보류한다.

    재시도 때는 직전 검증 오류를 입력에 덧붙인다. 반환값은 (연결 목록, 경고 목록)이다.
    """
    if not questions:
        return [], []
    base_fn = llm_fn or call_report_llm
    last_raw, last_error = None, None
    for attempt in range(attempts):

        def recording_fn(system_prompt, user_text, _feedback=last_error):
            nonlocal last_raw
            if _feedback:
                user_text += (
                    f"\n\n직전 응답 검증 오류: {_feedback}\n"
                    "모든 질문 ID를 한 번씩, 6개 기준 이름 그대로, 입력에 있는 인용 ID만 써서 다시 작성하라."
                )
            last_raw = base_fn(system_prompt, user_text)
            return last_raw

        try:
            return build_question_links(questions, market, patent, recording_fn), []
        except ValueError as exc:
            last_error = str(exc)[:300]
        except Exception as exc:  # LLM 호출 실패는 재시도 없이 질문 전체를 보류한다
            return [hold_link(q["id"]) for q in questions], [
                f"질문 연결 호출 실패({type(exc).__name__})로 모든 질문을 보류했습니다."
            ]
    links, warnings = salvage_question_links(last_raw, questions, market, patent)
    return links, [f"질문 연결 검증 {attempts}회 실패: {last_error}", *warnings]


def _format_yyyymmdd(value) -> str | None:
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


def _brief_lines(draft: IdeaDraft) -> list[str]:
    lines = ["## 확정 브리프", "", "| 항목 | 내용 | 출처 |", "|---|---|---|"]
    for field in IDEA_FIELDS:
        source = SOURCE_LABELS.get(draft.field_sources.get(field, ""), "입력에서 추출")
        value = getattr(draft, field) or "모름"
        lines.append(f"| {FIELD_LABELS[field]} | {escape_md(value)} | {source} |")
    return lines + [""]


def _run_lines(runs: dict) -> list[str]:
    lines = [
        "## 분석 실행 상태",
        "",
        "| 영역 | 상태 | 소요 시간 | 메모 |",
        "|---|---|---|---|",
    ]
    for label, run in runs.items():
        if run is None:
            continue
        seconds = f"{run.seconds:.1f}초" if run.seconds is not None else "-"
        state = RUN_STATE_LABELS.get(run.state, run.state)
        lines.append(
            f"| {label} | {state} | {seconds} | {escape_md(run.message) or '-'} |"
        )
    return lines + [""]


def _patent_lines(patent: PatentReport) -> list[str]:
    lines = [
        "## 특허 조사",
        "",
        f"- 상태: {REPORT_STATUS_LABELS.get(patent.status, patent.status)}",
        f"- 범위: {escape_md(patent.search_scope)}",
    ]
    if patent.error_message:
        lines.append(f"- 오류: {escape_md(patent.error_message)}")
    comparisons = {c.citation_id: c for c in patent.comparisons}
    for evidence in patent.evidence:
        comparison = comparisons.get(evidence.citation_id)
        url = safe_url(evidence.source_url)
        dates = " · ".join(
            f"{label} {value}"
            for label, value in (
                ("출원", _format_yyyymmdd(evidence.application_date)),
                ("공개", _format_yyyymmdd(evidence.publication_date)),
            )
            if value
        )
        lines += [
            "",
            f"### [P:{evidence.citation_id}] {escape_md(evidence.title)}",
            "",
            f"- 문헌: {escape_md(evidence.patent_id)}"
            + (f" · {dates}" if dates else "")
            + (f" · [원문]({url})" if url else " · 원문 링크 미확인"),
            f"- 근거 원문 ({patent_location(evidence)}): {escape_md(evidence.quote)}",
        ]
        if comparison:
            lines += [
                f"- 유사점: {escape_md(comparison.similarity)}",
                f"- 차이점: {escape_md(comparison.difference)}",
                f"- 미확인: {escape_md(comparison.uncertainty)}",
            ]
    if patent.unknowns:
        lines += ["", "### 특허 미확인 사항", ""]
        lines += [f"- {escape_md(item)}" for item in patent.unknowns]
    return lines + [""]


def integrated_report_markdown(
    title: str,
    questions: list[dict],
    links: list[QuestionLink],
    market: MarketReport,
    patent: PatentReport,
    *,
    draft: IdeaDraft | None = None,
    runs: dict | None = None,
    analyzed_on: int | None = None,
    market_collected_at: int | None = None,
    warnings: list[str] | None = None,
) -> str:
    """통합 보고서의 질문 연결, 출처, 상태를 Markdown으로 렌더링한다.

    외부·사용자 텍스트는 escape_md로, 시장 절은 이스케이프한 사본을 market_report_to_markdown으로 그린다.
    """
    by_id = {link.question_id: link for link in links}
    analyzed = _format_yyyymmdd(analyzed_on) or datetime.now().strftime("%Y-%m-%d")
    collected = _format_yyyymmdd(market_collected_at) or "미확인"
    lines = [
        f"# {escape_md(title) or '사업기획 검토 보고서'}",
        "",
        f"> 실제 분석 결과 · 분석일 {analyzed} · 시장 자료 수집 기준 {collected}"
        f" · 근거 발행 범위 {evidence_period(market, patent)}",
        "> 근거와 미확인 사항을 정리한 자료이며, LLM 결과는 실행마다 달라질 수 있다.",
        "",
    ]
    if draft is not None:
        lines += _brief_lines(draft)
    if runs:
        lines += _run_lines(runs)
    if warnings:
        lines += ["## 분석 경고", ""]
        lines += [f"- {escape_md(item)}" for item in warnings]
        lines.append("")
    lines += ["## 검토 질문별 근거 연결", ""]
    for question in questions:
        link = by_id.get(question["id"])
        if not link:
            continue
        lines += [
            f"### {escape_md(question['id'])} · {escape_md(question['question'])}",
            "",
            f"- 상태: {LINK_STATUS_LABELS.get(link.status, link.status)}",
            f"- 요약: {escape_md(link.summary)}",
        ]
        for criterion in link.criteria:
            refs = (
                ", ".join(f"[{escape_md(cid)}]" for cid in criterion.citation_ids)
                or "근거 없음"
            )
            lines.append(
                f"- {escape_md(criterion.criterion)}: {escape_md(criterion.assessment)}"
                f" ({refs}) · 다음 확인: {escape_md(criterion.next_check)}"
            )
        lines.append("")
    lines += _patent_lines(patent)
    lines.append(market_report_to_markdown(escaped_market_report(market), 2))
    lines += [
        "## 판단 범위",
        "",
        "이 보고서는 조사 근거와 미확인 사항을 정리하며 특허성·신규성·진보성·침해 여부 또는 사업성의 최종 판정을 제공하지 않습니다.",
    ]
    return "\n".join(lines) + "\n"
