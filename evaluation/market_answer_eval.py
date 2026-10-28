"""시장 답변 평가: LLM 단독·단순 RAG·IdeaLens 시장 분석을 같은 문항으로 비교한다.

세 방식 모두 차원 결과(판정 + 최대 3문장)를 만들고, 인용이 있는 fact 문장마다 판정기
(prompts/market_claim_judge.md)가 인용 기사 제목·요약과 대조해 supported·partial·unsupported로
판정한다. 답변 모델은 세 방식 모두 ANALYSIS_MODEL이다.

방식:
    llm_only    자료 없이 기본 답변 규칙(prompts/market_answer_baseline.md)으로 답변
    naive_rag   차원 질의 dense 상위 5건을 그대로 주고 같은 규칙으로 답변
                (관련성 필터·판정 제한·문장 검증 없음)
    idealens    run_market_research 결과(MarketReport)의 해당 차원

방식별 지표:
    uncited_fact_rate   인용 없는 fact 문장 비율 (출처로 확인할 수 없는 사실 주장)
    citation_accuracy   인용된 fact 문장 중 supported 비율 (partial_rate는 따로)
    cited_relevance_rate  fact 문장이 인용한 기사 중 사람 정답 라벨로 관련(1)인 비율
                          (라벨 없는 기사는 cited_unlabeled로 따로 센다)
    unsourced_numbers   단위가 붙은 수치가 있고 그 숫자가 인용 기사·아이디어에 없는 fact 문장 수
    demand_confirmed    수요를 confirmed로 판정한 문항 수 (뉴스는 사업 신호이므로 과대 판정)

사용 예:
    python -m evaluation.market_answer_eval run --idea-ids SF-01,SF-02,SF-03,SF-04
    python -m evaluation.market_answer_eval sample      # 사람 검토용 표본 CSV (판정기 결과 숨김)
    python -m evaluation.market_answer_eval agreement   # 판정기 vs 사람 일치율·kappa
"""

import argparse
import csv
import json
import random
from collections import Counter
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from typing import Callable

from evaluation.market_labeling import (
    case_query,
    default_search_fn,
    idea_of,
    load_cases,
    load_ideas,
)
from src.generation.market_analysis import (
    MAX_CLAIMS,
    METRIC_PATTERN,
    call_analysis_llm,
    numbers_in,
)
from src.retrieval.market_relevance import call_relevance_llm
from src.schemas import IDEA_FIELDS, MarketReport, MarketSearchRequest, StructuredIdea

ROOT_DIR = Path(__file__).resolve().parents[1]
RESULTS_DIR = ROOT_DIR / "evaluation" / "results"
LABELS_DIR = ROOT_DIR / "evaluation" / "labels"
BASELINE_PROMPT_PATH = ROOT_DIR / "prompts" / "market_answer_baseline.md"
JUDGE_PROMPT_PATH = ROOT_DIR / "prompts" / "market_claim_judge.md"

ARMS = ["llm_only", "naive_rag", "idealens"]
VERDICTS = ["confirmed", "signal_only", "unverified"]
JUDGE_LABELS = ["supported", "partial", "unsupported"]
TOP_K = 5
MAX_WORKERS = 8
SAMPLE_PER_ARM = 15

CLAIM_FIELDS = [
    "case_id",
    "idea_id",
    "dimension",
    "arm",
    "verdict",
    "claim_index",
    "claim_type",
    "statement",
    "citation_ids",
    "sources",
    "source_relevance",
    "unsourced_number",
    "judge_label",
    "judge_error_type",
    "judge_reason",
]
ANSWER_FIELDS = ["case_id", "idea_id", "dimension", "arm", "verdict", "claims"]
REVIEW_FIELDS = [
    "case_id",
    "arm",
    "claim_index",
    "statement",
    "sources",
    "human_label",
    "note",
]

LLMFn = Callable[[str, str], dict]
ResearchFn = Callable[[str], MarketReport]
SearchFn = Callable[[str, int, str], list[dict]]


