"""완성된 아이디어를 특허·시장 조사와 근거 연결 보고서로 실행한다.

- 색인 준비 점검(check_readiness): 로컬 색인은 파일 존재로, 공용 Chroma는 제한 시간이 있는
  heartbeat로 확인하고, 컬렉션을 새로 만들지 않고 연다.
- 조사(analyze_sources): 시장·특허를 병렬로 실행하고 영역별 제한 시간·오류를 격리한다.
  제한 시간이 지나면 새 외부 호출을 막는다(이미 보낸 호출은 끝날 때까지 남는다).
- 질문 연결(run_pipeline): 조사 결과를 재사용할 수 있고, 연결 실패는 질문 단위로 보류한다.
- 오류 문구는 redact로 API 키를 가린 뒤 보고서·화면·CLI에 내보낸다.

CLI:
    python -m src.pipeline status [--json] [--area SF-02]
    python -m src.pipeline run --idea-id SF-02 [--questions 질문.json] [--out 결과.json]
"""

import argparse
import json
import logging
import os
import re
import sys
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from concurrent.futures import TimeoutError as FutureTimeout
from datetime import date
from pathlib import Path
from typing import Callable, Literal

import requests
import yaml
from dotenv import load_dotenv
from pydantic import BaseModel, Field

from src.generation.idea_parser import build_requests
from src.generation.business_review import BusinessReview, build_business_review
from src.generation.executive_review import (
    ExecutiveReview,
    build_executive_review,
    executive_report_markdown,
)
from src.generation.input_guard import MAX_ANSWER_CHARS, screen_text
from src.generation.report_builder import (
    QuestionLink,
    link_questions_with_retry,
)
from src.schemas import (
    IDEA_FIELDS,
    IdeaDraft,
    MarketReport,
    PatentReport,
    ImplementationCostEstimate,
    CostScenarioTotals,
)
from src.services.market_service import run_market_research
from src.services.patent_service import analyze_patents

ROOT_DIR = Path(__file__).resolve().parents[1]
MARKET_CHROMA_DIR = ROOT_DIR / "data" / "market" / "chroma"
PATENT_CHROMA_DIR = ROOT_DIR / "data" / "patents" / "chroma"
MARKET_COLLECTION = "news"
PATENT_COLLECTION = "patents"
AREAS_PATH = ROOT_DIR / "configs" / "technology_areas.yaml"
IDEAS_PATH = ROOT_DIR / "data" / "samples" / "ideas.json"

MARKET_TIMEOUT = float(os.getenv("IDEALENS_MARKET_TIMEOUT", "120"))
PATENT_TIMEOUT = float(os.getenv("IDEALENS_PATENT_TIMEOUT", "180"))
HEARTBEAT_TIMEOUT = 5.0
KEY_NAMES = [
    "OPENAI_API_KEY",
    "KIPRIS_API_KEY",
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
    "NAVER_TREND_CLIENT_ID",
    "NAVER_TREND_CLIENT_SECRET",
    "DART_API_KEY",
    "CHROMA_API_KEY",
]
_SECRET_PATTERNS = [
    (re.compile(r"(?i)\b((?:access|service)key=)[^&\s'\"]+"), r"\1***"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=\-]+"), r"\1***"),
]

RunState = Literal["completed", "partial", "no_results", "error", "skipped", "timeout"]

LOG = logging.getLogger("idealens")
if not LOG.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(
        logging.Formatter("%(asctime)s idealens %(levelname)s %(message)s")
    )
    LOG.addHandler(_handler)
    LOG.setLevel(logging.INFO)
    LOG.propagate = False


class IndexState(BaseModel):
    location: Literal["local", "remote"]
    collection: str
    count: int | None = None  # None이면 열지 못함(reason 참고)
    area_counts: dict[str, int] = Field(default_factory=dict)
    reason: str | None = None


class Readiness(BaseModel):
    keys: dict[str, bool]  # 키 이름별 설정 여부. 값은 담지 않는다
    chroma: Literal["local", "remote"]
    market_index: IndexState
    patent_index: IndexState
    market_runnable: bool
    patent_mode: Literal["local+kipris", "kipris_only", "local_only", "none"]
    market_collected_at: int | None = None
    reasons: list[str] = Field(default_factory=list)


