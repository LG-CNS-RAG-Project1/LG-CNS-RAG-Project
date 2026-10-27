"""시장·특허 근거를 검토 질문 및 6개 기준에 연결해 통합 보고서를 구성한다."""

import json
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from openai import OpenAI
from pydantic import BaseModel, Field

from src.schemas import MarketReport, PatentReport

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
    payload = {
        "questions": questions,
        "market": market.model_dump(),
        "patent": patent.model_dump(),
        "criteria": CRITERIA,
    }
    batch = LinkBatch.model_validate(
        (llm_fn or call_report_llm)(prompt, json.dumps(payload, ensure_ascii=False))
    )
    wanted_ids = [item["id"] for item in questions]
    actual_ids = [link.question_id for link in batch.links]
    if set(actual_ids) != set(wanted_ids) or len(actual_ids) != len(wanted_ids):
        raise ValueError("Question evidence links must map one-to-one to questions")
    market_ids = {f"M:{item.citation_id}" for item in market.evidence}
    patent_ids = {f"P:{item.citation_id}" for item in patent.evidence}
    allowed_ids = market_ids | patent_ids
    has_both = bool(market_ids) and bool(patent_ids)
    for link in batch.links:
        if len(link.criteria) != len(CRITERIA) or {
            c.criterion for c in link.criteria
        } != set(CRITERIA):
            raise ValueError("Each question needs all six evidence criteria")
        for criterion in link.criteria:
            unknown = set(criterion.citation_ids) - allowed_ids
            if unknown:
                raise ValueError(f"Unknown integrated citation ids: {sorted(unknown)}")
        used = {cid for criterion in link.criteria for cid in criterion.citation_ids}
        if not has_both or not (used & market_ids) or not (used & patent_ids):
            link.status = "hold"
            link.summary = "시장·특허 양쪽 근거가 연결되지 않아 통합 판단을 보류합니다."
    return batch.links


def integrated_report_markdown(
    title: str,
    questions: list[dict],
    links: list[QuestionLink],
    market: MarketReport,
    patent: PatentReport,
) -> str:
    """통합 보고서의 질문 연결, 출처, 상태를 Markdown으로 렌더링한다."""
    by_id = {link.question_id: link for link in links}
    lines = [f"# {title or '사업기획 검토 보고서'}", "", "## 검토 질문별 근거 연결", ""]
    for question in questions:
        link = by_id.get(question["id"])
        if not link:
            continue
        lines += [
            f"### {question['id']} · {question['question']}",
            "",
            f"- 상태: {link.status}",
            f"- 요약: {link.summary}",
        ]
        for criterion in link.criteria:
            refs = (
                ", ".join(f"[{cid}]" for cid in criterion.citation_ids) or "근거 없음"
            )
            lines.append(
                f"- {criterion.criterion}: {criterion.assessment} ({refs}) · 다음 확인: {criterion.next_check}"
            )
        lines.append("")
    lines += [
        "## 특허 조사",
        "",
        f"- 상태: {patent.status}",
        f"- 범위: {patent.search_scope}",
    ]
    patent_by_id = {item.citation_id: item for item in patent.evidence}
    for comparison in patent.comparisons:
        evidence = patent_by_id[comparison.citation_id]
        lines += [
            f"### [P:{comparison.citation_id}] {evidence.title}",
            "",
            f"- 근거 원문 ({evidence.section}): {evidence.quote}",
            f"- 유사점: {comparison.similarity}",
            f"- 차이점: {comparison.difference}",
            f"- 미확인: {comparison.uncertainty}",
            "",
        ]
    lines += [
        "## 시장 조사",
        "",
        f"- 상태: {market.status}",
        f"- 범위: {market.search_scope}",
    ]
    for dimension in market.dimensions:
        lines.append(f"### {dimension.dimension} · {dimension.verdict}")
        for claim in dimension.claims:
            refs = " ".join(f"[M:{cid}]" for cid in claim.citation_ids) or "(근거 없음)"
            lines.append(f"- [{claim.claim_type}] {claim.statement} {refs}")
        if dimension.next_check:
            lines.append(f"- 다음 확인: {dimension.next_check}")
        lines.append("")
    for evidence in market.evidence:
        lines.append(
            f"- [M:{evidence.citation_id}] {evidence.title} · {evidence.publisher} · {evidence.quote} · {evidence.url or 'URL 미확인'}"
        )
    if patent.unknowns or market.unknowns:
        lines += ["", "## 미확인 사항", ""]
        lines.extend(f"- 특허: {item}" for item in patent.unknowns)
        lines.extend(f"- 시장: {item}" for item in market.unknowns)
    lines += [
        "",
        "## 판단 범위",
        "",
        "이 보고서는 조사 근거와 미확인 사항을 정리하며 특허성·신규성·진보성·침해 여부 또는 사업성의 최종 판정을 제공하지 않습니다.",
    ]
    return "\n".join(lines) + "\n"
