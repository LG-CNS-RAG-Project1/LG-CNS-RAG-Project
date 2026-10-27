"""LLM으로 시장 검색 평가셋의 라벨 초안을 만들고, 사람 라벨과의 일치도를 확인한다.

절차:
    prelabel   후보 CSV의 각 행을 prompts/market_label_judge.md 기준으로 LLM이 판정해
               evaluation/labels/market_llm_labels.csv에 따로 저장 (사람 라벨 파일은 건드리지 않음)
    agreement  사람이 relevant를 채운 행과 LLM 판정을 비교해 일치율·Cohen's kappa 출력
    merge      후보 CSV에 LLM 판정 열을 붙이고, 사람이 비워 둔 relevant만 LLM 판정으로 채움
               (label_source = human | llm, 확신이 낮은 행은 review = 확인)

사용 예:
    python -m evaluation.market_judge prelabel --limit 3
    python -m evaluation.market_judge prelabel
    python -m evaluation.market_judge agreement
    python -m evaluation.market_judge merge
"""

import argparse
import json
import os
import shutil
from pathlib import Path
from typing import Callable

from dotenv import load_dotenv

from evaluation.market_labeling import (
    CANDIDATES_PATH,
    CSV_FIELDS,
    LABEL_VALUES,
    load_ideas,
    read_label_rows,
    write_label_rows,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
JUDGE_PROMPT_PATH = ROOT_DIR / "prompts" / "market_label_judge.md"
LLM_LABELS_PATH = ROOT_DIR / "evaluation" / "labels" / "market_llm_labels.csv"
JUDGE_MODEL = "gpt-4o"
LLM_FIELDS = ["case_id", "source_id", "llm_label", "llm_confidence", "llm_reason"]
MERGED_FIELDS = CSV_FIELDS + ["label_source", "review"] + LLM_FIELDS[2:]

JudgeFn = Callable[[str, str], dict]


def call_judge(system_prompt: str, user_text: str) -> dict:
    """OpenAI 채팅 API를 JSON 모드로 호출해 판정 결과를 dict로 반환한다."""
    from openai import OpenAI

    load_dotenv(ROOT_DIR / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set in .env")
    response = OpenAI().chat.completions.create(
        model=JUDGE_MODEL,
        temperature=0,
        response_format={"type": "json_object"},
        messages=[
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_text},
        ],
    )
    return json.loads(response.choices[0].message.content)


def row_key(row: dict) -> tuple[str, str]:
    """문항·문서 쌍으로 행을 식별한다."""
    return row["case_id"], row["source_id"]


def judge_input(row: dict, ideas: dict[str, dict]) -> str:
    """판정 프롬프트에 넘길 입력 JSON을 만든다."""
    return json.dumps(
        {
            "idea": ideas[row["idea_id"]]["idea"],
            "dimension": row["dimension"],
            "question": row["question"],
            "title": row["title"],
            "summary": row["summary"],
        },
        ensure_ascii=False,
    )


def parse_judgement(raw: dict) -> dict:
    """LLM 응답을 검증해 llm_label·llm_confidence·llm_reason으로 정리한다.

    label이 0·1이 아니면 0, confidence가 high가 아니면 low로 본다.
    """
    label = str(raw.get("label", "")).strip()
    return {
        "llm_label": label if label in LABEL_VALUES else "0",
        "llm_confidence": "high" if raw.get("confidence") == "high" else "low",
        "llm_reason": " ".join(str(raw.get("reason", "")).split()),
    }


def load_llm_labels(path: Path = LLM_LABELS_PATH) -> list[dict]:
    """저장된 LLM 판정을 읽는다. 파일이 없으면 빈 목록."""
    return read_label_rows(path) if path.exists() else []


def prelabel(
    rows: list[dict],
    ideas: dict[str, dict],
    judge_fn: JudgeFn = call_judge,
    existing: list[dict] | None = None,
    limit: int | None = None,
    case_ids: set[str] | None = None,
) -> list[dict]:
    """아직 판정하지 않은 행만 LLM으로 판정해 기존 판정 뒤에 붙여 반환한다.

    case_ids를 주면 해당 문항의 행만 판정한다.
    """
    results = list(existing or [])
    done = {row_key(r) for r in results}
    todo = [
        r
        for r in rows
        if row_key(r) not in done and (not case_ids or r["case_id"] in case_ids)
    ][:limit]
    system_prompt = JUDGE_PROMPT_PATH.read_text(encoding="utf-8")
    for row in todo:
        judgement = parse_judgement(judge_fn(system_prompt, judge_input(row, ideas)))
        results.append(
            {"case_id": row["case_id"], "source_id": row["source_id"], **judgement}
        )
    return results


def agreement(human_rows: list[dict], llm_rows: list[dict]) -> dict:
    """사람이 1·0을 적은 행과 LLM 판정의 일치율·Cohen's kappa·불일치 목록을 계산한다."""
    llm = {row_key(r): r["llm_label"] for r in llm_rows}
    pairs = [
        (r["relevant"].strip(), llm[row_key(r)], r)
        for r in human_rows
        if r["relevant"].strip() in LABEL_VALUES
        and r.get("label_source") != "llm"
        and row_key(r) in llm
    ]
    n = len(pairs)
    if not n:
        return {"n": 0, "agreement": None, "kappa": None, "disagreements": []}

    observed = sum(h == m for h, m, _ in pairs) / n
    human_pos = sum(h == "1" for h, _, _ in pairs) / n
    llm_pos = sum(m == "1" for _, m, _ in pairs) / n
    expected = human_pos * llm_pos + (1 - human_pos) * (1 - llm_pos)
    kappa = (observed - expected) / (1 - expected) if expected < 1 else 1.0
    return {
        "n": n,
        "agreement": observed,
        "kappa": kappa,
        "human_positive": sum(h == "1" for h, _, _ in pairs),
        "llm_positive": sum(m == "1" for _, m, _ in pairs),
        "disagreements": [
            {"case_id": r["case_id"], "title": r["title"], "human": h, "llm": m}
            for h, m, r in pairs
            if h != m
        ],
    }


def merge_llm_labels(human_rows: list[dict], llm_rows: list[dict]) -> list[dict]:
    """후보 행에 LLM 판정 열을 붙인다.

    이미 채워진 relevant는 그대로 두고(label_source가 없으면 human), 빈 relevant만 LLM 판정으로
    채운다(label_source=llm). LLM 확신이 낮은 LLM 채움 행에는 review=확인을 표시한다.
    다시 실행해도 앞서 채운 값과 사람이 고친 값은 바뀌지 않는다.
    """
    llm = {row_key(r): r for r in llm_rows}
    merged = []
    for row in human_rows:
        judged = llm.get(row_key(row), {})
        filled = row["relevant"].strip() in LABEL_VALUES
        if filled:
            relevant, source = row["relevant"], row.get("label_source") or "human"
        else:
            relevant = judged.get("llm_label", "")
            source = "llm" if judged else ""
        needs_review = source == "llm" and judged.get("llm_confidence") == "low"
        merged.append(
            {
                **row,
                **{f: judged.get(f, "") for f in LLM_FIELDS[2:]},
                "relevant": relevant,
                "label_source": source,
                "review": "확인" if needs_review else row.get("review", ""),
            }
        )
    return merged


def main() -> None:
    """prelabel·agreement·merge 하위 명령을 실행한다."""
    parser = argparse.ArgumentParser(description="LLM 라벨 초안·일치도 확인")
    sub = parser.add_subparsers(dest="command", required=True)
    pre = sub.add_parser("prelabel", help="LLM 판정을 별도 파일에 저장")
    pre.add_argument("--limit", type=int, help="이번에 판정할 최대 행 수")
    pre.add_argument("--cases", nargs="+", help="판정할 case_id (생략하면 전체)")
    sub.add_parser("agreement", help="사람 라벨과 LLM 판정 비교")
    sub.add_parser("merge", help="후보 CSV에 LLM 판정 반영 (백업 후 덮어씀)")
    args = parser.parse_args()

    human_rows = read_label_rows(CANDIDATES_PATH)
    llm_rows = load_llm_labels()
    if args.command == "prelabel":
        llm_rows = prelabel(
            human_rows,
            load_ideas(),
            existing=llm_rows,
            limit=args.limit,
            case_ids=set(args.cases) if args.cases else None,
        )
        write_label_rows(llm_rows, LLM_FIELDS, LLM_LABELS_PATH)
        print(f"{len(llm_rows)}/{len(human_rows)} rows judged -> {LLM_LABELS_PATH}")
    elif args.command == "agreement":
        result = agreement(human_rows, llm_rows)
        if not result["n"]:
            raise SystemExit("no rows with both human and LLM labels")
        print(
            f"n={result['n']} 일치율={result['agreement']:.0%} kappa={result['kappa']:.2f}"
            f" (관련: 사람 {result['human_positive']} / LLM {result['llm_positive']})"
        )
        for d in result["disagreements"]:
            print(
                f"  {d['case_id']} 사람={d['human']} LLM={d['llm']} {d['title'][:50]}"
            )
    else:
        backup = CANDIDATES_PATH.with_name("market_candidates.before_merge.csv")
        shutil.copyfile(CANDIDATES_PATH, backup)
        merged = merge_llm_labels(human_rows, llm_rows)
        write_label_rows(merged, MERGED_FIELDS, CANDIDATES_PATH)
        review = sum(r["review"] == "확인" for r in merged)
        print(
            f"merged -> {CANDIDATES_PATH} (backup {backup.name}, 확인 필요 {review}행)"
        )


if __name__ == "__main__":
    main()