class PartRun(BaseModel):
    state: RunState
    seconds: float | None = None
    message: str | None = None


class SourceAnalysis(BaseModel):
    """시장·특허 조사 결과. 질문만 바뀌면 이 결과를 재사용해 연결만 다시 만든다."""

    patent: PatentReport
    market: MarketReport
    patent_run: PartRun
    market_run: PartRun
    readiness: Readiness | None = None
    analyzed_on: int
    total_seconds: float


class PipelineReport(BaseModel):
    status: str
    title: str
    patent: PatentReport
    market: MarketReport
    links: list[QuestionLink] = Field(default_factory=list)
    markdown: str = ""
    business_review: BusinessReview | None = None
    executive_review: ExecutiveReview | None = None
    errors: list[str] = Field(default_factory=list)
    patent_run: PartRun | None = None
    market_run: PartRun | None = None
    readiness: Readiness | None = None
    analyzed_on: int | None = None
    cost_estimate: ImplementationCostEstimate | None = None
    cost_totals: CostScenarioTotals | None = None


class Cancelled(RuntimeError):
    """영역 제한 시간이 지난 뒤 새 외부 호출을 막을 때 낸다."""


class _GetCountCollection:
    """공용 Chroma 컬렉션의 count()를 POST get으로 대신한다.

    공용 서버의 인증 게이트웨이가 쿼리 문자열이 붙은 요청(count 등)을 404로 막으므로,
    서비스에 넘기는 원격 컬렉션은 이 래퍼로 감싼다. 그 밖의 호출은 원래 컬렉션으로 넘긴다.
    """

    def __init__(self, collection):
        self._collection = collection

    def count(self) -> int:
        return len(self._collection.get(include=[])["ids"])

    def __getattr__(self, name):
        return getattr(self._collection, name)


class _EmptyCollection:
    """특허 로컬 색인이 없을 때 넘기는 빈 컬렉션. KIPRIS 보충 경로로 넘어가게 한다."""

    def count(self) -> int:
        return 0

    def get(self, *args, **kwargs) -> dict:
        return {"ids": [], "documents": [], "metadatas": []}

    def query(self, *args, **kwargs) -> dict:
        return {"ids": [[]], "distances": [[]]}


def redact(text: str | None) -> str | None:
    """오류 문구에서 API 키 값과 키가 담긴 URL 인자·인증 헤더를 가린다."""
    if not text:
        return text
    result = str(text)
    for name in KEY_NAMES:
        value = os.getenv(name, "").strip()
        if len(value) >= 6:
            result = result.replace(value, "***")
    for pattern, replacement in _SECRET_PATTERNS:
        result = pattern.sub(replacement, result)
    return result


def _redacted(report):
    return report.model_copy(
        update={
            "error_message": redact(report.error_message),
            "unknowns": [redact(item) for item in report.unknowns],
        }
    )


def _area_ids() -> list[str]:
    try:
        config = yaml.safe_load(AREAS_PATH.read_text(encoding="utf-8")) or {}
    except OSError:
        return []
    return [area["id"] for area in config.get("technology_areas", []) if "id" in area]


def _chroma_location() -> Literal["local", "remote"]:
    return "remote" if os.getenv("CHROMA_HOST", "").strip() else "local"


def remote_heartbeat(timeout: float = HEARTBEAT_TIMEOUT) -> str | None:
    """공용 Chroma 서버가 응답하면 None, 아니면 키 없이 쓴 사유를 돌려준다."""
    host = os.getenv("CHROMA_HOST", "").strip()
    port = os.getenv("CHROMA_PORT", "8000").strip() or "8000"
    ssl = os.getenv("CHROMA_SSL", "false").strip().lower() == "true"
    key = os.getenv("CHROMA_API_KEY", "").strip()
    headers = {"Authorization": f"Bearer {key}"} if key else {}
    url = f"{'https' if ssl else 'http'}://{host}:{port}/api/v2/heartbeat"
    try:
        response = requests.get(url, headers=headers, timeout=timeout)
    except requests.RequestException as exc:
        return f"공용 Chroma 연결 실패({type(exc).__name__})"
    if response.status_code in (401, 403):
        return "공용 Chroma 인증 실패(CHROMA_API_KEY 확인 필요)"
    if not response.ok:
        return f"공용 Chroma 응답 오류(HTTP {response.status_code})"
    return None


