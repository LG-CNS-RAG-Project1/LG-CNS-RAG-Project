"""LLM 단독 답변과 시장 RAG 답변을 짝지어 탐색 평가한다.

사용 예:
    python -m evaluation.answer_eval --limit 5

사람이 라벨링한 시장 문항·정답 후보를 사용한다. LLM 판정 점수는 자동 채점이
아니므로 결과를 탐색 지표로 취급하고, 필요하면 사람이 표본을 검토한다.
"""

import argparse
import csv
import hashlib
import json
import subprocess
import time
from pathlib import Path

from dotenv import load_dotenv
from openai import OpenAI

from evaluation.market_labeling import case_query, load_cases, load_ideas
from src.retrieval.market_search import search_market
from src.retrieval.market_search import get_collection

ROOT_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT_DIR / "evaluation" / "results"
MODEL = "gpt-4o-mini"
ANSWER_PROMPT = """질문에 한국어로 간결히 답한다. 제공된 자료가 없으면 확정 사실처럼 말하지 말고 불확실성을 밝힌다. 자료가 있으면 제공된 citation ID를 사실 문장에 붙이고, 자료가 뒷받침하지 않는 주장은 만들지 않는다. JSON: {\"answer\":\"...\"}"""
JUDGE_PROMPT = """평가자다. 질문과 자료에 비추어 답변을 평가한다. 입력에 없는 사실을 추가하지 않는다. 1~5점으로 citation_accuracy, evidence_faithfulness, factual_correctness를 평가하고 error_type을 none, unsupported_claim, citation_mismatch, omission, uncertainty_not_disclosed, other 중 하나로 고른다. JSON: {\"citation_accuracy\":1,\"evidence_faithfulness\":1,\"factual_correctness\":1,\"error_type\":\"...\",\"reason\":\"...\"}"""
FIELDS = [
    "case_id",
    "mode",
    "question",
    "answer",
    "citation_accuracy",
    "evidence_faithfulness",
    "factual_correctness",
    "error_type",
    "reason",
    "latency_ms",
    "answer_model",
    "judge_model",
    "answer_prompt_sha256",
    "judge_prompt_sha256",
    "commit",
    "input_tokens",
    "output_tokens",
]


def completion(client, system, user):
    started = time.perf_counter()
    response = client.chat.completions.create(
        model=MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user},
        ],
    )
    return (
        json.loads(response.choices[0].message.content),
        response.usage,
        (time.perf_counter() - started) * 1000,
    )


def prompt_hash(prompt):
    return hashlib.sha256(prompt.encode("utf-8")).hexdigest()


def run(limit=5, label="baseline"):
    load_dotenv(ROOT_DIR / ".env")
    client = OpenAI()
    collection = get_collection()
    if collection.count() == 0:
        raise RuntimeError(
            "market Chroma index is empty; build the market index before answer evaluation"
        )
    ideas = load_ideas()
    cases = [case for case in load_cases() if case.get("labeled")][:limit]
    if not cases:
        raise RuntimeError("No labeled market evaluation cases are available")
    commit = subprocess.run(
        ["git", "rev-parse", "HEAD"], capture_output=True, text=True, check=False
    ).stdout.strip()
    rows = []
    for case in cases:
        query = case_query(case, ideas)
        hits = search_market(
            query, collection=collection, top_k=5, idea_id=case["idea_id"]
        )
        context_items = [
            {
                "citation_id": f"M:{rank}",
                "source_id": hit["source_id"],
                "title": hit["title"],
                "text": hit["text"],
            }
            for rank, hit in enumerate(hits, 1)
        ]
        for mode in ("llm_only", "rag"):
            context = context_items if mode == "rag" else []
            answer_raw, answer_usage, answer_ms = completion(
                client,
                ANSWER_PROMPT,
                json.dumps(
                    {"question": case["question"], "context": context},
                    ensure_ascii=False,
                ),
            )
            answer = answer_raw.get("answer", "")
            judge_raw, judge_usage, judge_ms = completion(
                client,
                JUDGE_PROMPT,
                json.dumps(
                    {
                        "question": case["question"],
                        "answer": answer,
                        "available_sources": context,
                        "known_relevant_source_ids": case.get(
                            "relevant_source_ids", []
                        ),
                    },
                    ensure_ascii=False,
                ),
            )
            rows.append(
                {
                    "case_id": case["case_id"],
                    "mode": mode,
                    "question": case["question"],
                    "answer": answer,
                    **{
                        key: judge_raw.get(key)
                        for key in (
                            "citation_accuracy",
                            "evidence_faithfulness",
                            "factual_correctness",
                            "error_type",
                            "reason",
                        )
                    },
                    "latency_ms": round(answer_ms + judge_ms, 2),
                    "answer_model": MODEL,
                    "judge_model": MODEL,
                    "answer_prompt_sha256": prompt_hash(ANSWER_PROMPT),
                    "judge_prompt_sha256": prompt_hash(JUDGE_PROMPT),
                    "commit": commit,
                    "input_tokens": (answer_usage.prompt_tokens or 0)
                    + (judge_usage.prompt_tokens or 0),
                    "output_tokens": (answer_usage.completion_tokens or 0)
                    + (judge_usage.completion_tokens or 0),
                }
            )
    output = RESULTS_DIR / f"answer_quality_{label}.csv"
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("w", encoding="utf-8-sig", newline="") as file:
        writer = csv.DictWriter(file, fieldnames=FIELDS)
        writer.writeheader()
        writer.writerows(rows)
    print(f"{len(rows)} paired answers -> {output}")
    for mode in ("llm_only", "rag"):
        group = [row for row in rows if row["mode"] == mode]
        print(
            mode,
            {
                key: round(sum(row[key] for row in group) / len(group), 2)
                for key in (
                    "citation_accuracy",
                    "evidence_faithfulness",
                    "factual_correctness",
                )
            },
        )


def main():
    parser = argparse.ArgumentParser(description="LLM-only vs RAG answer evaluation")
    parser.add_argument("--limit", type=int, default=5)
    parser.add_argument("--label", default="baseline")
    args = parser.parse_args()
    run(args.limit, args.label)


if __name__ == "__main__":
    main()
