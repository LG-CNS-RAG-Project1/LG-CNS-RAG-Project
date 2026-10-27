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
    payload = {
        "idea": idea.model_dump(),
        "evidence": [item.model_dump() for item in evidence],
    }
    raw = llm_fn(load_prompt(), json.dumps(payload, ensure_ascii=False))
    comparisons = [
        PatentComparison.model_validate(item) for item in raw.get("comparisons", [])
    ]
    allowed_ids = {item.citation_id for item in evidence}
    comparison_ids = [item.citation_id for item in comparisons]
    if set(comparison_ids) != allowed_ids or len(comparison_ids) != len(allowed_ids):
        raise ValueError("Patent comparisons must map one-to-one to supplied evidence")
    return comparisons