def open_collection(name: str, local_dir: Path, client=None):
    """컬렉션을 새로 만들지 않고 연다. 반환: (컬렉션 또는 None, IndexState)."""
    location = _chroma_location() if client is None else "local"
    if client is None:
        if location == "remote":
            reason = remote_heartbeat()
            if reason:
                return None, IndexState(
                    location=location, collection=name, reason=reason
                )
            from src.retrieval.chroma_client import connect_chroma

            try:
                client = connect_chroma(local_dir)
            except Exception as exc:
                return None, IndexState(
                    location=location,
                    collection=name,
                    reason=redact(
                        f"공용 Chroma 설정 오류({type(exc).__name__}: {exc})"
                    ),
                )
        else:
            if not (local_dir / "chroma.sqlite3").exists():
                return None, IndexState(
                    location=location, collection=name, reason="로컬 색인 없음"
                )
            import chromadb
            from chromadb.config import Settings

            client = chromadb.PersistentClient(
                path=str(local_dir), settings=Settings(anonymized_telemetry=False)
            )
    try:
        collection = client.get_collection(name, embedding_function=None)
    except Exception as exc:  # chromadb NotFoundError 등
        reason = (
            "컬렉션 없음"
            if type(exc).__name__ == "NotFoundError" or "does not exist" in str(exc)
            else f"컬렉션을 열 수 없음({type(exc).__name__})"
        )
        return None, IndexState(location=location, collection=name, reason=reason)
    if location == "remote":
        collection = _GetCountCollection(collection)
    try:
        count = collection.count()
    except Exception as exc:
        return None, IndexState(
            location=location,
            collection=name,
            reason=f"건수 확인 실패({type(exc).__name__})",
        )
    return collection, IndexState(location=location, collection=name, count=count)


def _market_dart_count(collection) -> int:
    """시장 컬렉션의 DART 사업보고서 청크 수. 확인하지 못하면 0."""
    try:
        return len(collection.get(where={"source_type": "dart"}, include=[])["ids"])
    except Exception:
        return 0


def _market_collected_at(collection) -> int | None:
    try:
        metadatas = collection.get(include=["metadatas"])["metadatas"] or []
    except Exception:
        return None
    values = [m.get("collected_at") for m in metadatas if m and m.get("collected_at")]
    return max(values) if values else None


