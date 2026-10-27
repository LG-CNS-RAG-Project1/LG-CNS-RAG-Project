"""사용자 입력(아이디어 문장·재질문 답변)을 LLM 호출 전에 규칙으로 검사한다.

길이와 프롬프트 조작에 자주 쓰이는 표현(지시 무시·역할 변경·프롬프트 공개 요구 등)만 확인한다.
주제 이탈과 규칙에 걸리지 않는 조작 시도는 아이디어 구조화 LLM 호출(prompts/idea_parser.md)에서
input_status로 함께 판정한다.
"""

import re
from typing import Literal

InputStatus = Literal["ok", "off_topic", "unsafe"]

MIN_IDEA_CHARS = 5
MAX_IDEA_CHARS = 1000
MAX_ANSWER_CHARS = 300

REJECTION_MESSAGES: dict[str, str] = {
    "off_topic": (
        "IdeaLens는 스마트팩토리·제조 자동화 분야의 사업 아이디어를 검토합니다. "
        "제품·서비스가 어떤 현장 문제를 어떻게 해결하는지 한 문장으로 입력해 주세요."
    ),
    "unsafe": (
        "시스템 지시를 바꾸거나 안전하지 않은 목적의 요청으로 보여 처리하지 않았습니다. "
        "검토할 사업 아이디어만 입력해 주세요."
    ),
}

# 정상 아이디어에 나올 수 있는 표현(작업 지침 안내, 시스템 메시지 전송, 안전장치 해제 감지 등)과
# 겹치지 않도록 프롬프트·AI 자신을 대상으로 한 표현만 잡는다.
INJECTION_PATTERNS = [
    r"ignore\s+(all\s+|any\s+)?(the\s+)?(previous|above|prior|earlier)\s+(instructions?|prompts?|rules?)",
    r"disregard\s+(all\s+|any\s+)?(the\s+)?(previous|above|prior|earlier|your)\s+(instructions?|prompts?|rules?)",
    r"forget\s+(all\s+|everything\s+)?(you\s+were\s+told|your\s+(instructions?|rules?))",
    r"(system|developer)\s+prompt",
    r"(reveal|show|print|repeat)\s+(me\s+)?your\s+(prompt|instructions?|rules?)",
    r"you\s+are\s+now\s+",
    r"developer\s+mode|jail\s*break",
    r"</?\s*(system|assistant)\s*>",
    r"(이전|위의|앞의|기존|모든)\s*(의\s*)?(지시|명령|규칙|지침|프롬프트)\S*\s*(은|는|을|를|다|모두)?\s*(무시|잊)",
    r"시스템\s*프롬프트",
    r"프롬프트\S*\s*(을|를)?\s*(보여|알려|출력|공개)",
    r"(너|네|당신)(의|가|는)?\s*(지시|지침|규칙|설정)\S*\s*(을|를)?\s*(보여|알려|출력|공개|무시|잊)",
    r"(너는|당신은)\s*이제",
    r"(너|네|당신)의\s*역할",
    r"탈옥|개발자\s*모드",
    r"(필터|검열|안전\s*필터)\S*\s*(을|를)?\s*(해제|풀어|우회)",
]
_INJECTION_RE = [re.compile(p, re.IGNORECASE) for p in INJECTION_PATTERNS]


def screen_text(
    text: str, max_chars: int = MAX_IDEA_CHARS, min_chars: int = MIN_IDEA_CHARS
) -> tuple[InputStatus, str | None]:
    """입력을 규칙으로 검사해 (상태, 사용자 안내 문구)를 반환한다. 통과하면 ("ok", None).

    - 너무 짧거나 길면 off_topic (아이디어 한 문장 기준)
    - 프롬프트 조작 표현이 있으면 unsafe
    """
    normalized = " ".join(text.split())
    if len(normalized) < min_chars:
        return "off_topic", "입력이 너무 짧습니다. " + REJECTION_MESSAGES["off_topic"]
    if len(normalized) > max_chars:
        return "off_topic", (
            f"입력이 너무 깁니다({len(normalized)}자, 최대 {max_chars}자). "
            "아이디어를 한두 문장으로 줄여 입력해 주세요."
        )
    if any(pattern.search(normalized) for pattern in _INJECTION_RE):
        return "unsafe", REJECTION_MESSAGES["unsafe"]
    return "ok", None
