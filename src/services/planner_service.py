"""사업기획 근거 자료집 진입점: refresh · reanalyze · replay · review.

- refresh: 예산 안에서 뉴스 수집 → 본문 수집 → 기사별 추출 → 규칙 판정 → 후속 질문 라운드(최대 3회)
  → 새 실행 폴더에 게시. 부모 실행의 추출 결과는 캐시로만 쓰고 부모 폴더는 바꾸지 않는다.
- reanalyze: 같은 기사로 현재 규칙·프롬프트를 다시 적용한 새 실행(검색 없음).
- replay: 저장 파일만 읽어 의미 결과를 재계산하고 해시를 대조한다. 검색·HTTP·LLM·Chroma 호출 없음.
- review: 근거 승인·제외와 가격 입력을 새 revision으로 추가한다.

사용 예:
    python -m src.services.planner_service refresh --idea-id SF-02
    python -m src.services.planner_service replay <run_id 또는 경로>
    python -m src.services.planner_service list --area SF-02
"""

import argparse
import json
import subprocess
import time
from collections import Counter
from collections.abc import Callable
from pathlib import Path

from src.planner import store
from src.planner.analyze import analyze
from src.planner.anchors import attach_mention_index, process_articles
from src.planner.assumptions import select_followups
from src.planner.body import BodyFetcher
from src.planner.collect import (
    Collection,
    collect_followup,
    collect_initial,
    default_search,
    now_kst,
)
from src.planner.config import (
    Profile,
    QuestionBank,
    load_profile,
    load_question_bank,
    profile_hash,
)
from src.planner.diff import diff_results
from src.planner.extract import (
    EXTRACTOR_VERSION,
    SCHEMA_HASH,
    Extractor,
    call_extraction_llm,
    validate_response,
)
from src.planner.pricing import CALC_VERSION
from src.planner.rules import RULE_VERSION
from src.planner.schemas import (
    Anchor,
    ExtractionRecord,
    RunManifest,
    SemanticResult,
)
from src.schemas import StructuredIdea

ROOT_DIR = Path(__file__).resolve().parents[2]
IDEAS_PATH = ROOT_DIR / "data" / "samples" / "ideas.json"
BUDGET_STOPS = {"budget_exhausted", "request_cap_reached", "candidate_cap_reached"}
# 후속 라운드에서 질문별 새 근거로 세는 근거 종류(질문 ID 첫 글자 기준)
GAIN_KINDS = {
    "C": {"claim", "supplier"},
    "G": {"relation"},
    "D": {"relation"},
    "M": {"relation", "supplier"},
    "T": {"relation"},
    "R": {"adverse", "relation"},
    "E": {"metric"},
}


def git_commit() -> str:
    try:
        out = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=ROOT_DIR,
            capture_output=True,
            text=True,
            timeout=5,
        )
        return out.stdout.strip() or "unknown"
    except (OSError, subprocess.SubprocessError):
        return "unknown"


def versions_for(profile, prompt_hash: str, bank: QuestionBank) -> dict:
    digest = profile_hash(profile)
    return {
        "rule_version": f"{RULE_VERSION}+{digest[:12]}",
        "extractor_version": EXTRACTOR_VERSION,
        "prompt_hash": prompt_hash,
        "schema_hash": SCHEMA_HASH,
        "profile_hash": digest,
        "question_bank": f"{bank.version}+{store.sha256_hex(store.canonical_json(bank))[:12]}",
        "calc_version": CALC_VERSION,
        "model": profile.model,
    }


def _collection_summary(
    collection: Collection, rejected: list[dict], followups
) -> dict:
    excluded = Counter(
        row["reason"] for row in collection.selection if row["decision"] == "excluded"
    )
    return {
        "requests_used": collection.requests_used,
        "candidates_seen": collection.candidates_seen,
        "excluded_by_reason": dict(sorted(excluded.items())),
        "shortfalls": collection.shortfalls,
        "stops": collection.stops,
        "span_not_found": sum(1 for r in rejected if r["reason"] == "span_not_found"),
        "followups": followups,
    }