def prepare_sources(
    technology_area_id: str | None = None,
    *,
    market_client=None,
    patent_client=None,
    dotenv_path: Path | None = ROOT_DIR / ".env",
):
    """키·색인 준비 상태를 점검하고 실행에 쓸 컬렉션을 연다.

    반환: (Readiness, 시장 컬렉션 또는 None, 특허 컬렉션 또는 None)
    """
    if dotenv_path is not None:
        load_dotenv(dotenv_path)
    keys = {name: bool(os.getenv(name, "").strip()) for name in KEY_NAMES}
    market, market_state = open_collection(
        MARKET_COLLECTION, MARKET_CHROMA_DIR, market_client
    )
    patent, patent_state = open_collection(
        PATENT_COLLECTION, PATENT_CHROMA_DIR, patent_client
    )
    if patent is not None:
        for area_id in _area_ids():
            try:
                found = patent.get(where={f"area_{area_id}": True}, include=[])
                patent_state.area_counts[area_id] = len(found["ids"])
            except Exception:
                patent_state.area_counts[area_id] = 0

    reasons = []
    if not keys["OPENAI_API_KEY"]:
        reasons.append("OPENAI_API_KEY 없음: 시장·특허 분석을 실행할 수 없음")
    market_runnable = keys["OPENAI_API_KEY"] and bool(market_state.count)
    if not market_state.count:
        reasons.append(f"시장 색인 준비 필요({market_state.reason or '문서 0건'})")
    elif not _market_dart_count(market):
        reasons.append(
            "시장 색인에 DART 사업보고서 없음: dart_client·dart_processor 실행 후 "
            "market_search build 필요"
        )
    total_local_patents = patent_state.count or 0
    selected_area_count = (
        patent_state.area_counts.get(technology_area_id, 0)
        if technology_area_id
        else total_local_patents
    )
    local_patents = selected_area_count or total_local_patents
    if technology_area_id and not selected_area_count and total_local_patents:
        reasons.append(
            f"특허 색인에 {technology_area_id} 문서가 없어 전체 특허 색인으로 검색합니다"
        )
    if not keys["OPENAI_API_KEY"]:
        patent_mode = "none"
    elif local_patents and keys["KIPRIS_API_KEY"]:
        patent_mode = "local+kipris"
    elif local_patents:
        patent_mode = "local_only"
    elif keys["KIPRIS_API_KEY"]:
        patent_mode = "kipris_only"
    else:
        patent_mode = "none"
    if not local_patents:
        reasons.append(
            f"특허 색인에 {technology_area_id or '전체'} 문서 없음"
            + (": KIPRIS 실시간 검색만 사용" if patent_mode == "kipris_only" else "")
        )
    readiness = Readiness(
        keys=keys,
        chroma=market_state.location,
        market_index=market_state,
        patent_index=patent_state,
        market_runnable=market_runnable,
        patent_mode=patent_mode,
        market_collected_at=_market_collected_at(market) if market_runnable else None,
        reasons=reasons,
    )
    return readiness, market, patent


def check_readiness(technology_area_id: str | None = None) -> Readiness:
    """실행 없이 준비 상태만 점검한다(status CLI·doctor용)."""
    return prepare_sources(technology_area_id)[0]


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
    from src.services.market_network import build_keyword_network
    from src.services.market_trend import build_search_trend

    return {
        "embed_fn": _guard(embed_texts, event),
        "judge_fn": _guard(call_relevance_llm, event),
        "llm_fn": _guard(call_analysis_llm, event),
        "trend_fn": _guard(build_search_trend, event),
        "network_fn": _guard(build_keyword_network, event),
    }


def _patent_defaults(event: threading.Event) -> dict:
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

    def review(idea, evidence):
        return review_patents_by_component(idea, evidence, llm_fn=guarded_review_llm)

    def design_proposals(idea, evidence, reviews, precheck):
        return generate_patent_design_analysis(
            idea, evidence, reviews, precheck, llm_fn=guarded_review_llm
        )

    return {
        "embed_fn": _guard(embed_texts, event),
        "query_llm_fn": _guard(call_query_llm, event),
        "claim_fetcher": _guard(fetch_patent_claims, event),
        "kipris_search_fn": _guard(search_kipris, event),
        "patent_review_fn": review,
        "design_proposal_fn": design_proposals,
        "relevance_fn": _tolerant_relevance(event),
    }


def _timed(fn: Callable, *args, **kwargs):
    started = time.monotonic()
    report = fn(*args, **kwargs)
    return report, time.monotonic() - started


