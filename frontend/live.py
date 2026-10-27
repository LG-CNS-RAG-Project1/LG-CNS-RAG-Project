"""실제 분석 화면의 보조 규칙: 접속 비밀번호, 실행 가능 여부, 분석 캐시 키, 동시 실행 제한, 오류·표시 문구.

무거운 분석 모듈(src.pipeline 등)은 함수 안에서 불러 첫 화면 로딩을 가볍게 유지한다.
"""

import hashlib
import hmac
import json
import os
import threading

RUN_LOCK = threading.Lock()  # 프로세스 전체에서 실분석은 한 번에 1건
MAX_PASSWORD_FAILURES = 5
PASSWORD_LOCK_SECONDS = 60

FIELD_LABELS = {
    "problem": "문제",
    "technology": "기술",
    "customers": "고객",
    "difference": "차별점",
    "revenue": "수익모델",
}
SOURCE_LABELS = {
    "extracted": "입력에서 추출",
    "user_answer": "재질문 답변",
    "unknown": "모름",
}

STATE_LABELS = {
    "completed": "완료",
    "no_results": "결과 없음",
    "error": "오류",
    "skipped": "실행 안 함",
    "timeout": "시간 초과",
}
LINK_LABELS = {"connected": "연결", "partial": "부분 연결", "hold": "판단 보류"}
PATENT_MODE_LABELS = {
    "local+kipris": "색인 + KIPRIS 보충",
    "kipris_only": "KIPRIS 실시간 검색만",
    "local_only": "색인만(KIPRIS 키 없음)",
    "none": "실행 불가",
}
COST_NOTE = (
    "외부 API 호출과 비용이 발생합니다(시장 관련성 판정·분석 gpt-4o 최대 약 28회, "
    "특허 검색어·판정·비교 gpt-4o-mini 수 회, KIPRIS 조회). 보통 20~60초 걸립니다."
)


def app_password() -> str:
    """호스팅 배포에서 설정하는 접속 비밀번호. 비어 있으면 비밀번호 화면을 띄우지 않는다(로컬 실행)."""
    return os.getenv("IDEALENS_APP_PASSWORD", "").strip()


def password_matches(entered: str, expected: str) -> bool:
    """시간 차이로 값이 드러나지 않게 비교한다."""
    return hmac.compare_digest(entered.strip().encode(), expected.encode())


def live_available() -> bool:
    """OpenAI 키가 있으면 실제 분석(AI 구조화·조사)을 쓸 수 있다."""
    return bool(os.getenv("OPENAI_API_KEY", "").strip())


def analysis_key(draft, parts: list[str], area: str | None) -> str:
    """조사 결과를 재사용할 수 있는지 가르는 키. 질문은 넣지 않는다(질문만 바뀌면 연결만 다시 만든다)."""
    payload = {
        "idea": draft.to_structured_idea().model_dump(),
        "parts": list(parts),
        "area": area,
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True).encode()
    ).hexdigest()


def friendly_error(exc: Exception) -> str:
    """사용자에게 보일 오류 문구. 원문은 키를 가리고 길이를 줄인다."""
    from src.pipeline import redact

    name = type(exc).__name__
    if name == "AuthenticationError":
        return "OpenAI 인증에 실패했습니다. OPENAI_API_KEY를 확인해 주세요."
    if name == "RateLimitError":
        return "OpenAI 사용 한도에 걸렸습니다. 잠시 후 다시 시도해 주세요."
    if name in ("APIConnectionError", "APITimeoutError", "ConnectionError"):
        return "외부 API에 연결하지 못했습니다. 네트워크를 확인해 주세요."
    if isinstance(exc, RuntimeError) and "OPENAI_API_KEY" in str(exc):
        return "OPENAI_API_KEY가 없어 AI 구조화를 실행할 수 없습니다."
    if isinstance(exc, ValueError):
        return redact(str(exc))[:300]
    return (
        f"처리 중 오류가 발생했습니다({name}). 자세한 내용은 실행 로그를 확인해 주세요."
    )


def run_line(label: str, run) -> str:
    """영역별 실행 상태 한 줄."""
    if run is None:
        return f"{label}: 상태 미확인"
    seconds = f" · {run.seconds:.1f}초" if run.seconds is not None else ""
    return f"{label}: {STATE_LABELS.get(run.state, run.state)}{seconds}"


def cost_rows_list(edited) -> list[dict]:
    """st.data_editor 결과를 행 목록으로 맞춘다(입력 형태에 따라 list 또는 DataFrame)."""
    if hasattr(edited, "to_dict"):
        return edited.to_dict("records")
    return [dict(row) for row in edited or []]


def cost_markdown(rows: list[dict]) -> str:
    """보고서 끝에 붙일 구현 비용표. 칸 내용은 이스케이프한다."""
    from src.generation.report_builder import escape_md

    columns = ["항목", "수량", "단가(만원)", "근거 / 가정", "납기"]
    lines = [
        "",
        "## 구현 비용표",
        "",
        "| " + " | ".join(columns) + " |",
        "|---|---:|---:|---|---|",
    ]
    for row in rows:
        lines.append(
            "| " + " | ".join(escape_md(row.get(c, "")) for c in columns) + " |"
        )
    return "\n".join(lines) + "\n"