class _Pipeline:
    """refresh 한 번의 누적 상태(기사·본문·추출·Anchor)."""

    def __init__(self, profile, extractor, fetcher, progress):
        self.profile = profile
        self.extractor = extractor
        self.fetcher = fetcher
        self.progress = progress
        self.records, self.metas, self.extractions = [], [], []
        self.anchors, self.rejected = [], []
        self.bodies, self.statuses, self.texts = {}, {}, {}
        self.body_fetches = 0

    def process(self, records: list[dict], stage: str) -> None:
        for n, record in enumerate(records, 1):
            sid = record["source_id"]
            if self.fetcher is None:
                self.statuses[sid] = "disabled"
            elif self.body_fetches >= self.profile.budget.max_body_fetches:
                self.statuses[sid] = "cap_reached"
            else:
                self.body_fetches += 1
                result = self.fetcher.fetch(record["url"], record["snippet"])
                self.statuses[sid] = result.status
                if result.status == "ok":
                    self.bodies[sid] = result.text
            self.progress(f"{stage} 본문 확인", n, len(records))
        result = process_articles(
            records, self.bodies, self.statuses, self.extractor, self.profile
        )
        self.records += records
        self.metas += result["articles"]
        self.extractions += result["extractions"]
        self.anchors += result["anchors"]
        self.rejected += result["rejected"]
        self.texts.update(result["texts"])
        attach_mention_index(self.metas, self.anchors, self.texts)


def _analyze(
    idea, digest, area_id, profile, bank, pipeline, collection, followups, versions
):
    return analyze(
        idea,
        digest,
        area_id,
        profile,
        bank,
        pipeline.metas,
        pipeline.anchors,
        _collection_summary(collection, pipeline.rejected, followups),
        {"revision": 0, "reviews": [], "user_inputs": {}},
        versions,
    )


def _parent_cache(parent: Path | None) -> dict:
    """이전 실행의 추출 결과를 캐시로 만든다. 실패 기록은 저장된 원응답을 현재 검증 규칙으로
    다시 검사해 통과하면 쓴다(LLM 재호출 없음)."""
    if not parent:
        return {}
    responses: dict[str, list[dict]] = {}
    for row in store.read_jsonl(Path(parent) / "llm_responses.jsonl"):
        responses.setdefault(row["cache_key"], []).append(row)
    cache = {}
    for row in store.read_jsonl(Path(parent) / "extraction.jsonl"):
        record = ExtractionRecord.model_validate(row)
        if not record.cache_key:
            continue
        if record.status == "ok":
            cache[record.cache_key] = record.candidates
            continue
        for raw in reversed(responses.get(record.cache_key, [])):
            candidates, error = validate_response(
                raw, record.source_id, set(record.input_sentence_ids)
            )
            if not error:
                cache[record.cache_key] = candidates
                break
    return cache


