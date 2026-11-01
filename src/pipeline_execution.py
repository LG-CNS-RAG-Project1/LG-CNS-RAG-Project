"""특허·시장 조사 실행과 영역별 시간 초과·부분 실패 처리를 담당한다."""

import logging
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import date
from typing import Callable

from src.generation.idea_parser import build_requests
from src.schemas import IdeaDraft
from src.pipeline_models import (
    Cancelled,
    MarketReport,
    PartRun,
    PatentReport,
    Readiness,
    RunState,
    SourceAnalysis,
)

MARKET_TIMEOUT = float(os.getenv("IDEALENS_MARKET_TIMEOUT", "120"))
PATENT_TIMEOUT = float(os.getenv("IDEALENS_PATENT_TIMEOUT", "180"))


class _EmptyCollection:
    """특허 색인이 없을 때 KIPRIS 보충 검색 경로로 넘기는 빈 컬렉션."""

    def count(self) -> int:
        return 0

    def get(self, *args, **kwargs) -> dict:
        return {"ids": [], "documents": [], "metadatas": []}

    def query(self, *args, **kwargs) -> dict:
        return {"ids": [[]], "distances": [[]]}


def _guard(fn: Callable, event: threading.Event) -> Callable:
    def guarded(*args, **kwargs):
        if event.is_set():
            raise Cancelled("제한 시간이 지나 외부 호출을 중단했습니다.")
        return fn(*args, **kwargs)

    return guarded


def _tolerant_relevance(event: threading.Event) -> Callable:
    """특허 관련성 판정 함수. 원래 판정(형식 검증 포함)을 최대 2회 시도하고,
    그래도 후보와 1:1로 맞지 않으면 마지막 응답에서 후보별 판정을 맞춘다.

    응답에서 빠진 후보는 관련 없음으로 두고(근거로 쓰지 않음) 후보에 없는 ID는 버린다.
    판정 형식 오류 하나로 특허 결과 전체가 error가 되는 것을 막기 위한 연결 계층의 보완이다.
    """
    from src.retrieval import patent_relevance

    def judge(idea, results):
        last = {}

        def llm(system_prompt, user_text):
            if event.is_set():
                raise Cancelled("제한 시간이 지나 외부 호출을 중단했습니다.")
            last["raw"] = patent_relevance.call_relevance_llm(system_prompt, user_text)
            return last["raw"]

        for _ in range(2):
            try:
                return patent_relevance.judge_patent_candidates(
                    idea, results, llm_fn=llm
                )
            except Cancelled:
                raise
            except ValueError:
                continue
        expected = [item.document.source_id for item in results]
        judged = {}
        for item in (last.get("raw") or {}).get("judgments", []):
            try:
                verdict = patent_relevance.RelevanceVerdict.model_validate(item)
            except ValueError:
                continue
            if verdict.source_id in expected:
                judged.setdefault(verdict.source_id, verdict)
        return {
            source_id: judged.get(source_id)
            or patent_relevance.RelevanceVerdict(
                source_id=source_id,
                relevant=False,
                confidence="low",
                reason="판정 응답에서 빠져 관련 없음으로 처리",
            )
            for source_id in expected
        }

    return judge


def _market_defaults(event: threading.Event) -> dict:
    from src.generation.market_analysis import call_analysis_llm
    from src.retrieval.market_relevance import call_relevance_llm
    from src.retrieval.market_search import embed_texts
    from src.services.market_financials import build_company_financials
    from src.services.market_network import build_keyword_network
    from src.services.market_procurement import build_procurement
    from src.services.market_trend import build_search_trend

    return {
        "embed_fn": _guard(embed_texts, event),
        "judge_fn": _guard(call_relevance_llm, event),
        "llm_fn": _guard(call_analysis_llm, event),
        "trend_fn": _guard(build_search_trend, event),
        "network_fn": _guard(build_keyword_network, event),
        "financials_fn": _guard(build_company_financials, event),
        "procurement_fn": _guard(build_procurement, event),
    }