def source_entry(
    citation_id: int, source_id: str, title: str, summary: str, published_at: int
) -> dict:
    """답변·판정에 쓰는 기사 1건. source_id는 정답 라벨 대조용이며 LLM 입력에서는 뺀다."""
    return {
        "citation_id": citation_id,
        "source_id": source_id,
        "title": title,
        "summary": summary,
        "published_at": published_at,
    }


def llm_sources(sources: list[dict]) -> list[dict]:
    """LLM 입력용 기사 목록 (source_id 제외)."""
    return [{k: v for k, v in s.items() if k != "source_id"} for s in sources]


def hits_to_sources(hits: list[dict]) -> list[dict]:
    """검색 결과를 순위 순서대로 citation_id 1..n인 기사 목록으로 만든다."""
    sources = []
    for rank, hit in enumerate(hits, 1):
        _, _, summary = hit["text"].partition("\n")
        sources.append(
            source_entry(
                rank,
                hit["source_id"],
                hit["title"],
                summary.strip(),
                hit["published_at"],
            )
        )
    return sources


def report_sources(report: MarketReport) -> list[dict]:
    """MarketReport의 인용 근거를 기사 목록으로 만든다."""
    return [
        source_entry(e.citation_id, e.source_id, e.title, e.quote, e.published_at)
        for e in report.evidence
    ]


def source_relevance(case: dict, source_id: str) -> str:
    """사람 정답 라벨 기준 기사 관련성: 1 관련 · 0 비관련 · ? 라벨 없음."""
    if source_id in case.get("relevant_source_ids", []):
        return "1"
    return "0" if source_id in case.get("judged_source_ids", []) else "?"


def baseline_answer(
    case: dict, idea: StructuredIdea, sources: list[dict], answer_fn: LLMFn
) -> dict:
    """기본 답변 규칙으로 차원 결과를 만든다.

    판정이 허용 값이 아니면 unverified, 문장은 MAX_CLAIMS개까지, 인용은 주어진 기사 ID만 남긴다.
    """
    user_text = json.dumps(
        {
            "idea": idea.model_dump(include={"title", *IDEA_FIELDS}),
            "dimension": case["dimension"],
            "question": case["question"],
            "sources": llm_sources(sources),
        },
        ensure_ascii=False,
    )
    raw = answer_fn(BASELINE_PROMPT_PATH.read_text(encoding="utf-8"), user_text)
    valid_ids = {s["citation_id"] for s in sources}
    claims = []
    for claim in raw.get("claims") or []:
        if not isinstance(claim, dict) or not str(claim.get("statement", "")).strip():
            continue
        claims.append(
            {
                "statement": " ".join(str(claim["statement"]).split()),
                "claim_type": (
                    "ai_hypothesis"
                    if claim.get("claim_type") == "ai_hypothesis"
                    else "fact"
                ),
                "citation_ids": [
                    i for i in (claim.get("citation_ids") or []) if i in valid_ids
                ],
            }
        )
    verdict = raw.get("verdict") if raw.get("verdict") in VERDICTS else "unverified"
    return {"verdict": verdict, "claims": claims[:MAX_CLAIMS]}


def date_text(published_at: int) -> str:
    """YYYYMMDD 발행일을 '2026 3 15'처럼 앞자리 0 없는 연·월·일 숫자로 바꾼다 (시점 표기 허용용)."""
    return f"{published_at // 10000} {published_at // 100 % 100} {published_at % 100}"


def unsourced_number(statement: str, sources: list[dict], idea_text: str) -> bool:
    """단위가 붙은 수치가 있고 문장 속 숫자 중 인용 기사·아이디어에 없는 숫자가 있으면 True."""
    if not METRIC_PATTERN.search(statement):
        return False
    source_text = (
        idea_text
        + " "
        + " ".join(
            f"{s['title']} {s['summary']} {date_text(s['published_at'])}"
            for s in sources
        )
    )
    return bool(numbers_in(statement) - numbers_in(source_text))


