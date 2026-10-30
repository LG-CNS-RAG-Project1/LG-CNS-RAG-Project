"""사업 아이디어에서 기술 요소별 특허 검색어를 생성한다."""

import json
import math
from typing import Callable

from openai import OpenAI
from pydantic import ValidationError

from src.schemas import PatentSearchRequest
from src.retrieval.schemas import PatentQueryPlan
from pathlib import Path
from dotenv import load_dotenv

from src.retrieval.patent_store import get_collection
from src.retrieval.schemas import RetrievalResult, SearchDocument
from src.retrieval.engine import RetrievalConfig, retrieve

ROOT_DIR = Path(__file__).resolve().parents[2]
PATENT_CHUNK_OVERFETCH = 4

LLM_MODEL = "gpt-4o-mini"

SYSTEM_PROMPT = """
당신은 선행특허 검색을 위한 검색어 설계 전문가입니다.

입력된 사업 아이디어를 분석하여 핵심 기술 요소별
한국어 및 영어 특허 검색어를 생성하세요.

규칙:
1. technology와 technical_components를 중심으로 구체적인 기술 요소를 추출합니다.
2. problem, difference는 기술 맥락과 해결 대상 파악에 활용합니다.
3. revenue는 필요한 경우에만 참고합니다.
4. 아이디어에 없는 새로운 기술을 임의로 추가하지 않습니다.
5. 기술 요소는 2~5개 추출하되, 실제 기술적 구성 요소만 선정합니다.
6. 고객, 적용 산업, 가격, 수익모델은 독립적인 기술 요소로 선정하지 않습니다.
7. 각 기술 요소에 대해 한국어·영어 검색어를 2개씩 생성합니다.
8. 입력에 명시되지 않은 구체적인 알고리즘이나 장비를
   실제 구현 기술인 것처럼 단정하지 않습니다.
9. 기술 요소가 부족하면 개수를 억지로 채우지 않습니다.
10. 핵심 기술뿐 아니라 기술 요소 간 결합 방식이
    명시되어 있다면 해당 결합 기술도 검색 대상으로 고려합니다.

반드시 다음 JSON 형식으로만 응답하세요.

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


QueryLLMFn = Callable[[str, str], dict]


def build_patent_queries(
    request: PatentSearchRequest,
    llm_fn: QueryLLMFn = call_query_llm,
) -> PatentQueryPlan:
    """사업 아이디어를 기술 요소별 특허 검색어로 변환한다."""

    idea = request.idea

    user_text = json.dumps(
        {
            "title": idea.title,
            "problem": idea.problem,
            "technology": idea.technology,
            "technical_components": idea.technical_components,
            "customers": idea.customers,
            "difference": idea.difference,
            "revenue": idea.revenue,
        },
        ensure_ascii=False,
    )

    raw = llm_fn(SYSTEM_PROMPT, user_text)

    return PatentQueryPlan.model_validate(raw)


def search_patents(
    query: str,
    collection=None,
    embed_fn=None,
    top_k: int = 5,
    retrieval_mode: str = "dense",
    reranker=None,
    retrieval_config: RetrievalConfig | None = None,
    technology_area_id: str | None = None,
) -> list[RetrievalResult]:
    """ChromaDB 특허 청크를 dense, BM25 또는 RRF hybrid 방식으로 검색한다."""

    if not query.strip():
        raise ValueError("검색어가 비어 있습니다.")

    if top_k < 1:
        raise ValueError("top_k는 1 이상이어야 합니다.")
    if retrieval_mode not in {"dense", "bm25", "hybrid"}:
        raise ValueError("retrieval_mode must be dense, bm25, or hybrid")
    config = retrieval_config or RetrievalConfig(
        candidate_k=max(top_k * 4, top_k),
        top_k=top_k,
        deduplicate_by_source=True,
    )

    if collection is None:
        collection = get_collection()

    where = {f"area_{technology_area_id}": True} if technology_area_id else None
    stored = collection.get(where=where, include=["documents", "metadatas"])
    matching_count = len(stored["ids"])
    if matching_count == 0:
        return []

    if embed_fn is None:
        from src.retrieval.market_search import embed_texts

        embed_fn = embed_texts

    documents = []
    for chunk_id, content, raw_metadata in zip(
        stored["ids"], stored["documents"], stored["metadatas"]
    ):
        metadata = dict(raw_metadata)
        documents.append(
            SearchDocument(
                chunk_id=chunk_id,
                source_id=metadata.pop("source_id"),
                source_type="patent",
                title=metadata.pop("title"),
                content=content,
                metadata=metadata,
            )
        )

    dense_results = []
    if retrieval_mode in {"dense", "hybrid"}:
        query_vector = embed_fn([query])[0]
        chunk_candidate_k = min(
            config.candidate_k * PATENT_CHUNK_OVERFETCH,
            matching_count,
        )
        results = collection.query(
            query_embeddings=[query_vector],
            n_results=chunk_candidate_k,
            where=where,
            include=["distances"],
        )
        by_id = {document.chunk_id: document for document in documents}
        dense_results = [
            RetrievalResult(
                document=by_id[chunk_id],
                dense_score=1.0 - distance,
                dense_rank=rank,
            )
            for rank, (chunk_id, distance) in enumerate(
                zip(results["ids"][0], results["distances"][0]), 1
            )
        ]
    response = retrieve(
        query,
        documents,
        dense_results,
        mode=retrieval_mode,
        config=config,
        reranker=reranker,
    )
    return [
        item.model_copy(update={"final_rank": rank})
        for rank, item in enumerate(response.results[:top_k], 1)
    ]


def bi_encoder_reranker(embed_fn=None):
    """질의·특허 후보 임베딩의 cosine 유사도로 재정렬 함수를 만든다.

    문서 임베딩도 요청마다 계산하므로 실험 시 API 사용량과 지연을 기록해야 한다.
    운영 색인의 임베딩을 재사용하지 않으며, 외부 호출은 호출부에서 명시적으로 한다.
    """
    if embed_fn is None:
        from src.retrieval.market_search import embed_texts

        embed_fn = embed_texts

    def score(query: str, documents: list[SearchDocument]) -> list[float]:
        texts = [query] + [f"{item.title}\n{item.content}" for item in documents]
        vectors = embed_fn(texts)
        if len(vectors) != len(texts):
            raise ValueError("embedding function must return one vector per text")
        query_vector = vectors[0]
        query_norm = math.sqrt(sum(float(value) ** 2 for value in query_vector))
        scores = []
        for vector in vectors[1:]:
            if len(vector) != len(query_vector):
                raise ValueError("embedding vectors must have matching dimensions")
            document_norm = math.sqrt(sum(float(value) ** 2 for value in vector))
            denominator = query_norm * document_norm
            scores.append(
                sum(
                    float(left) * float(right)
                    for left, right in zip(query_vector, vector)
                )
                / denominator
                if denominator
                else 0.0
            )
        return scores

    return score