def _patent_defaults(event: threading.Event) -> dict:
    from src import pipeline
    from src.generation.patent_analysis import (
        call_comparison_llm,
        review_patents_by_component,
    )
    from src.generation.patent_design import generate_patent_design_analysis
    from src.ingestion.kipris_client import fetch_patent_claims
    from src.ingestion.kipris_client import search_patents as search_kipris
    from src.retrieval.market_search import embed_texts
    from src.retrieval.patent_search import call_query_llm

    guarded_review_llm = _guard(call_comparison_llm, event)
    guarded_embed = _guard(embed_texts, event)

    def review(idea, evidence):
        return review_patents_by_component(idea, evidence, llm_fn=guarded_review_llm)

    def design_proposals(idea, evidence, reviews, precheck):
        return generate_patent_design_analysis(
            idea, evidence, reviews, precheck, llm_fn=guarded_review_llm
        )

    def score_semantic_similarity(idea, evidence, source_texts):
        return pipeline.score_patent_semantic_similarity(
            idea, evidence, source_texts, embed_fn=guarded_embed
        )

    return {
        "embed_fn": guarded_embed,
        "query_llm_fn": _guard(call_query_llm, event),
        "claim_fetcher": _guard(fetch_patent_claims, event),
        "kipris_search_fn": _guard(search_kipris, event),
        "patent_review_fn": review,
        "design_proposal_fn": design_proposals,
        "relevance_fn": _tolerant_relevance(event),
        "semantic_similarity_fn": score_semantic_similarity,
    }


def _timed(fn: Callable, *args, **kwargs):
    started = time.monotonic()
    report = fn(*args, **kwargs)
    return report, time.monotonic() - started


def _part_from_report(report, seconds: float) -> PartRun:
    from src import pipeline

    message = report.error_message if report.status in {"error", "partial"} else None
    return PartRun(
        state=report.status, seconds=round(seconds, 1), message=pipeline.redact(message)
    )


def analyze_sources(
    draft: IdeaDraft,
    *,
    technical_components: list[str] | None = None,
    technology_area_id: str | None = None,
    patent_kwargs: dict | None = None,
    market_kwargs: dict | None = None,
    readiness: Readiness | None = None,
    parallel: bool | None = None,
    market_timeout: float = MARKET_TIMEOUT,
    patent_timeout: float = PATENT_TIMEOUT,
    progress_callback: Callable[[str, object, PartRun], None] | None = None,
) -> SourceAnalysis:
    """시장·특허 조사를 실행한다. 준비되지 않은 영역은 호출하지 않고 skipped로 둔다.

    patent_kwargs·market_kwargs로 넘긴 값(컬렉션·호출 함수)이 기본값보다 우선한다.
    readiness를 넘기면 그 판정을 쓰고 색인 점검을 건너뛴다(컬렉션은 kwargs로 주입).
    """
    from src import pipeline

    started = time.monotonic()
    patent_request, market_request = build_requests(draft)
    patent_request.technology_area_id = technology_area_id
    if technical_components is not None:
        patent_request.idea.technical_components = technical_components
        market_request.idea.technical_components = technical_components

    market_collection = patent_collection = None
    if readiness is None:
        readiness, market_collection, patent_collection = pipeline.prepare_sources(
            technology_area_id
        )
    if (
        technology_area_id
        and readiness.patent_index.count
        and not readiness.patent_index.area_counts.get(technology_area_id, 0)
    ):
        # 오래된 세션의 고정 분야 선택이 비어 있는 분야를 가리켜도 검색을 중단하지 않는다.
        patent_request.technology_area_id = None

    event = threading.Event()
    market_args = {**_market_defaults(event), **(market_kwargs or {})}
    patent_args = {**_patent_defaults(event), **(patent_kwargs or {})}
    if market_collection is not None:
        market_args.setdefault("collection", market_collection)
    if "collection" not in patent_args:
        patent_args["collection"] = patent_collection or _EmptyCollection()

    jobs = {}
    if readiness.market_runnable:
        jobs["market"] = (
            pipeline.run_market_research,
            market_request,
            market_args,
            market_timeout,
        )
    if readiness.patent_mode != "none":
        jobs["patent"] = (
            pipeline.analyze_patents,
            patent_request,
            patent_args,
            patent_timeout,
        )

    if parallel is None:
        parallel = os.getenv("IDEALENS_SERIAL", "") != "1"
    if progress_callback is not None:
        # The UI's step-by-step flow needs the patent result before starting
        # the market phase. Keep ordinary CLI/pipeline callers parallel.
        jobs = {kind: jobs[kind] for kind in ("patent", "market") if kind in jobs}
        parallel = False
    results = _run_jobs(jobs, event, parallel, on_result=progress_callback)

    skipped_reason = "; ".join(readiness.reasons) or "실행 조건 미충족"
    market_report, market_run = results.get(
        "market",
        (
            MarketReport(status="no_results", search_scope="시장 조사를 실행하지 않음"),
            PartRun(state="skipped", message=skipped_reason),
        ),
    )
    patent_report, patent_run = results.get(
        "patent",
        (
            PatentReport(status="no_results", search_scope="특허 조사를 실행하지 않음"),
            PartRun(state="skipped", message=skipped_reason),
        ),
    )
    patent_report, market_report = pipeline._redacted(
        patent_report
    ), pipeline._redacted(market_report)
    for label, run, report in (
        ("특허", patent_run, patent_report),
        ("시장", market_run, market_report),
    ):
        level = logging.WARNING if run.state in ("error", "timeout") else logging.INFO
        pipeline.LOG.log(
            level,
            "%s 조사 %s (%ss, 근거 %d건)%s",
            label,
            run.state,
            run.seconds,
            len(report.evidence),
            f": {run.message}" if run.message else "",
        )
        for item in report.unknowns:
            pipeline.LOG.info("%s 미확인: %s", label, item)
    if progress_callback is not None:
        for kind, report, run in (
            ("patent", patent_report, patent_run),
            ("market", market_report, market_run),
        ):
            if kind not in jobs:
                progress_callback(kind, report, run)
    return SourceAnalysis(
        patent=patent_report,
        market=market_report,
        patent_run=patent_run,
        market_run=market_run,
        readiness=readiness,
        analyzed_on=int(date.today().strftime("%Y%m%d")),
        total_seconds=round(time.monotonic() - started, 1),
    )