def claim_rows(
    case: dict,
    arm: str,
    answer: dict,
    sources: list[dict],
    idea_text: str,
) -> list[dict]:
    """차원 결과 1개를 문장 단위 행으로 펼친다.

    각 행에는 그 문장이 인용한 기사와, 인용 기사별 정답 라벨 관련성(source_relevance)을 담는다.
    """
    by_id = {s["citation_id"]: s for s in sources}
    rows = []
    for index, claim in enumerate(answer["claims"], 1):
        cited = [by_id[i] for i in claim["citation_ids"] if i in by_id]
        rows.append(
            {
                "case_id": case["case_id"],
                "idea_id": case["idea_id"],
                "dimension": case["dimension"],
                "arm": arm,
                "verdict": answer["verdict"],
                "claim_index": index,
                "claim_type": claim["claim_type"],
                "statement": claim["statement"],
                "citation_ids": ";".join(str(s["citation_id"]) for s in cited),
                "sources": json.dumps(cited, ensure_ascii=False),
                "source_relevance": ";".join(
                    source_relevance(case, s["source_id"]) for s in cited
                ),
                "unsourced_number": int(
                    claim["claim_type"] == "fact"
                    and unsourced_number(claim["statement"], cited, idea_text)
                ),
                "judge_label": "",
                "judge_error_type": "",
                "judge_reason": "",
            }
        )
    return rows


def judge_input(row: dict) -> str:
    """판정 프롬프트 입력 JSON(문장·인용 기사). 관련성과 섞이지 않도록 질문은 넣지 않는다."""
    return json.dumps(
        {
            "statement": row["statement"],
            "sources": llm_sources(json.loads(row["sources"])),
        },
        ensure_ascii=False,
    )


def judge_claims(
    rows: list[dict],
    judge_fn: LLMFn = call_relevance_llm,
    max_workers: int = MAX_WORKERS,
) -> list[dict]:
    """인용이 있는 fact 문장을 병렬로 판정해 judge_* 열을 채운다. 나머지 행은 비워 둔다."""
    targets = [r for r in rows if r["claim_type"] == "fact" and r["citation_ids"]]
    system_prompt = JUDGE_PROMPT_PATH.read_text(encoding="utf-8")
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        raws = list(
            executor.map(
                lambda r: judge_fn(system_prompt, judge_input(r)),
                targets,
            )
        )
    for row, raw in zip(targets, raws):
        label = raw.get("label")
        row["judge_label"] = label if label in JUDGE_LABELS else "unsupported"
        row["judge_error_type"] = str(raw.get("error_type") or "")
        row["judge_reason"] = " ".join(str(raw.get("reason", "")).split())
    return rows


def ratio(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator, 3) if denominator else None


def summarize(answers: list[dict], claims: list[dict]) -> list[dict]:
    """방식별 판정 분포·문장 지표를 계산한다."""
    summary = []
    for arm in ARMS:
        arm_answers = [a for a in answers if a["arm"] == arm]
        if not arm_answers:
            continue
        verdicts = Counter(a["verdict"] for a in arm_answers)
        facts = [c for c in claims if c["arm"] == arm and c["claim_type"] == "fact"]
        cited = [c for c in facts if c["citation_ids"]]
        labels = Counter(c["judge_label"] for c in cited)
        errors = Counter(
            c["judge_error_type"] for c in cited if c["judge_label"] != "supported"
        )
        relevance = Counter(
            mark for c in cited for mark in c["source_relevance"].split(";") if mark
        )
        summary.append(
            {
                "arm": arm,
                "cases": len(arm_answers),
                **{f"verdict_{v}": verdicts[v] for v in VERDICTS},
                "demand_confirmed": sum(
                    a["dimension"] == "demand" and a["verdict"] == "confirmed"
                    for a in arm_answers
                ),
                "claims": sum(c["arm"] == arm for c in claims),
                "fact_claims": len(facts),
                "uncited_fact_rate": ratio(len(facts) - len(cited), len(facts)),
                "cited_facts": len(cited),
                **{label: labels[label] for label in JUDGE_LABELS},
                "citation_accuracy": ratio(labels["supported"], len(cited)),
                "partial_rate": ratio(labels["partial"], len(cited)),
                "cited_relevant": relevance["1"],
                "cited_irrelevant": relevance["0"],
                "cited_unlabeled": relevance["?"],
                "cited_relevance_rate": ratio(
                    relevance["1"], relevance["1"] + relevance["0"]
                ),
                "unsourced_numbers": sum(int(c["unsourced_number"]) for c in facts),
                "error_types": ";".join(f"{k}:{v}" for k, v in errors.most_common()),
            }
        )
    return summary