def refresh(
    idea: StructuredIdea,
    area_id: str,
    *,
    root: Path | None = None,
    search_fn=default_search,
    http_get=None,
    llm_fn=call_extraction_llm,
    parent: Path | None = None,
    body: bool = True,
    clock: Callable = now_kst,
    sleep: Callable[[float], None] = time.sleep,
    progress: Callable[[str, int, int], None] | None = None,
    cancelled: Callable[[], bool] = lambda: False,
) -> Path:
    """새 자료집을 만든다. 실패하거나 취소되면 게시하지 않고 staging을 지운다."""
    progress = progress or (lambda stage, done, total: None)
    started = time.perf_counter()
    profile = load_profile(area_id)
    bank = load_question_bank()
    digest = store.idea_hash(idea, area_id)
    as_of = clock().strftime("%Y%m%d")
    run_id = store.new_run_id(as_of)
    staging = store.Staging(root or store.runs_root(), area_id, digest, run_id)
    try:
        collection = Collection(
            profile, search_fn, clock=clock, sleep=sleep, cancelled=cancelled
        )
        fetcher = (
            BodyFetcher(
                http_get,
                sleep=sleep,
                deny_domains=profile.body_fetch.deny_domains,
                cancelled=cancelled,
            )
            if body and profile.body_fetch.enabled
            else None
        )
        extractor = Extractor(profile, llm_fn, _parent_cache(parent), cancelled)
        versions = versions_for(profile, extractor.prompt_hash, bank)
        pipeline = _Pipeline(profile, extractor, fetcher, progress)

        progress("초기 검색", 0, profile.budget.initial_articles)
        pipeline.process(collect_initial(collection), "초기")
        rounds, exhausted, stop_reasons = [], set(), {}
        for round_no in range(1, profile.budget.max_followup_rounds + 1):
            if cancelled() or set(collection.stops) & BUDGET_STOPS:
                break
            interim = _analyze(
                idea,
                digest,
                area_id,
                profile,
                bank,
                pipeline,
                collection,
                {"rounds": rounds, "stop_reasons": {}},
                versions,
            )
            picks = select_followups(interim.questions, exhausted)
            if not picks:
                break
            progress(f"후속 {round_no}차 검색", 0, profile.budget.followup_batch)
            new = collect_followup(
                collection,
                [{"question_id": p.question_id, "queries": p.queries} for p in picks],
                round_no,
            )
            pipeline.process(new, f"후속 {round_no}차")
            after = _analyze(
                idea,
                digest,
                area_id,
                profile,
                bank,
                pipeline,
                collection,
                {"rounds": rounds, "stop_reasons": {}},
                versions,
            )
            new_ids = {r["source_id"] for r in new}
            gained = {}
            for pick in picks:
                sources = {
                    r["source_id"] for r in new if r["question_id"] == pick.question_id
                }
                kinds = GAIN_KINDS.get(pick.question_id[0], set())
                gained[pick.question_id] = sum(
                    1
                    for e in after.evidence
                    if e.source_id in sources
                    and e.review_status == "approved"
                    and e.kind in kinds
                )
                if not gained[pick.question_id]:
                    exhausted.add(pick.question_id)
                    stop_reasons[pick.question_id] = (
                        "no_new_evidence_within_capped_search"
                    )
            rounds.append(
                {
                    "round": round_no,
                    "questions": [p.question_id for p in picks],
                    "queries": [q for p in picks for q in p.queries],
                    "retained": sorted(new_ids),
                    "new_approved_evidence": gained,
                }
            )
        if cancelled():
            raise RuntimeError("사용자가 자료집 생성을 취소했습니다.")
        final_gap_reason = "budget_exhausted"
        followups = {"rounds": rounds, "stop_reasons": stop_reasons}
        semantic = _analyze(
            idea,
            digest,
            area_id,
            profile,
            bank,
            pipeline,
            collection,
            followups,
            versions,
        )
        for pick in semantic.questions:
            if pick.status == "gap" and pick.question_id not in stop_reasons:
                stop_reasons[pick.question_id] = (
                    final_gap_reason if pick.queries else "slot_unfilled"
                )
        followups["stop_reasons"] = dict(sorted(stop_reasons.items()))
        semantic = _analyze(
            idea,
            digest,
            area_id,
            profile,
            bank,
            pipeline,
            collection,
            followups,
            versions,
        )
        _write_run(
            staging,
            idea=idea,
            digest=digest,
            area_id=area_id,
            profile=profile,
            bank=bank,
            collection=collection,
            pipeline=pipeline,
            followups=followups,
            semantic=semantic,
            parent=parent,
            run_log={
                "seconds": round(time.perf_counter() - started, 1),
                "search_requests": collection.requests_used,
                "body_requests": fetcher.requests_made if fetcher else 0,
                "llm_calls": extractor.calls,
                "llm_cache_hits": sum(1 for e in pipeline.extractions if e.from_cache),
                "llm_retries_used": profile.budget.llm_retry_total
                - extractor.retries_left,
            },
            llm_log=extractor.log,
        )
        manifest = RunManifest(
            run_id=run_id,
            parent_run_id=_run_id(parent),
            mode="refresh",
            idea_hash=digest,
            area_id=area_id,
            idea_title=idea.title,
            as_of=as_of,
            versions=versions,
            budget=profile.budget.model_dump(),
            git_commit=git_commit(),
        )
        return staging.publish(manifest)
    except BaseException:
        staging.discard()
        raise


def _run_id(path: Path | None) -> str:
    if not path:
        return ""
    return store.read_json(Path(path) / "manifest.json")["run_id"]


