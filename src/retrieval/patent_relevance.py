"""특허 검색 후보를 아이디어 기술 요소와 대조해 근거 적합성을 판정한다."""

import json
from pathlib import Path
from typing import Callable

from pydantic import BaseModel, Field
from src.llm_client import chat_model, get_openai_client

ROOT_DIR = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT_DIR / "prompts" / "patent_relevance_judge.md"
MODEL = "gpt-4o-mini"


class RelevanceVerdict(BaseModel):
    """검색된 특허 한 건의 관련성 판정과 설명."""

    source_id: str
    relevant: bool
    confidence: str = Field(pattern="^(high|medium|low)$")
    reason: str


class RelevanceBatch(BaseModel):
    """후보 집합 전체에 대한 일대일 관련성 판정 묶음."""

    judgments: list[RelevanceVerdict]


def call_relevance_llm(system_prompt: str, user_text: str) -> dict:
    """선택한 LLM provider에 판정 요청을 보내 JSON 객체를 읽는다."""
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


def judge_patent_candidates(idea, results, llm_fn: Callable | None = None):
    """후보를 판정하고 판정이 확인된 결과만 반환한다."""
    if not results:
        return {}
    prompt = PROMPT_PATH.read_text(encoding="utf-8")
    payload = {
        "idea": idea.model_dump(),
        "candidates": [
            {
                "source_id": item.document.source_id,
                "title": item.document.title,
                "section": item.document.metadata.get("section", "unknown"),
                "text": item.document.content[:4000],
            }
            for item in results
        ],
    }
    raw = (llm_fn or call_relevance_llm)(
        prompt, json.dumps(payload, ensure_ascii=False)
    )
    batch = RelevanceBatch.model_validate(raw)
    expected = {item.document.source_id for item in results}
    actual = [item.source_id for item in batch.judgments]
    if set(actual) != expected or len(actual) != len(expected):
        raise ValueError("Patent relevance judgments must map one-to-one to candidates")
    return {item.source_id: item for item in batch.judgments}
