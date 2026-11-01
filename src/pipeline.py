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

import json
import logging
import os
import re
import sys
from pathlib import Path
from typing import Literal

import requests
import yaml
from dotenv import load_dotenv
from src.llm_client import (
    embedding_collection_name,
    llm_is_configured,
    load_llm_settings,
)

from src.generation.business_review import build_business_review
from src.generation.business_canvas import build_business_canvas
from src.generation.swot import build_swot
from src.generation.executive_review import (
    build_executive_review,
    executive_report_markdown,
)
from src.generation.input_guard import MAX_ANSWER_CHARS, screen_text
from src.generation.question_links import link_questions_with_retry
from src.pipeline_execution import (
    MARKET_TIMEOUT,
    PATENT_TIMEOUT,
    _part_from_report,
    _patent_defaults,
    analyze_sources,
)
from src.pipeline_models import (
    Cancelled,
    IndexState,
    PartRun,
    PipelineReport,
    Readiness,
    SourceAnalysis,
)
from src.schemas import (
    IDEA_FIELDS,
    IdeaDraft,
)
from src.services.market_service import run_market_research
from src.services.patent_service import (
    analyze_patents,
    score_patent_semantic_similarity,
)

ROOT_DIR = Path(__file__).resolve().parents[1]
MARKET_CHROMA_DIR = ROOT_DIR / "data" / "market" / "chroma"
PATENT_CHROMA_DIR = ROOT_DIR / "data" / "patents" / "chroma"
MARKET_COLLECTION = "news"
PATENT_COLLECTION = "patents"
AREAS_PATH = ROOT_DIR / "configs" / "technology_areas.yaml"
IDEAS_PATH = ROOT_DIR / "data" / "samples" / "ideas.json"

HEARTBEAT_TIMEOUT = 5.0
KEY_NAMES = [
    "OPENAI_API_KEY",
    "OLLAMA_API_KEY",
    "KIPRIS_API_KEY",
    "NAVER_CLIENT_ID",
    "NAVER_CLIENT_SECRET",
    "NAVER_TREND_CLIENT_ID",
    "NAVER_TREND_CLIENT_SECRET",
    "DART_API_KEY",
    "DATA_GO_KR_SERVICE_KEY",
    "CHROMA_API_KEY",
]
_SECRET_PATTERNS = [
    (re.compile(r"(?i)\b((?:access|service)key=)[^&\s'\"]+"), r"\1***"),
    (re.compile(r"\bsk-[A-Za-z0-9_\-]{8,}"), "sk-***"),
    (re.compile(r"(?i)\b(bearer\s+)[A-Za-z0-9._~+/=\-]+"), r"\1***"),
]

LOG = logging.getLogger("idealens")
if not LOG.handlers:
    _handler = logging.StreamHandler(sys.stderr)
    _handler.setFormatter(
        logging.Formatter("%(asctime)s idealens %(levelname)s %(message)s")
    )
    LOG.addHandler(_handler)
    LOG.setLevel(logging.INFO)
    LOG.propagate = False


class _GetCountCollection:
    """공용 Chroma 컬렉션의 count()를 POST get으로 대신한다.

    공용 서버의 인증 게이트웨이가 쿼리 문자열이 붙은 요청(count 등)을 404로 막으므로,
    서비스에 넘기는 원격 컬렉션은 이 래퍼로 감싼다. 그 밖의 호출은 원래 컬렉션으로 넘긴다.
    """

    def __init__(self, collection):
        """원격 컬렉션에 대한 count 호출을 호환 요청으로 감싼다."""
        self._collection = collection

    def count(self) -> int:
        """문서 내용을 받지 않고 현재 컬렉션 건수를 센다."""
        return len(self._collection.get(include=[])["ids"])

    def __getattr__(self, name):
        """count 이외의 컬렉션 동작은 원본 객체에 위임한다."""
        return getattr(self._collection, name)


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
    """오류 문구와 미확인 항목을 비밀값 제거 후 복사한다."""
    return report.model_copy(
        update={
            "error_message": redact(report.error_message),
            "unknowns": [redact(item) for item in report.unknowns],
        }
    )


def _area_ids() -> list[str]:
    """기술 분야 설정에서 색인 필터용 분야 ID를 읽는다."""
    try:
        config = yaml.safe_load(AREAS_PATH.read_text(encoding="utf-8")) or {}
    except OSError:
        return []
    return [area["id"] for area in config.get("technology_areas", []) if "id" in area]