def _write_run(
    staging,
    *,
    idea,
    digest,
    area_id,
    profile,
    bank,
    collection,
    pipeline,
    followups,
    semantic,
    parent,
    run_log,
    llm_log,
    query_plan=None,
    raw_responses=None,
    selection=None,
):
    staging.write_json(
        "idea.json",
        {"idea": idea.model_dump(), "area_id": area_id, "idea_hash": digest},
    )
    staging.write_json("profile.json", profile)
    staging.write_json("question_bank.json", bank)
    plan = query_plan or {
        "initial": collection.query_plan,
        "budget": profile.budget.model_dump(),
        "collection": _collection_summary(collection, pipeline.rejected, followups),
    }
    plan["collection"]["followups"] = followups
    staging.write_json("query_plan.json", plan)
    for n, row in enumerate(
        raw_responses if raw_responses is not None else collection.raw_responses, 1
    ):
        staging.write_json(f"raw_responses/{n:04d}.json", row)
    staging.write_json(
        "selection.json",
        selection if selection is not None else {"rows": collection.selection},
    )
    staging.write_jsonl("articles.jsonl", pipeline.metas)
    for sid, text in sorted(pipeline.bodies.items()):
        staging.write_text(f"bodies/{sid}.txt", text)
    rejected_by_source = {}
    for row in pipeline.rejected:
        rejected_by_source.setdefault(row["source_id"], []).append(row)
    staging.write_jsonl(
        "extraction.jsonl",
        [
            e.model_copy(update={"rejected": rejected_by_source.get(e.source_id, [])})
            for e in pipeline.extractions
        ],
    )
    staging.write_jsonl("llm_responses.jsonl", llm_log)
    staging.write_jsonl("anchors.jsonl", pipeline.anchors)
    store.write_semantic(
        staging, 0, {"revision": 0, "reviews": [], "user_inputs": {}}, semantic
    )
    if parent:
        _, parent_semantic, _ = store.load_revision(parent, 0)
        staging.write_json(
            "diff.json",
            diff_results(SemanticResult.model_validate(parent_semantic), semantic),
        )
    staging.write_json("run_log.json", run_log)


def load_inputs(path: Path) -> dict:
    """replay·review에 필요한 저장 입력을 읽는다(파일 해시 검증 포함)."""
    path = Path(path)
    checked = store.verify_run(path)
    idea_file = store.read_json(path / "idea.json")
    return {
        "manifest": checked["manifest"],
        "missing_optional": checked["missing_optional"],
        "profile": Profile.model_validate(store.read_json(path / "profile.json")),
        "bank": QuestionBank.model_validate(
            store.read_json(path / "question_bank.json")
        ),
        "idea": StructuredIdea.model_validate(idea_file["idea"]),
        "area_id": idea_file["area_id"],
        "idea_hash": idea_file["idea_hash"],
        "articles": store.read_jsonl(path / "articles.jsonl"),
        "anchors": [
            Anchor.model_validate(a) for a in store.read_jsonl(path / "anchors.jsonl")
        ],
        "collection": store.read_json(path / "query_plan.json")["collection"],
    }


def _recompute(inputs: dict, revision: dict) -> SemanticResult:
    """실행에 저장된 프로필·질문 은행으로 재계산한다(현재 설정 파일 변경의 영향을 받지 않음)."""
    return analyze(
        inputs["idea"],
        inputs["idea_hash"],
        inputs["area_id"],
        inputs["profile"],
        inputs["bank"],
        inputs["articles"],
        inputs["anchors"],
        inputs["collection"],
        revision,
        inputs["manifest"].versions,
    )


def replay(path: Path, revision: int | None = None) -> dict:
    """저장 파일로 의미 결과를 재계산하고 저장 해시와 대조한다. 외부 호출은 하지 않는다."""
    path = Path(path)
    inputs = load_inputs(path)
    revision = store.latest_revision(path) if revision is None else revision
    payload, stored, stored_hash = store.load_revision(path, revision)
    computed = _recompute(inputs, payload)
    computed_hash = store.semantic_hash(computed)
    try:
        current = load_profile(inputs["area_id"])
        current_rule = f"{RULE_VERSION}+{profile_hash(current)[:12]}"
    except (OSError, ValueError):
        current_rule = ""
    return {
        "path": path,
        "manifest": inputs["manifest"],
        "revision": revision,
        "revision_payload": payload,
        "semantic": SemanticResult.model_validate(stored),
        "computed": computed,
        "stored_hash": stored_hash,
        "computed_hash": computed_hash,
        "match": stored_hash == computed_hash,
        "rule_drift": inputs["manifest"].versions.get("rule_version") != current_rule,
        "missing_optional": inputs["missing_optional"],
        "diff": (
            store.read_json(path / "diff.json")
            if (path / "diff.json").exists()
            else None
        ),
    }


