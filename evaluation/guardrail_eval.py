"""아이디어 입력 가드레일(규칙 검사 + 구조화 LLM의 input_status)을 공격·주제 이탈·정상 입력으로 평가한다.

문항은 evaluation/guardrail_cases.json과 data/samples/ideas.json의 샘플 아이디어(정상 입력)이다.
- 공격 차단율: 기대값이 off_topic·unsafe인 문항 중 거절된 비율
- 오차단율: 기대값이 ok인 문항 중 거절된 비율
- 상태 일치율: 거절 여부뿐 아니라 off_topic·unsafe 구분까지 맞은 비율
- blocked_by: rule(LLM 호출 전 규칙 검사) · llm(input_status) · none
"""

import json
from pathlib import Path

from src.generation.idea_parser import call_llm, parse_idea

ROOT_DIR = Path(__file__).resolve().parents[1]
CASES_PATH = ROOT_DIR / "evaluation" / "guardrail_cases.json"
IDEAS_PATH = ROOT_DIR / "data" / "samples" / "ideas.json"
RESULT_FIELDS = [
    "case_id",
    "kind",
    "expected",
    "predicted",
    "blocked_by",
    "correct",
    "text",
    "reason",
]


def load_guardrail_cases(
    cases_path: Path = CASES_PATH, ideas_path: Path = IDEAS_PATH
) -> list[dict]:
    """가드레일 문항에 샘플 아이디어를 정상 입력(expected=ok, kind=sample)으로 더한다."""
    cases = json.loads(cases_path.read_text(encoding="utf-8"))
    ideas = json.loads(ideas_path.read_text(encoding="utf-8"))
    return cases + [
        {"case_id": i["idea_id"], "expected": "ok", "kind": "sample", "text": i["text"]}
        for i in ideas
    ]


def evaluate_guardrail(cases: list[dict], llm_fn=call_llm) -> list[dict]:
    """문항마다 parse_idea를 실행해 판정 결과와 차단 단계를 기록한다."""
    rows = []
    for case in cases:
        calls = []

        def counted_llm(system_prompt, user_text):
            calls.append(user_text)
            return llm_fn(system_prompt, user_text)

        draft = parse_idea(case["text"], llm_fn=counted_llm)
        predicted = draft.input_status
        blocked_by = "none" if predicted == "ok" else ("llm" if calls else "rule")
        rows.append(
            {
                "case_id": case["case_id"],
                "kind": case["kind"],
                "expected": case["expected"],
                "predicted": predicted,
                "blocked_by": blocked_by,
                "correct": int(predicted == case["expected"]),
                "text": case["text"],
                "reason": draft.rejection_reason or "",
            }
        )
    return rows


def summarize_guardrail(rows: list[dict]) -> dict:
    """공격 차단율·오차단율·상태 일치율과 차단 단계별 건수를 계산한다."""
    attacks = [r for r in rows if r["expected"] != "ok"]
    normal = [r for r in rows if r["expected"] == "ok"]

    def rate(group, condition):
        return sum(condition(r) for r in group) / len(group) if group else None

    return {
        "cases": len(rows),
        "attacks": len(attacks),
        "normal": len(normal),
        "block_rate": rate(attacks, lambda r: r["predicted"] != "ok"),
        "false_block_rate": rate(normal, lambda r: r["predicted"] != "ok"),
        "status_accuracy": rate(rows, lambda r: r["correct"]),
        "blocked_by_rule": sum(r["blocked_by"] == "rule" for r in rows),
        "blocked_by_llm": sum(r["blocked_by"] == "llm" for r in rows),
    }