def _failed(kind: str, state: RunState, message: str, seconds: float | None):
    model = MarketReport if kind == "market" else PatentReport
    report = model(status="error", search_scope="조사 미완료", error_message=message)
    return report, PartRun(state=state, seconds=seconds, message=message)


def _run_jobs(
    jobs: dict,
    event: threading.Event,
    parallel: bool,
    on_result: Callable[[str, object, PartRun], None] | None = None,
) -> dict:
    """영역별로 제한 시간 안에 실행하고 예외·시간 초과를 그 영역 결과로만 남긴다."""
    results = {}
    if not jobs:
        return results
    pool = ThreadPoolExecutor(max_workers=len(jobs) if parallel else 1)
    try:
        if parallel:
            futures = {
                kind: (pool.submit(_timed, fn, request, **kwargs), timeout)
                for kind, (fn, request, kwargs, timeout) in jobs.items()
            }
            started = time.monotonic()
            for kind, (future, timeout) in futures.items():
                remaining = max(0.0, timeout - (time.monotonic() - started))
                results[kind] = _collect(kind, future, remaining, event)
                if on_result:
                    on_result(kind, *results[kind])
        else:
            for kind, (fn, request, kwargs, timeout) in jobs.items():
                future = pool.submit(_timed, fn, request, **kwargs)
                results[kind] = _collect(kind, future, timeout, event)
                if on_result:
                    on_result(kind, *results[kind])
    finally:
        pool.shutdown(wait=False, cancel_futures=True)
    return results


def _collect(kind: str, future, timeout: float, event: threading.Event):
    from src import pipeline

    try:
        report, seconds = future.result(timeout=timeout)
    except FutureTimeout:
        event.set()
        return _failed(
            kind,
            "timeout",
            f"제한 시간 {timeout:.0f}초 초과로 중단(진행 중이던 호출은 끝날 때까지 남을 수 있음)",
            round(timeout, 1),
        )
    except Exception as exc:
        return _failed(
            kind, "error", pipeline.redact(f"{type(exc).__name__}: {exc}"), None
        )
    return report, _part_from_report(report, seconds)
