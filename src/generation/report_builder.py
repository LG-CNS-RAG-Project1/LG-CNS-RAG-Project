"""시장·특허 근거를 검토 질문 및 6개 기준에 연결해 통합 보고서를 구성한다."""

import html
import json
import re
from datetime import datetime
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field, field_validator
from src.llm_client import chat_model, get_openai_client

from src.generation.business_review import (
    BusinessReview,
    RECOMMENDATION_LABELS,
)
from src.retrieval.market_relevance import DIMENSION_LABELS
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
    "ai_hypothesis": "AI 검증 가설",
    "unknown": "모름",
}
LINK_STATUS_LABELS = {"connected": "연결", "partial": "부분 연결", "hold": "판단 보류"}
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


class CriterionLink(BaseModel):
    criterion: str
    assessment: str = "미확인"
    citation_ids: list[str] = Field(default_factory=list)
    next_check: str = ""

    @field_validator("assessment", "next_check", mode="before")
    @classmethod
    def _null_text(cls, value):
        """LLM이 빈 값을 null로 돌려줘도 연결 전체를 버리지 않는다."""
        return "" if value is None else value

    @field_validator("citation_ids", mode="before")
    @classmethod
    def _null_ids(cls, value):
        return [] if value is None else value


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
    response = get_openai_client().chat.completions.create(
        model=chat_model(MODEL),
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
    fields = [
        *((field, FIELD_LABELS[field], getattr(draft, field)) for field in IDEA_FIELDS),
        ("current_alternative", "현재 대안", draft.current_alternative),
        ("target_segment", "목표 세그먼트", draft.target_segment),
        (
            "technical_components",
            "기술 구성요소",
            ", ".join(draft.technical_components),
        ),
        ("value_hypotheses", "가치 가설", "; ".join(draft.value_hypotheses)),
    ]
    for field, label, field_value in fields:
        source = SOURCE_LABELS.get(draft.field_sources.get(field, ""), "입력에서 추출")
        value = field_value or "모름"
        lines.append(f"| {label} | {escape_md(value)} | {source} |")
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
    evidence_by_id = {item.citation_id: item for item in patent.evidence}
    comparisons = {c.citation_id: c for c in patent.comparisons}
    if patent.patent_reviews:
        for review in patent.patent_reviews:
            first = (
                evidence_by_id[review.citation_ids[0]] if review.citation_ids else None
            )
            dates = " · ".join(
                f"{label} {value}"
                for label, value in (
                    (
                        "출원",
                        _format_yyyymmdd(first.application_date) if first else None,
                    ),
                    (
                        "공개",
                        _format_yyyymmdd(first.publication_date) if first else None,
                    ),
                )
                if value
            )
            url = safe_url(first.source_url) if first else None
            lines += [
                "",
                f"### {escape_md(review.title)}",
                "",
                f"- 문헌: {escape_md(review.patent_id)} · 관련성 {PATENT_RELEVANCE_LABELS[review.relevance]}"
                + (f" · {dates}" if dates else "")
                + (f" · [원문]({url})" if url else " · 원문 링크 미확인"),
                f"- 관련성 근거: {escape_md(review.relevance_reason)}",
                f"- 특허 단위 요약: {escape_md(review.overall_summary)}",
                "",
                "| 아이디어 구성 | 비교 상태 | 공통점 | 차이점 | 근거 | 미확인 |",
                "|---|---|---|---|---|---|",
            ]
            for comparison in review.component_comparisons:
                refs = (
                    ", ".join(f"P:{cid}" for cid in comparison.citation_ids) or "없음"
                )
                lines.append(
                    f"| {escape_md(comparison.idea_component)} | {PATENT_COMPONENT_STATUS_LABELS[comparison.status]} | "
                    f"{escape_md(comparison.overlap)} | {escape_md(comparison.difference)} | "
                    f"{refs} | {escape_md(comparison.uncertainty)} |"
                )
            for citation_id in review.citation_ids:
                evidence = evidence_by_id[citation_id]
                lines += [
                    "",
                    f"- [P:{citation_id}] {patent_location(evidence)} 원문: {escape_md(evidence.quote)}",
                ]
            for item in review.watchouts:
                lines.append(f"- 주의: {escape_md(item)}")
            for item in review.unknowns:
                lines.append(f"- 미확인: {escape_md(item)}")
    else:
        for evidence in patent.evidence:
            comparison = comparisons.get(evidence.citation_id)
            url = safe_url(evidence.source_url)
            lines += [
                "",
                f"### [P:{evidence.citation_id}] {escape_md(evidence.title)}",
                "",
                f"- 문헌: {escape_md(evidence.patent_id)}"
                + (f" · [원문]({url})" if url else " · 원문 링크 미확인"),
                f"- 근거 원문 ({patent_location(evidence)}): {escape_md(evidence.quote)}",
            ]
            if comparison:
                lines += [
                    f"- 유사점: {escape_md(comparison.similarity)}",
                    f"- 차이점: {escape_md(comparison.difference)}",
                    f"- 미확인: {escape_md(comparison.uncertainty)}",
                ]
    if patent.patentability_precheck:
        precheck = patent.patentability_precheck
        refs = ", ".join(f"P:{cid}" for cid in precheck.citation_ids) or "없음"
        lines += [
            "",
            "### 등록 관련 예비 신호 (법적 판단 아님)",
            "",
            f"- 상태: {PATENTABILITY_STATUS_LABELS[precheck.status]}",
            f"- 요약: {escape_md(precheck.summary)} ({refs})",
        ]
        lines += [
            f"- 차별점 가설: {escape_md(item)}"
            for item in precheck.distinction_hypotheses
        ]
        lines += [
            f"- 전문가 확인 질문: {escape_md(item)}"
            for item in precheck.expert_questions
        ]
        lines += [f"- 한계: {escape_md(item)}" for item in precheck.limitations]
    if patent.unknowns:
        lines += ["", "### 특허 미확인 사항", ""]
        lines += [f"- {escape_md(item)}" for item in patent.unknowns]
    return lines + [""]


def _business_review_lines(review: BusinessReview) -> list[str]:
    lines = [
        "## 한눈에 보는 사업 실행 검토",
        "",
        f"- 다음 행동 권고: **{RECOMMENDATION_LABELS[review.recommendation]}**",
        f"- 판단 신뢰 수준: {CONFIDENCE_LABELS[review.confidence]}",
        f"- 요약: {escape_md(review.summary)}",
        f"- 범위: {escape_md(review.scope_note)}",
        "",
        "### 권고 근거",
        "",
    ]
    for item in review.reasons:
        refs = ", ".join(item.citation_ids) or "근거 인용 없음"
        lines.append(
            f"- **{escape_md(item.topic)}:** {escape_md(item.finding)} ({refs})"
        )
    for title, entries in (("기회", review.opportunities), ("위험", review.risks)):
        lines += ["", f"### {title}", ""]
        if not entries:
            lines.append("- 현재 별도로 확인된 항목 없음")
        for item in entries:
            refs = ", ".join(item.citation_ids) or "근거 인용 없음"
            lines.append(f"- {escape_md(item.finding)} ({refs})")
    lines += ["", "### 다음 검증 행동", ""]
    for action in review.next_steps:
        refs = ", ".join(action.citation_ids)
        lines += [
            f"- **{escape_md(action.horizon)} · {escape_md(action.target)}:** {escape_md(action.action)}",
            f"  성공 신호: {escape_md(action.success_signal)}"
            + (f" ({refs})" if refs else ""),
        ]
    if review.unknowns:
        lines += ["", "### 결론을 바꿀 수 있는 미확인 사항", ""]
        lines += [f"- {escape_md(item)}" for item in review.unknowns]
    return lines + [""]


def _compact_text(value: str | None, limit: int = 140) -> str:
    """최종 요약에 쓸 문장을 길이 제한과 Markdown 이스케이프를 적용해 반환한다."""
    text = " ".join(str(value or "").split())
    if len(text) > limit:
        text = text[: limit - 1].rstrip() + "…"
    return escape_md(text)


def _compact_refs(values: list[int] | list[str], limit: int = 3) -> str:
    refs = [str(value) for value in values[:limit]]
    return ", ".join(refs) if refs else "근거 인용 없음"


def _compact_patent_lines(patent: PatentReport) -> list[str]:
    lines = ["## 특허 핵심", ""]
    if patent.status == "error":
        return lines + [f"- 조사 실패: {_compact_text(patent.error_message, 120)}", ""]
    if patent.status == "partial":
        lines.append("- 원문 근거는 확보했지만 비교 분석 일부가 완료되지 않았습니다.")
        if patent.error_message:
            lines.append(f"- 비교 오류: {_compact_text(patent.error_message, 120)}")
    if patent.status == "no_results":
        return lines + [
            "- 검색 범위에서 비교 근거를 확보하지 못함. 특허 위험이 없다는 뜻은 아닙니다.",
            "",
        ]

    statistics = patent.indexed_statistics
    related_statistics = patent.related_statistics
    if statistics:
        top_ipc = (
            " · ".join(
                f"{item.label} {item.count}건"
                for item in statistics.ipc_distribution[:3]
            )
            or "IPC 분류 미확보"
        )
        related_count = (
            f"관련 후보 {related_statistics.total_patents}건"
            if related_statistics
            else "관련 후보 분류 미확인"
        )
        lines.append(
            f"- 색인 기술 동향: {_compact_text(top_ipc, 100)} · {related_count}"
        )

    evidence_by_id = {item.citation_id: item for item in patent.evidence}
    precheck = patent.patentability_precheck
    if precheck:
        refs = _compact_refs([f"P:{item}" for item in precheck.citation_ids])
        lines.append(
            f"- 예비 신호: **{PATENTABILITY_STATUS_LABELS[precheck.status]}** · "
            f"{_compact_text(precheck.summary, 180)} ({refs})"
        )

    if patent.patent_reviews:
        for review in patent.patent_reviews[:2]:
            lines += [
                "",
                f"- **{_compact_text(review.title, 55)}** · 관련성 {PATENT_RELEVANCE_LABELS[review.relevance]}",
                f"  - {_compact_text(review.overall_summary, 130)}",
            ]
            comparisons = sorted(
                review.component_comparisons,
                key=lambda item: {
                    "overlap": 0,
                    "partial": 1,
                    "uncertain": 2,
                    "different": 3,
                    "not_found": 4,
                }[item.status],
            )[:2]
            for comparison in comparisons:
                refs = _compact_refs([f"P:{item}" for item in comparison.citation_ids])
                note = (
                    comparison.overlap
                    or comparison.difference
                    or comparison.uncertainty
                )
                lines.append(
                    f"  - {PATENT_COMPONENT_STATUS_LABELS[comparison.status]}: "
                    f"{_compact_text(comparison.idea_component, 45)} — "
                    f"{_compact_text(note, 100)} ({refs})"
                )
                for citation_id in comparison.citation_ids[:1]:
                    evidence = evidence_by_id.get(citation_id)
                    if evidence:
                        lines.append(
                            f"    - 근거 {patent_location(evidence)}: "
                            f"{_compact_text(evidence.quote, 100)} [P:{citation_id}]"
                        )
    elif patent.comparisons:
        for comparison in patent.comparisons[:2]:
            evidence = evidence_by_id.get(comparison.citation_id)
            if evidence:
                lines.append(
                    f"- {_compact_text(evidence.title, 55)} · 유사점 {_compact_text(comparison.similarity, 80)} · "
                    f"차이 {_compact_text(comparison.difference, 80)} "
                    f"[P:{comparison.citation_id}]"
                )
    else:
        lines.append("- 구성요소별 비교 결과가 충분하지 않습니다.")

    if precheck and precheck.distinction_hypotheses:
        lines.append(
            f"- 검토할 차별점: {_compact_text(precheck.distinction_hypotheses[0], 120)}"
        )
    lines += [
        "- 범위: 검색 문헌 기반 예비 비교이며 등록 가능성·침해 여부를 확정하지 않습니다.",
        "",
    ]
    return lines


def _compact_market_lines(market: MarketReport) -> list[str]:
    lines = ["## 시장성 핵심", ""]
    if market.status == "error":
        return lines + [f"- 조사 실패: {_compact_text(market.error_message, 120)}", ""]
    if market.status == "no_results":
        return lines + [
            "- 시장 근거를 확보하지 못함. 시장 수요가 없다는 뜻은 아닙니다.",
            "",
        ]

    review = market.opportunity_review
    if review:
        labels = {
            "validated_demand": "직접 고객 검증 자료 있음",
            "buyer_signals": "구매자 신호",
            "indirect_signals": "간접 산업 신호",
            "insufficient_evidence": "근거 부족",
        }
        lines.append(
            f"- 수요 근거: **{labels[review.status]}** · 목표 고객: "
            f"{_compact_text(review.target_segment or '미확인', 70)}"
        )
        for finding in review.reasons[:2]:
            refs = _compact_refs([f"M:{item}" for item in finding.citation_ids])
            lines.append(
                f"- {_compact_text(finding.topic, 35)}: "
                f"{_compact_text(finding.statement, 115)} ({refs})"
            )
    commercial = market.commercial_analysis
    if commercial and commercial.hypotheses:
        lines += ["- LLM 가설 (검증 전이며 확인된 수요가 아님):"]
        for hypothesis in commercial.hypotheses[:2]:
            refs = _compact_refs([f"M:{item}" for item in hypothesis.citation_ids])
            lines.append(
                f"  - {_compact_text(hypothesis.hypothesis, 105)} "
                f"(검증: {_compact_text(hypothesis.validation_method, 70)}; "
                f"성공 기준: {_compact_text(hypothesis.success_criterion, 65)}"
                + (f"; {refs}" if refs else "; 직접 근거 인용 없음")
                + ")"
            )

    dimension_labels = {
        "confirmed": "확인",
        "signal_only": "신호",
        "unverified": "미확인",
    }
    dimension_lines = []
    for dimension in market.dimensions:
        refs = dict.fromkeys(
            citation_id
            for claim in dimension.claims
            for citation_id in claim.citation_ids
        )
        if dimension.verdict != "unverified" or refs:
            dimension_lines.append(
                f"{DIMENSION_LABELS[dimension.dimension]} {dimension_labels[dimension.verdict]} "
                f"({_compact_refs([f'M:{item}' for item in refs])})"
            )
    if dimension_lines:
        lines.append("- 차원별 신호: " + " · ".join(dimension_lines[:5]))
    lines += [
        "- 뉴스·기업 자료는 산업 신호이며, 직접 구매 의사로 보지 않습니다.",
        "",
    ]
    return lines


def _compact_business_lines(review: BusinessReview) -> list[str]:
    lines = [
        "## 실행 전 판단",
        "",
        f"- **권고: {RECOMMENDATION_LABELS[review.recommendation]}** · 신뢰도 {CONFIDENCE_LABELS[review.confidence]}",
        f"- {_compact_text(review.summary, 220)}",
    ]
    if review.opportunities:
        lines.append(
            "- 기회: "
            + " · ".join(
                _compact_text(item.finding, 105) for item in review.opportunities[:2]
            )
        )
    if review.risks:
        lines.append(
            "- 위험: "
            + " · ".join(_compact_text(item.finding, 105) for item in review.risks[:2])
        )
    if review.unknowns:
        lines.append(
            "- 핵심 미확인: "
            + " · ".join(_compact_text(item, 75) for item in review.unknowns[:3])
        )
    lines += ["", "## 다음 행동", ""]
    if review.next_steps:
        for action in review.next_steps[:3]:
            refs = (
                f" ({_compact_refs(action.citation_ids)})"
                if action.citation_ids
                else ""
            )
            lines.append(
                f"- **{_compact_text(action.horizon, 25)} · {_compact_text(action.target, 55)}:** "
                f"{_compact_text(action.action, 140)}{refs}"
            )
    else:
        lines.append(
            "- 추가 행동이 정해지지 않았습니다. 고객·특허 전문가와 후속 확인을 진행하세요."
        )
    lines += ["", f"> {_compact_text(review.scope_note, 180)}", ""]
    return lines


def _cross_analysis_lines(patent: PatentReport, market: MarketReport) -> list[str]:
    """특허 비교 신호와 시장 근거 상태를 나란히 보여주는 짧은 교차표를 만든다."""
    precheck = patent.patentability_precheck
    patent_signal = (
        PATENTABILITY_STATUS_LABELS[precheck.status]
        if precheck and precheck.citation_ids
        else "특허 비교 근거 부족"
    )
    market_review = market.opportunity_review
    market_labels = {
        "validated_demand": "직접 고객 검증 자료 있음",
        "buyer_signals": "구매자 관련 공개 신호",
        "indirect_signals": "간접 산업 신호",
        "insufficient_evidence": "수요 근거 부족",
    }
    market_signal = (
        market_labels.get(market_review.status, "시장 판단 자료 없음")
        if market_review
        else "시장 판단 자료 없음"
    )
    patent_refs = (
        _compact_refs([f"P:{item}" for item in precheck.citation_ids])
        if precheck and precheck.citation_ids
        else "인용 근거 없음"
    )
    market_refs = (
        _compact_refs(
            [
                f"M:{citation_id}"
                for reason in market_review.reasons
                for citation_id in reason.citation_ids
            ]
        )
        if market_review
        else "인용 근거 없음"
    )
    directions: list[tuple[str, str]] = []
    if (
        market.status in {"error", "no_results"}
        or not market_review
        or market_review.status == "insufficient_evidence"
    ):
        directions.append(("고객 인터뷰와 문제·지불의사 검증을 우선", market_refs))
    elif precheck and precheck.citation_ids and precheck.status == "overlap_concern":
        directions.append(
            ("수요 신호와 별도로 청구항 대조 및 차별 구성 검토", patent_refs)
        )
    elif (
        precheck and precheck.citation_ids and precheck.status == "potentially_distinct"
    ):
        directions.append(
            (
                "차별 구성은 예비 신호로 두고 고객 조건을 확인한 제한 파일럿 검토",
                f"{patent_refs} · {market_refs}",
            )
        )
    else:
        directions.append(
            ("특허 범위 확인과 고객 검증을 병행", f"{patent_refs} · {market_refs}")
        )

    for dimension in market.dimensions:
        has_citations = any(claim.citation_ids for claim in dimension.claims)
        if (
            dimension.dimension == "adoption_barrier"
            and dimension.verdict != "unverified"
            and has_citations
        ):
            refs = _compact_refs(
                [f"M:{cid}" for claim in dimension.claims for cid in claim.citation_ids]
            )
            directions.append(
                ("도입 비용·설치 장벽을 확인하고 저비용 MVP 가설 검증", refs)
            )
            break
    for dimension in market.dimensions:
        has_citations = any(claim.citation_ids for claim in dimension.claims)
        if (
            dimension.dimension == "competition"
            and dimension.verdict != "unverified"
            and has_citations
        ):
            refs = _compact_refs(
                [f"M:{cid}" for claim in dimension.claims for cid in claim.citation_ids]
            )
            directions.append(
                ("경쟁·대체재 근거를 확인해 목표 고객과 가치 제안 재검토", refs)
            )
            break
    rows = [
        "| 특허 분석 | 시장 분석 | 종합 검토 방향 |",
        "|---|---|---|",
        f"| {_compact_text(patent_signal, 70)} ({patent_refs}) | {_compact_text(market_signal, 70)} ({market_refs}) | {_compact_text(directions[0][0], 100)} |",
    ]
    for direction, references in directions[1:]:
        rows.append(
            f"| 특허와 별도 확인 | {_compact_text(references, 45)} | {_compact_text(direction, 100)} |"
        )
    return [
        "## 특허와 시장 근거의 교차 분석",
        "",
        *rows,
        "",
        "특허 검색 결과만으로 사업성을 판단하지 않습니다. 시장 근거가 부족한 결론은 검증 가설로 남깁니다.",
        "",
    ]


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
    business_review: BusinessReview | None = None,
) -> str:
    """핵심 의사결정 보고서를 짧게 렌더링한다. 세부 근거는 2·3단계에서 제공한다."""
    analyzed = _format_yyyymmdd(analyzed_on) or datetime.now().strftime("%Y-%m-%d")
    collected = _format_yyyymmdd(market_collected_at) or "미확인"
    lines = [
        f"# {escape_md(title) or '사업기획 검토 보고서'}",
        "",
        f"> 분석일 {analyzed} · 시장 자료 기준 {collected} · 근거 발행 범위 {evidence_period(market, patent)}",
        "",
    ]
    if business_review:
        lines += _compact_business_lines(business_review)
    else:
        lines += [
            "## 실행 전 판단",
            "",
            "- 통합 근거 검토 결과를 만들지 못해 진행 권고를 보류합니다.",
            "",
        ]
    if draft is not None:
        lines += [
            "## 아이디어 요약",
            "",
            f"- 문제: {_compact_text(draft.problem, 90) or '미확인'}",
            f"- 제안: {_compact_text(draft.technology, 90) or '미확인'}",
            f"- 고객: {_compact_text(draft.target_segment or draft.customers, 75) or '미확인'}",
            "",
        ]
    if warnings:
        lines += ["## 분석 메모", ""]
        lines += [f"- {_compact_text(item, 130)}" for item in warnings[:2]]
        lines.append("")
    lines += [
        *_compact_patent_lines(patent),
        *_compact_market_lines(market),
        *_cross_analysis_lines(patent, market),
        "> 상세 비교표·원문 인용·시장 분석은 특허 및 시장성 단계의 상세 근거에서 확인할 수 있습니다.",
    ]
    return "\n".join(lines) + "\n"