def _part_from_report(report, seconds: float) -> PartRun:
    message = report.error_message if report.status in {"error", "partial"} else None
    return PartRun(
        state=report.status, seconds=round(seconds, 1), message=redact(message)
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
    started = time.monotonic()
    patent_request, market_request = build_requests(draft)
    patent_request.technology_area_id = technology_area_id
    if technical_components is not None:
        patent_request.idea.technical_components = technical_components
        market_request.idea.technical_components = technical_components

    market_collection = patent_collection = None
    if readiness is None:
        readiness, market_collection, patent_collection = prepare_sources(
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
            run_market_research,
            market_request,
            market_args,
            market_timeout,
        )
    if readiness.patent_mode != "none":
        jobs["patent"] = (analyze_patents, patent_request, patent_args, patent_timeout)

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
    patent_report, market_report = _redacted(patent_report), _redacted(market_report)
    for label, run, report in (
        ("특허", patent_run, patent_report),
        ("시장", market_run, market_report),
    ):
        level = logging.WARNING if run.state in ("error", "timeout") else logging.INFO
        LOG.log(
            level,
            "%s 조사 %s (%ss, 근거 %d건)%s",
            label,
            run.state,
            run.seconds,
            len(report.evidence),
            f": {run.message}" if run.message else "",
        )
        for item in report.unknowns:
            LOG.info("%s 미확인: %s", label, item)
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
        return _failed(kind, "error", redact(f"{type(exc).__name__}: {exc}"), None)
    return report, _part_from_report(report, seconds)


def screen_inputs(parts: list[str] | None, questions: list[dict]) -> list[dict]:
    """핵심 구성·검토 질문을 입력 규칙으로 검사하고 빈 질문을 뺀 목록을 돌려준다.

    거절되면 ValueError(사용자 안내 문구)를 낸다. 짧은 구성(예: '센서')도 허용한다.
    """
    for index, part in enumerate(parts or [], 1):
        status, message = screen_text(part, MAX_ANSWER_CHARS, min_chars=1)
        if status != "ok":
            raise ValueError(f"핵심 구성 {index}: {message}")
    kept = []
    for item in questions:
        text = str(item.get("question", "")).strip()
        if not text:
            continue
        for label, value in (("질문", text), ("조건", item.get("condition", ""))):
            if not str(value or "").strip():
                continue
            status, message = screen_text(str(value), MAX_ANSWER_CHARS, min_chars=1)
            if status != "ok":
                raise ValueError(f"검토 {label} {item.get('id', '')}: {message}")
        kept.append(item)
    return kept


def default_questions(draft: IdeaDraft) -> list[dict]:
    """구조화 결과로 기본 검토 질문 1개를 만든다(조사 없이 읽히는 문장)."""
    return [
        {
            "id": "Q1",
            "question": f"제안 기술({draft.technology or '미확인'})로 문제({draft.problem or '미확인'})를 해결할 수 있는가?",
            "condition": "",
        }
    ]


def run_pipeline(
    draft: IdeaDraft,
    questions: list[dict],
    *,
    technical_components: list[str] | None = None,
    technology_area_id: str | None = None,
    patent_kwargs: dict | None = None,
    market_kwargs: dict | None = None,
    link_llm_fn=None,
    readiness: Readiness | None = None,
    sources: SourceAnalysis | None = None,
    parallel: bool | None = None,
    cost_llm_fn=None,
) -> PipelineReport:
    """확정된 IdeaDraft로 두 조사와 질문별 통합 근거 보고서를 실행한다.

    sources를 넘기면 조사를 다시 하지 않고 질문 연결과 보고서만 새로 만든다.
    """
    draft.to_structured_idea()
    questions = screen_inputs(technical_components, questions)
    if sources is None:
        sources = analyze_sources(
            draft,
            technical_components=technical_components,
            technology_area_id=technology_area_id,
            patent_kwargs=patent_kwargs,
            market_kwargs=market_kwargs,
            readiness=readiness,
            parallel=parallel,
        )
    links, warnings = link_questions_with_retry(
        questions, sources.market, sources.patent, llm_fn=link_llm_fn
    )
    for item in warnings:
        LOG.warning("질문 연결: %s", redact(item))
    errors = [redact(item) for item in warnings]
    for label, run in (("특허", sources.patent_run), ("시장", sources.market_run)):
        if run.state in ("error", "timeout"):
            errors.append(f"{label} 조사 {run.state}: {run.message}")
    collected = sources.readiness.market_collected_at if sources.readiness else None
    business_review = build_business_review(draft, sources.patent, sources.market)
    executive_review = build_executive_review(
        draft,
        sources.patent,
        sources.market,
        business_review,
        patent_run_state=sources.patent_run.state,
        market_run_state=sources.market_run.state,
    )
    cost_estimate = None
    cost_totals = None
    if cost_llm_fn is not None:
        from src.generation.cost_estimation import calculate_scenarios, estimate_costs

        cost_estimate = estimate_costs(
            draft, sources.market, sources.patent, llm_fn=cost_llm_fn
        )
        cost_totals = calculate_scenarios(cost_estimate)
    markdown = executive_report_markdown(
        draft.title,
        executive_review,
        analyzed_on=sources.analyzed_on,
        cost_estimate=cost_estimate,
        cost_totals=cost_totals,
    )
    statuses = {sources.patent.status, sources.market.status}
    status = "completed" if statuses == {"completed"} and not errors else "partial"
    return PipelineReport(
        status=status,
        title=draft.title,
        patent=sources.patent,
        market=sources.market,
        links=links,
        markdown=markdown,
        business_review=business_review,
        executive_review=executive_review,
        errors=errors,
        patent_run=sources.patent_run,
        market_run=sources.market_run,
        readiness=sources.readiness,
        analyzed_on=sources.analyzed_on,
        cost_estimate=cost_estimate,
        cost_totals=cost_totals,
    )


def sample_draft(idea_id: str) -> IdeaDraft:
    """data/samples/ideas.json의 아이디어를 확정된 IdeaDraft로 만든다."""
    entries = json.loads(IDEAS_PATH.read_text(encoding="utf-8"))
    entry = next((e for e in entries if e.get("idea_id") == idea_id), None)
    if entry is None:
        raise SystemExit(f"Unknown idea id: {idea_id}")
    idea = entry["idea"]
    return IdeaDraft(
        original_text=entry.get("text") or idea["problem"],
        title=idea.get("title", idea_id),
        **{field: idea.get(field, "") for field in IDEA_FIELDS},
        field_sources={field: "extracted" for field in IDEA_FIELDS},
        status="complete",
    )


def main() -> None:
    """준비 상태 점검(status)과 샘플 아이디어 실분석(run)을 실행한다. 표준 출력은 JSON만 쓴다."""
    parser = argparse.ArgumentParser(description="IdeaLens 통합 분석 흐름")
    sub = parser.add_subparsers(dest="command", required=True)
    status_cmd = sub.add_parser(
        "status", help="키·색인 준비 상태 점검(외부 생성 호출 없음)"
    )
    status_cmd.add_argument("--json", action="store_true", help="JSON으로 출력")
    status_cmd.add_argument("--area", help="특허 분야 ID(예: SF-02)")
    run_cmd = sub.add_parser("run", help="샘플 아이디어로 실분석 실행(API 비용 발생)")
    run_cmd.add_argument(
        "--idea-id", required=True, help="data/samples/ideas.json의 ID"
    )
    run_cmd.add_argument(
        "--area", help="특허 분야 ID(기본: idea-id와 같은 분야가 있으면 그 값)"
    )
    run_cmd.add_argument("--questions", type=Path, help="질문 목록 JSON 파일")
    run_cmd.add_argument("--out", type=Path, help="PipelineReport JSON 저장 경로")
    args = parser.parse_args()

    if args.command == "status":
        readiness = check_readiness(args.area)
        if args.json:
            print(readiness.model_dump_json(indent=2))
        else:
            print(f"Chroma: {readiness.chroma}")
            print(
                f"시장 색인: {readiness.market_index.count} ({readiness.market_index.reason or 'ok'})"
            )
            print(
                f"특허 색인: {readiness.patent_index.count} 분야별 {readiness.patent_index.area_counts}"
            )
            print(f"특허 실행 방식: {readiness.patent_mode}")
            for reason in readiness.reasons:
                print(f"- {reason}")
        return

    draft = sample_draft(args.idea_id)
    area = args.area or (args.idea_id if args.idea_id in _area_ids() else None)
    questions = (
        json.loads(args.questions.read_text(encoding="utf-8"))
        if args.questions
        else default_questions(draft)
    )
    report = run_pipeline(draft, questions, technology_area_id=area)
    print(
        f"[{report.status}] 특허 {report.patent_run.state}({report.patent_run.seconds}s)"
        f" · 시장 {report.market_run.state}({report.market_run.seconds}s)",
        file=sys.stderr,
    )
    payload = report.model_dump_json(indent=2)
    if args.out:
        args.out.write_text(payload, encoding="utf-8")
    else:
        print(payload)


if __name__ == "__main__":
    main()
