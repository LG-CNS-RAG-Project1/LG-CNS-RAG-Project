"""아이디어 기술 요소와 실제 특허 근거의 비교 초안을 생성한다."""

import json
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from openai import OpenAI

from src.schemas import PatentComparison, PatentEvidence, StructuredIdea

ROOT_DIR = Path(__file__).resolve().parents[2]
LLM_MODEL = "gpt-4o-mini"

PROMPT_PATH = ROOT_DIR / "prompts" / "patent_analysis.md"


def load_prompt() -> str:
    """특허 비교 생성 규칙을 저장된 프롬프트에서 읽는다."""
    return PROMPT_PATH.read_text(encoding="utf-8")


def call_comparison_llm(system_prompt: str, user_text: str) -> dict:
    """OpenAI JSON 응답을 반환한다."""
    load_dotenv(ROOT_DIR / ".env")
    client = OpenAI()
    response = client.chat.completions.create(
        model=LLM_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
    )
    return json.loads(response.choices[0].message.content)


ComparisonLLMFn = Callable[[str, str], dict]


def compare_patent_evidence(
    idea: StructuredIdea,
    evidence: list[PatentEvidence],
    llm_fn: ComparisonLLMFn = call_comparison_llm,
) -> list[PatentComparison]:
    """검증 가능한 근거를 입력해 citation_id별 비교를 생성하고 스키마를 검증한다."""
    if not evidence:
        return []
    evidence_ids = [item.citation_id for item in evidence]
    if len(evidence_ids) != len(set(evidence_ids)):
        raise ValueError("Supplied patent evidence must have unique citation IDs")

    payload = {
        "idea": idea.model_dump(),
        "evidence": [item.model_dump() for item in evidence],
        "required_citation_ids": evidence_ids,
    }
    system_prompt = load_prompt()
    user_text = json.dumps(payload, ensure_ascii=False)
    expected_ids = set(evidence_ids)
    last_error = None

    # 모델이 일부 인용을 빠뜨리거나 citation_id를 중복 생성하면, 누락 목록을
    # 명시해 한 번 교정 요청한다. 같은 입력을 그대로 재시도하면 같은 오류가
    # 반복될 가능성이 높다.
    for attempt in range(2):
        raw = llm_fn(system_prompt, user_text)
        comparison_ids = []
        try:
            if not isinstance(raw, dict) or not isinstance(
                raw.get("comparisons"), list
            ):
                raise ValueError("Response must contain a comparisons list")
            comparisons = [
                PatentComparison.model_validate(item) for item in raw["comparisons"]
            ]
            comparison_ids = [item.citation_id for item in comparisons]
            if set(comparison_ids) != expected_ids or len(comparison_ids) != len(
                expected_ids
            ):
                raise ValueError(
                    "Patent comparisons must map one-to-one to supplied evidence"
                )
            by_id = {item.citation_id: item for item in comparisons}
            return [by_id[citation_id] for citation_id in evidence_ids]
        except Exception as exc:
            last_error = exc
            if attempt == 0:
                missing = sorted(expected_ids - set(comparison_ids))
                duplicated = sorted(
                    citation_id
                    for citation_id in set(comparison_ids)
                    if comparison_ids.count(citation_id) > 1
                )
                correction = {
                    "required_citation_ids": evidence_ids,
                    "previous_response": raw,
                    "validation_error": str(exc),
                    "missing_citation_ids": missing,
                    "duplicated_citation_ids": duplicated,
                }
                user_text = (
                    json.dumps(payload, ensure_ascii=False)
                    + "\n\n이전 응답을 수정하세요. 원문 근거를 유지하고 required_citation_ids의 각 ID에 대해 정확히 하나씩 비교를 반환하세요.\n"
                    + json.dumps(correction, ensure_ascii=False)
                )

    raise ValueError(str(last_error)) from last_error