def default_research_fn(ideas: dict[str, dict]) -> ResearchFn:
    """샘플 아이디어로 실제 시장 조사(run_market_research)를 실행하는 함수를 만든다."""
    from src.services.market_service import run_market_research

    return lambda idea_id: run_market_research(
        MarketSearchRequest(idea=idea_of(ideas[idea_id])), idea_id=idea_id
    )


def collect_answers(
    cases: list[dict],
    ideas: dict[str, dict],
    reports: dict[str, MarketReport],
    search_fn: SearchFn,
    answer_fn: LLMFn = call_analysis_llm,
    max_workers: int = MAX_WORKERS,
) -> tuple[list[dict], list[dict]]:
    """문항마다 세 방식의 차원 결과를 모아 (답변 행, 문장 행)을 반환한다."""

    def answer_case(case: dict) -> list[tuple[str, dict, list[dict]]]:
        idea = idea_of(ideas[case["idea_id"]])
        hits = search_fn(case_query(case, ideas), TOP_K, case["idea_id"])
        naive_sources = hits_to_sources(hits)
        report = reports[case["idea_id"]]
        dimension = next(
            (d for d in report.dimensions if d.dimension == case["dimension"]), None
        )
        idealens = {
            "verdict": dimension.verdict if dimension else "unverified",
            "claims": [c.model_dump() for c in dimension.claims] if dimension else [],
        }
        return [
            ("llm_only", baseline_answer(case, idea, [], answer_fn), []),
            (
                "naive_rag",
                baseline_answer(case, idea, naive_sources, answer_fn),
                naive_sources,
            ),
            ("idealens", idealens, report_sources(report)),
        ]

    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        results = list(executor.map(answer_case, cases))

    answers, claims = [], []
    for case, arms in zip(cases, results):
        idea_text = " ".join(
            idea_of(ideas[case["idea_id"]])
            .model_dump(include={"title", *IDEA_FIELDS})
            .values()
        )
        for arm, answer, sources in arms:
            answers.append(
                {
                    "case_id": case["case_id"],
                    "idea_id": case["idea_id"],
                    "dimension": case["dimension"],
                    "arm": arm,
                    "verdict": answer["verdict"],
                    "claims": len(answer["claims"]),
                }
            )
            claims += claim_rows(case, arm, answer, sources, idea_text)
    return answers, claims


def write_csv(rows: list[dict], fields: list[str], path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields)
        writer.writeheader()
        writer.writerows(rows)
    return path


