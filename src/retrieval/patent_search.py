"""사업 아이디어에서 기술 요소별 특허 검색어를 생성한다."""

import json
from typing import Callable

from openai import OpenAI
from pydantic import ValidationError

from src.schemas import PatentSearchRequest
from src.retrieval.schemas import PatentQueryPlan

LLM_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """
당신은 선행특허 검색을 위한 검색어 설계 전문가입니다.

입력된 사업 아이디어를 분석하여 핵심 기술 요소별
한국어 및 영어 특허 검색어를 생성하세요.

규칙:
1. technology를 중심으로 기술 요소를 추출합니다.
2. problem, customers, difference는 기술 맥락을 파악하는 데 활용합니다.
3. revenue는 필요한 경우에만 참고합니다.
4. 아이디어에 없는 새로운 기술을 임의로 추가하지 않습니다.
5. 기술 요소는 최대 5개로 제한합니다.
6. 각 기술 요소에 대해 한국어 검색어 2개,
   영어 검색어 2개를 생성합니다.
7. 검색어는 특허 검색에 적합한 기술 용어로 작성합니다.
8. 반드시 아래 JSON 형식으로 응답합니다.

{
  "queries": [
    {
      "technical_element": "기술 요소",
      "korean_queries": ["한국어 검색어1", "한국어 검색어2"],
      "english_queries": ["영어 검색어1", "영어 검색어2"]
    }
  ]
}
"""


def call_query_llm(system_prompt: str, user_text: str) -> dict:
    """OpenAI API를 호출하여 검색어 생성 결과를 반환한다."""
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


QueryLLMFn = Callable[[str, str], dict]


def build_patent_queries(
    request: PatentSearchRequest,
    llm_fn: QueryLLMFn = call_query_llm,
) -> PatentQueryPlan:
    """사업 아이디어를 기술 요소별 특허 검색어로 변환한다."""

    idea = request.idea

    user_text = json.dumps(
        {
            "problem": idea.problem,
            "technology": idea.technology,
            "customers": idea.customers,
            "difference": idea.difference,
            "revenue": idea.revenue,
        },
        ensure_ascii=False,
    )

    raw = llm_fn(SYSTEM_PROMPT, user_text)

    return PatentQueryPlan.model_validate(raw)