def review(
    path: Path,
    decisions: list[dict] | None = None,
    price: dict | None = None,
    note: str = "",
    clock: Callable = now_kst,
) -> tuple[int, str]:
    """검토 결정·가격 입력을 누적한 새 revision을 추가한다. (revision 번호, 의미 결과 해시)."""
    path = Path(path)
    inputs = load_inputs(path)
    latest = store.latest_revision(path)
    previous, _, _ = store.load_revision(path, latest)
    reviews = {r["evidence_id"]: r for r in previous.get("reviews", [])}
    for decision in decisions or []:
        if decision.get("decision") not in {"approve", "reject"}:
            raise ValueError("decision은 approve 또는 reject")
        if not decision.get("reason", "").strip():
            raise ValueError("검토 사유가 필요합니다")
        reviews[decision["evidence_id"]] = {
            "evidence_id": decision["evidence_id"],
            "decision": decision["decision"],
            "reason": decision["reason"].strip(),
        }
    user_inputs = dict(previous.get("user_inputs", {}))
    if price is not None:
        user_inputs["price"] = price
    payload = {
        "revision": latest + 1,
        "parent_revision": latest,
        "reviews": [reviews[key] for key in sorted(reviews)],
        "user_inputs": user_inputs,
        "note": note,
        "created_at": clock().isoformat(),
    }
    semantic = _recompute(inputs, payload)
    digest = store.write_semantic(path, latest + 1, payload, semantic)
    return latest + 1, digest


def reanalyze(
    path: Path,
    *,
    root: Path | None = None,
    llm_fn=None,
    clock: Callable = now_kst,
) -> Path:
    """같은 기사·본문으로 현재 규칙·프롬프트를 다시 적용한 새 실행을 만든다(검색·본문 수집 없음)."""
    path = Path(path)
    inputs = load_inputs(path)
    area_id, idea, digest = inputs["area_id"], inputs["idea"], inputs["idea_hash"]
    profile = load_profile(area_id)
    bank = load_question_bank()
    extractor = Extractor(profile, llm_fn, _parent_cache(path))
    versions = versions_for(profile, extractor.prompt_hash, bank)
    records, bodies, statuses = [], {}, {}
    for meta in inputs["articles"]:
        sid = meta["source_id"]
        statuses[sid] = meta["body_status"]
        body_path = path / "bodies" / f"{sid}.txt"
        if body_path.exists():
            bodies[sid] = body_path.read_text("utf-8")
        elif meta["body_status"] == "ok":
            statuses[sid] = "not_attempted"
        records.append(
            {
                k: v
                for k, v in meta.items()
                if k
                not in {
                    "snippet_truncated",
                    "body_status",
                    "layers",
                    "extraction_status",
                    "mentioned_entity_ids",
                }
            }
        )
    pipeline = _Pipeline(profile, extractor, None, lambda *a: None)
    result = process_articles(records, bodies, statuses, extractor, profile)
    pipeline.metas, pipeline.extractions = result["articles"], result["extractions"]
    pipeline.anchors, pipeline.rejected = result["anchors"], result["rejected"]
    pipeline.bodies = bodies
    collection = dict(inputs["collection"])
    collection["span_not_found"] = sum(
        1 for r in pipeline.rejected if r["reason"] == "span_not_found"
    )
    semantic = analyze(
        idea,
        digest,
        area_id,
        profile,
        bank,
        pipeline.metas,
        pipeline.anchors,
        collection,
        {"revision": 0, "reviews": [], "user_inputs": {}},
        versions,
    )
    as_of = clock().strftime("%Y%m%d")
    run_id = store.new_run_id(as_of)
    staging = store.Staging(root or store.runs_root(), area_id, digest, run_id)
    try:
        plan = store.read_json(path / "query_plan.json")
        plan["collection"] = collection
        plan["reanalyzed_from"] = inputs["manifest"].run_id
        raw = [
            store.read_json(p) for p in sorted((path / "raw_responses").glob("*.json"))
        ]
        _write_run(
            staging,
            idea=idea,
            digest=digest,
            area_id=area_id,
            profile=profile,
            bank=bank,
            collection=None,
            pipeline=pipeline,
            followups=collection.get("followups", {}),
            semantic=semantic,
            parent=path,
            run_log={"llm_calls": extractor.calls, "mode": "reanalyze"},
            llm_log=extractor.log,
            query_plan=plan,
            raw_responses=raw,
            selection=store.read_json(path / "selection.json"),
        )
        manifest = RunManifest(
            run_id=run_id,
            parent_run_id=inputs["manifest"].run_id,
            mode="reanalyze",
            idea_hash=digest,
            area_id=area_id,
            idea_title=idea.title,
            as_of=as_of,
            versions=versions,
            budget=profile.budget.model_dump(),
            git_commit=git_commit(),
        )
        return staging.publish(manifest)
    except BaseException:
        staging.discard()
        raise