def read_csv(path: Path) -> list[dict]:
    with open(path, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def result_paths(label: str) -> dict[str, Path]:
    return {
        "answers": RESULTS_DIR / f"market_answer_{label}.csv",
        "claims": RESULTS_DIR / f"market_answer_claims_{label}.csv",
        "summary": RESULTS_DIR / f"market_answer_summary_{label}.csv",
        "reports": RESULTS_DIR / f"market_answer_reports_{label}.json",
        "review": LABELS_DIR / f"market_answer_review_{label}.csv",
    }


def run(idea_ids: list[str], label: str) -> list[dict]:
    """실제 색인·API로 세 방식을 실행·판정하고 결과 파일을 저장한다."""
    ideas = load_ideas()
    cases = [c for c in load_cases() if c["idea_id"] in idea_ids]
    research_fn = default_research_fn(ideas)
    reports = {idea_id: research_fn(idea_id) for idea_id in idea_ids}
    answers, claims = collect_answers(cases, ideas, reports, default_search_fn())
    judge_claims(claims)
    summary = summarize(answers, claims)

    paths = result_paths(label)
    write_csv(answers, ANSWER_FIELDS, paths["answers"])
    write_csv(claims, CLAIM_FIELDS, paths["claims"])
    write_csv(summary, list(summary[0]), paths["summary"])
    paths["reports"].write_text(
        json.dumps(
            {k: r.model_dump(mode="json") for k, r in reports.items()},
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )
    return summary


def review_sample(
    claims: list[dict], per_arm: int = SAMPLE_PER_ARM, seed: int = 0
) -> list[dict]:
    """판정된 문장을 방식별로 최대 per_arm개 뽑아 판정기 결과를 숨긴 검토 행을 만든다.

    supported가 아닌 문장은 모두 넣고, 남은 자리를 supported 문장에서 무작위로 채운다.
    """
    rng = random.Random(seed)
    sample = []
    for arm in ARMS:
        judged = [c for c in claims if c["arm"] == arm and c["judge_label"]]
        flagged = [c for c in judged if c["judge_label"] != "supported"][:per_arm]
        supported = [c for c in judged if c["judge_label"] == "supported"]
        sample += flagged + rng.sample(
            supported, min(per_arm - len(flagged), len(supported))
        )
    rng.shuffle(sample)
    return [
        {
            "case_id": c["case_id"],
            "arm": c["arm"],
            "claim_index": c["claim_index"],
            "statement": c["statement"],
            "sources": "\n".join(
                f"[{s['citation_id']}] {s['title']} — {s['summary']} ({s['published_at']})"
                for s in json.loads(c["sources"])
            ),
            "human_label": "",
            "note": "",
        }
        for c in sample
    ]


def agreement(review_rows: list[dict], claims: list[dict]) -> dict:
    """사람이 판정한 검토 행과 판정기 결과의 일치율·Cohen's kappa·혼동 행렬을 계산한다."""
    key = lambda r: (r["case_id"], r["arm"], str(r["claim_index"]))
    judged = {key(c): c["judge_label"] for c in claims}
    pairs = [
        (r["human_label"].strip(), judged[key(r)])
        for r in review_rows
        if r["human_label"].strip() in JUDGE_LABELS and key(r) in judged
    ]
    n = len(pairs)
    if not n:
        return {"n": 0, "agreement": None, "kappa": None, "confusion": {}}
    observed = sum(h == m for h, m in pairs) / n
    human = Counter(h for h, _ in pairs)
    model = Counter(m for _, m in pairs)
    expected = sum(human[label] * model[label] for label in JUDGE_LABELS) / n**2
    kappa = (observed - expected) / (1 - expected) if expected < 1 else 1.0
    return {
        "n": n,
        "agreement": round(observed, 3),
        "kappa": round(kappa, 3),
        "confusion": dict(Counter(f"{h}->{m}" for h, m in pairs)),
    }


def print_summary(summary: list[dict]) -> None:
    for row in summary:
        print(
            f"  {row['arm']:<10} 판정 {row['verdict_confirmed']}/{row['verdict_signal_only']}/"
            f"{row['verdict_unverified']} (확인/신호/미확인) 수요 confirmed {row['demand_confirmed']} | "
            f"fact {row['fact_claims']} 인용 없음 {row['uncited_fact_rate']} | "
            f"Citation Accuracy {row['citation_accuracy']} partial {row['partial_rate']} | "
            f"인용 기사 관련 {row['cited_relevance_rate']} (라벨 없음 {row['cited_unlabeled']}) | "
            f"출처 없는 수치 {row['unsourced_numbers']}"
        )


def main() -> None:
    """run(세 방식 실행·판정) / sample(사람 검토 표본) / agreement(판정기 일치율)."""
    parser = argparse.ArgumentParser(description="시장 답변 품질 평가")
    parser.add_argument("command", choices=["run", "sample", "agreement"])
    parser.add_argument("--idea-ids", default="SF-01,SF-02,SF-03,SF-04")
    parser.add_argument("--label", default="baseline", help="결과 파일 이름")
    args = parser.parse_args()
    paths = result_paths(args.label)

    if args.command == "run":
        print_summary(run(args.idea_ids.split(","), args.label))
        print(f"-> {paths['summary']}")
    elif args.command == "sample":
        rows = review_sample(read_csv(paths["claims"]))
        write_csv(rows, REVIEW_FIELDS, paths["review"])
        print(f"{len(rows)} rows -> {paths['review']} (human_label: {JUDGE_LABELS})")
    else:
        result = agreement(read_csv(paths["review"]), read_csv(paths["claims"]))
        print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
