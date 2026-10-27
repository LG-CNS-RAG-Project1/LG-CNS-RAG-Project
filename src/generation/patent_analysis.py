"""아이디어 기술 요소와 실제 특허 근거의 비교 초안을 생성한다."""

import json
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv
from openai import OpenAI

from src.schemas import PatentComparison, PatentEvidence, StructuredIdea

ROOT_DIR = Path(__file__).resolve().parents[2]
LLM_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """
특허 청구항 근거를 아이디어 기술 요소와 비교하는 분석기다.
입력으로 제공된 특허 문구만 근거로 사용하고, 인용 문구를 바꾸거나 보충하지 않는다.
각 근거마다 아이디어와의 유사점, 차이점, 미확인 사항을 분리해 작성한다.
청구항이 아닌 초록은 청구범위의 근거처럼 취급하지 않는다.
특허성, 신규성, 진보성, 침해 여부를 판정하지 않는다.
원문에 없는 구성·성능·법적 상태는 추측하지 않고 uncertainty에 미확인이라고 쓴다.

JSON 형식:
{"comparisons":[{"citation_id":1,"technical_element":"기술 요소",
"similarity":"근거와의 유사점","difference":"근거와의 차이점",
"uncertainty":"미확인 사항"}]}
"""


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
    raw = llm_fn(SYSTEM_PROMPT, json.dumps(payload, ensure_ascii=False))
    comparisons = [
        PatentComparison.model_validate(item) for item in raw.get("comparisons", [])
    ]
    allowed_ids = {item.citation_id for item in evidence}
    comparison_ids = [item.citation_id for item in comparisons]
    if set(comparison_ids) != allowed_ids or len(comparison_ids) != len(allowed_ids):
        raise ValueError("Patent comparisons must map one-to-one to supplied evidence")
    return comparisons