def _chroma_location() -> Literal["local", "remote"]:
    """CHROMA_HOST 설정에 따라 로컬·공용 저장소 모드를 고른다."""
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
                    location=location,
                    collection=embedding_collection_name(name),
                    reason=reason,
                )
            from src.retrieval.chroma_client import connect_chroma

            try:
                client = connect_chroma(local_dir)
            except Exception as exc:
                return None, IndexState(
                    location=location,
                    collection=embedding_collection_name(name),
                    reason=redact(
                        f"공용 Chroma 설정 오류({type(exc).__name__}: {exc})"
                    ),
                )
        else:
            from src.llm_client import local_chroma_path

            local_dir = local_chroma_path(local_dir)
            if not (local_dir / "chroma.sqlite3").exists():
                return None, IndexState(
                    location=location,
                    collection=embedding_collection_name(name),
                    reason="로컬 색인 없음",
                )
            import chromadb
            from chromadb.config import Settings

            client = chromadb.PersistentClient(
                path=str(local_dir), settings=Settings(anonymized_telemetry=False)
            )
    try:
        collection = client.get_collection(
            embedding_collection_name(name), embedding_function=None
        )
    except Exception as exc:  # chromadb NotFoundError 등
        reason = (
            "컬렉션 없음"
            if type(exc).__name__ == "NotFoundError" or "does not exist" in str(exc)
            else f"컬렉션을 열 수 없음({type(exc).__name__})"
        )
        return None, IndexState(
            location=location,
            collection=embedding_collection_name(name),
            reason=reason,
        )
    if location == "remote":
        collection = _GetCountCollection(collection)
    try:
        count = collection.count()
    except Exception as exc:
        return None, IndexState(
            location=location,
            collection=embedding_collection_name(name),
            reason=f"건수 확인 실패({type(exc).__name__})",
        )
    return collection, IndexState(
        location=location,
        collection=embedding_collection_name(name),
        count=count,
    )


def _market_dart_count(collection) -> int:
    """시장 컬렉션의 DART 사업보고서 청크 수. 확인하지 못하면 0."""
    try:
        return len(collection.get(where={"source_type": "dart"}, include=[])["ids"])
    except Exception:
        return 0


def _market_collected_at(collection) -> int | None:
    """시장 컬렉션 메타데이터에서 가장 최근 수집일을 찾는다."""
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
    llm_configured = llm_is_configured()
    keys["LLM_PROVIDER"] = llm_configured
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
    if not llm_configured:
        if load_llm_settings() == "ollama":
            reasons.append("OLLAMA_BASE_URL 설정 필요: Ollama LLM 연결 불가")
        else:
            reasons.append("OPENAI_API_KEY 없음: 시장·특허 분석을 실행할 수 없음")
    market_runnable = llm_configured and bool(market_state.count)
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
    if not llm_configured:
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
    swot_llm_fn=None,
    canvas_llm_fn=None,
) -> PipelineReport:
    """확정된 IdeaDraft로 두 조사와 질문별 통합 근거 보고서를 실행한다.

    sources를 넘기면 조사를 다시 하지 않고 질문 연결과 보고서만 새로 만든다.
    swot_llm_fn을 주면 두 조사 결과로 예비 SWOT(build_swot)을 만들어 보고서에 붙인다.
    canvas_llm_fn을 주면 아이디어·조사 결과·구축 비용 추정으로 예비 비즈니스 모델
    캔버스(build_business_canvas)를 만들어 보고서에 붙인다.
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
    swot = (
        build_swot(draft, sources.patent, sources.market, swot_llm_fn)
        if swot_llm_fn is not None
        else None
    )
    canvas = (
        build_business_canvas(
            draft,
            sources.patent,
            sources.market,
            canvas_llm_fn,
            cost_estimate=cost_estimate,
            technical_components=technical_components,
        )
        if canvas_llm_fn is not None
        else None
    )
    markdown = executive_report_markdown(
        draft.title,
        executive_review,
        analyzed_on=sources.analyzed_on,
        cost_estimate=cost_estimate,
        cost_totals=cost_totals,
        market=sources.market,
        swot=swot,
        canvas=canvas,
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
        swot=swot,
        canvas=canvas,
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
    """CLI 호환 진입점. 명령행 처리는 pipeline_cli에서 수행한다."""
    from src.pipeline_cli import main as cli_main

    cli_main()


if __name__ == "__main__":
    main()