def sample_idea(idea_id: str) -> StructuredIdea:
    entries = json.loads(IDEAS_PATH.read_text("utf-8"))
    entry = next(e for e in entries if e["idea_id"] == idea_id)
    return StructuredIdea(**entry["idea"])


def main() -> None:
    parser = argparse.ArgumentParser(description="사업기획 근거 자료집")
    sub = parser.add_subparsers(dest="command", required=True)
    p = sub.add_parser("refresh", help="새 자료집 생성(NAVER·OpenAI 호출, 비용 발생)")
    p.add_argument("--idea-id", required=True)
    p.add_argument("--area", help="분야 프로필 ID(기본: idea-id)")
    p.add_argument("--parent", help="캐시로 쓸 이전 실행 ID 또는 경로")
    p.add_argument("--no-body", action="store_true", help="본문 자동 수집 끔")
    p = sub.add_parser("replay", help="저장 결과 재계산·해시 대조(외부 호출 없음)")
    p.add_argument("run")
    p.add_argument("--revision", type=int)
    p = sub.add_parser("reanalyze", help="같은 기사로 현재 규칙 재적용(검색 없음)")
    p.add_argument("run")
    p.add_argument(
        "--allow-llm", action="store_true", help="캐시에 없는 기사만 LLM 호출"
    )
    p = sub.add_parser("review", help="근거 승인·제외를 revision으로 추가")
    p.add_argument("run")
    p.add_argument("--approve", action="append", default=[])
    p.add_argument("--reject", action="append", default=[])
    p.add_argument("--reason", required=True)
    p = sub.add_parser("list", help="저장된 실행 목록")
    p.add_argument("--area")
    args = parser.parse_args()

    if args.command == "refresh":
        area = args.area or args.idea_id
        parent = store.find_run(None, args.parent) if args.parent else None

        def show(stage, done, total):
            print(f"  {stage} {done}/{total}", flush=True)

        path = refresh(
            sample_idea(args.idea_id),
            area,
            parent=parent,
            body=not args.no_body,
            progress=show,
        )
        report = replay(path)
        log = store.read_json(path / "run_log.json")
        print(f"published {path}")
        print(f"  counts {json.dumps(report['semantic'].counts, ensure_ascii=False)}")
        print(f"  calls {json.dumps(log, ensure_ascii=False)}")
        print(f"  replay hash match: {report['match']}")
    elif args.command == "replay":
        report = replay(store.find_run(None, args.run), args.revision)
        print(
            json.dumps(
                {
                    "run_id": report["manifest"].run_id,
                    "revision": report["revision"],
                    "match": report["match"],
                    "stored_hash": report["stored_hash"],
                    "computed_hash": report["computed_hash"],
                    "rule_drift": report["rule_drift"],
                    "missing_optional": len(report["missing_optional"]),
                },
                ensure_ascii=False,
                indent=1,
            )
        )
    elif args.command == "reanalyze":
        source = store.find_run(None, args.run)
        path = reanalyze(source, llm_fn=call_extraction_llm if args.allow_llm else None)
        print(f"published {path}")
    elif args.command == "review":
        decisions = [
            {"evidence_id": e, "decision": "approve", "reason": args.reason}
            for e in args.approve
        ] + [
            {"evidence_id": e, "decision": "reject", "reason": args.reason}
            for e in args.reject
        ]
        rev, digest = review(store.find_run(None, args.run), decisions)
        print(f"revision {rev} {digest}")
    else:
        for run in store.list_runs(None, args.area):
            m = run["manifest"]
            print(f"{m.run_id}\t{m.mode}\t{m.area_id}\t{m.idea_title}\t{run['path']}")


if __name__ == "__main__":
    main()
