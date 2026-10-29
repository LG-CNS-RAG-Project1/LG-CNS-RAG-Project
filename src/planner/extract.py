"""기사 한 건의 근거 구절 후보를 gpt-4o-mini로 추출한다.

- 입력은 번호 붙인 문장(제목 t·검색 요약 s·본문 b)이며 본문은 llm_input_chars까지만 넣는다.
- 출력은 strict json_schema로 형식을 고정하지만, 형식 준수가 의미 정확성을 보장하지는 않는다.
  구절 위치·역할·단계 판정은 anchors·rules가 코드로 한다.
- 형식 오류·기사 ID 불일치·거절·잘린 응답은 기사당 1회(전체 재시도 상한 안에서) 다시 시도하고,
  그래도 실패하면 extraction_failed로 남긴다. 입력에 없는 문장 번호를 단 항목만 버리고(unknown_sentence_id)
  나머지 항목은 쓴다.
- 캐시 키 = 입력 해시 + extractor_version + prompt_hash + schema_hash + model. 같은 키는 재호출하지 않는다.
"""

import json
import os
import re
from collections.abc import Callable
from pathlib import Path

from dotenv import load_dotenv
from pydantic import BaseModel, ValidationError

from src.planner.config import ALLOWED_MODEL, Profile
from src.planner.schemas import ExtractionRecord, Sentence
from src.planner.store import canonical_json, sha256_hex

ROOT_DIR = Path(__file__).resolve().parents[2]
PROMPT_PATH = ROOT_DIR / "prompts" / "planner_extraction.md"
EXTRACTOR_VERSION = "planner-extractor-v1"
ROLES = [
    "supplier",
    "adopter",
    "equipment_maker",
    "si_partner",
    "public_or_research",
    "investor",
    "other",
    "unknown",
]
RELATION_HINTS = [
    "supply",
    "contract",
    "poc",
    "install",
    "operation",
    "repeat",
    "joint_dev",
    "plan",
    "withdrawal",
    "affiliate_site",
    "unknown",
]
UNRESOLVED = [
    "supplier",
    "product",
    "adopter",
    "process",
    "inspection_target",
    "event_stage",
    "event_date",
    "price_unit",
    "metric_conditions",
]
LEXICON_VERBS = re.compile(
    r"공급|납품|계약|수주|도입|구축|실증|협약|공동\s?개발|철수|중단|출시|선보|개발|적용"
)
METRIC_RE = re.compile(
    r"\d+(?:[.,]\d+)?\s*(?:%|퍼센트|시간|분|초|배|억\s?원|만\s?원|원)"
)

LLMFn = Callable[[str, str, dict], dict]


def _string(**extra):
    return {"type": "string", **extra}


def _items(properties: dict) -> dict:
    return {
        "type": "array",
        "items": {
            "type": "object",
            "properties": properties,
            "required": list(properties),
            "additionalProperties": False,
        },
    }


EXTRACTION_SCHEMA = {
    "type": "object",
    "properties": {
        "source_id": _string(),
        "mentions": _items(
            {
                "sentence_id": _string(),
                "exact_text": _string(),
                "candidate_role": _string(enum=ROLES),
            }
        ),
        "claims": _items(
            {
                "sentence_id": _string(),
                "exact_text": _string(),
                "owner_text": _string(),
                "product_text": _string(),
            }
        ),
        "relations": _items(
            {
                "sentence_id": _string(),
                "exact_clause": _string(),
                "subject_text": _string(),
                "object_text": _string(),
                "relation_hint": _string(enum=RELATION_HINTS),
            }
        ),
        "metrics": _items({"sentence_id": _string(), "exact_text": _string()}),
        "unresolved_fields": {"type": "array", "items": _string(enum=UNRESOLVED)},
    },
    "required": [
        "source_id",
        "mentions",
        "claims",
        "relations",
        "metrics",
        "unresolved_fields",
    ],
    "additionalProperties": False,
}
SCHEMA_HASH = sha256_hex(canonical_json(EXTRACTION_SCHEMA))


class _Mention(BaseModel):
    sentence_id: str
    exact_text: str
    candidate_role: str


class _Claim(BaseModel):
    sentence_id: str
    exact_text: str
    owner_text: str
    product_text: str


class _Relation(BaseModel):
    sentence_id: str
    exact_clause: str
    subject_text: str
    object_text: str
    relation_hint: str


class _Metric(BaseModel):
    sentence_id: str
    exact_text: str


class ExtractionPayload(BaseModel):
    source_id: str
    mentions: list[_Mention]
    claims: list[_Claim]
    relations: list[_Relation]
    metrics: list[_Metric]
    unresolved_fields: list[str]


def split_sentences(text: str, layer: str, prefix: str) -> list[Sentence]:
    """문장 끝(. ! ? 뒤 공백·줄 끝)·줄바꿈·생략 부호(... …)에서 나눈다. 소수점은 나누지 않는다.

    생략 부호로 끝난 조각은 잘린 문장(truncated)으로 표시한다.
    """
    sentences, start, i, n = [], 0, 0, len(text)

    def close(end: int, truncated: bool):
        nonlocal start
        segment = text[start:end]
        left = len(segment) - len(segment.lstrip())
        right = len(segment.rstrip())
        if segment.strip():
            sentences.append(
                Sentence(
                    sentence_id=f"{prefix}{len(sentences) + 1}",
                    layer=layer,
                    start=start + left,
                    end=start + right,
                    text=segment.strip(),
                    truncated=truncated,
                )
            )
        start = end

    while i < n:
        if text.startswith("...", i):
            close(i + 3, True)
            i += 3
            continue
        char = text[i]
        if char == "…":
            close(i + 1, True)
        elif char == "\n":
            close(i, False)
            start = i + 1
        elif char in ".!?" and (i + 1 == n or text[i + 1] in " \t\n\"'”’)"):
            end = i + 1
            while end < n and text[end] in "\"'”’)":
                end += 1
            close(end, False)
            i = end
            continue
        i += 1
    close(n, False)
    return sentences


def article_sentences(
    title: str, snippet: str, body: str, max_chars: int
) -> tuple[list[Sentence], list[Sentence]]:
    """(전체 문장, LLM에 넣을 문장)을 만든다. 제목·요약은 항상 넣고 본문은 max_chars까지."""
    every = split_sentences(title, "title", "t")
    every += split_sentences(snippet, "stored_snippet", "s")
    body_sentences = split_sentences(body, "reviewed_body", "b") if body else []
    chosen = list(every)
    used = sum(len(s.text) for s in chosen)
    for sentence in body_sentences:
        if used + len(sentence.text) > max_chars:
            break
        chosen.append(sentence)
        used += len(sentence.text)
    return every + body_sentences, chosen


def has_lexicon_hit(text: str, profile: Profile) -> bool:
    """기준 사전·관계 동사·수치 표현이 하나라도 있으면 추출 대상이다."""
    terms = [t for c in profile.criteria for t in c.strong + c.weak]
    return (
        any(term in text for term in terms)
        or bool(LEXICON_VERBS.search(text))
        or bool(METRIC_RE.search(text))
    )


def system_prompt(profile: Profile, path: Path = PROMPT_PATH) -> str:
    focus = "\n".join(f"- {item}" for item in profile.extraction_focus) or "- 없음"
    return path.read_text("utf-8").replace("{focus}", focus)


def render_input(source_id: str, sentences: list[Sentence]) -> str:
    payload = {
        "source_id": source_id,
        "sentences": [{"id": s.sentence_id, "text": s.text} for s in sentences],
    }
    return canonical_json(payload).decode("utf-8")


def cache_key(input_text: str, prompt_hash: str, model: str = ALLOWED_MODEL) -> str:
    return sha256_hex(
        "|".join(
            [sha256_hex(input_text), EXTRACTOR_VERSION, prompt_hash, SCHEMA_HASH, model]
        )
    )


def call_extraction_llm(system: str, user_text: str, schema: dict) -> dict:
    """OpenAI 채팅 API를 strict json_schema로 1회 호출한다. OPENAI_API_KEY가 없으면 RuntimeError."""
    from openai import OpenAI

    load_dotenv(ROOT_DIR / ".env")
    if not os.getenv("OPENAI_API_KEY"):
        raise RuntimeError("OPENAI_API_KEY is not set in .env")
    response = OpenAI().chat.completions.create(
        model=ALLOWED_MODEL,
        temperature=0,
        response_format={
            "type": "json_schema",
            "json_schema": {
                "name": "planner_extraction",
                "strict": True,
                "schema": schema,
            },
        },
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_text},
        ],
    )
    choice = response.choices[0]
    usage = response.usage
    return {
        "content": choice.message.content or "",
        "refusal": getattr(choice.message, "refusal", None) or "",
        "finish_reason": choice.finish_reason or "",
        "model": response.model,
        "system_fingerprint": response.system_fingerprint or "",
        "usage": {
            "prompt_tokens": getattr(usage, "prompt_tokens", 0),
            "completion_tokens": getattr(usage, "completion_tokens", 0),
        },
    }


def validate_response(
    raw: dict, source_id: str, sentence_ids: set[str]
) -> tuple[dict | None, str]:
    """응답 형식·기사 ID를 검사하고 입력에 없는 문장 번호의 항목은 dropped로 뺀다.

    반환: (후보 dict 또는 None, 오류 코드).
    """
    if raw.get("refusal"):
        return None, "refusal"
    if raw.get("finish_reason") == "length":
        return None, "truncated_response"
    try:
        payload = ExtractionPayload.model_validate(json.loads(raw.get("content") or ""))
    except (ValueError, ValidationError):
        return None, "invalid_json"
    if payload.source_id != source_id:
        return None, "source_id_mismatch"
    candidates, dropped = payload.model_dump(), []
    for kind in ("mentions", "claims", "relations", "metrics"):
        kept = []
        for item in candidates[kind]:
            if item["sentence_id"] in sentence_ids:
                kept.append(item)
            else:
                dropped.append({"kind": kind.rstrip("s"), **item})
        candidates[kind] = kept
    candidates["dropped"] = dropped
    return candidates, ""


class Extractor:
    """기사별 추출 호출·캐시·재시도 상한을 관리한다."""

    def __init__(
        self,
        profile: Profile,
        llm_fn: LLMFn | None,
        cache: dict[str, dict] | None = None,
        cancelled: Callable[[], bool] = lambda: False,
    ):
        self.profile = profile
        self.llm_fn = llm_fn
        self.cache = cache or {}
        self.cancelled = cancelled
        self.system = system_prompt(profile)
        self.prompt_hash = sha256_hex(self.system)
        self.retries_left = profile.budget.llm_retry_total
        self.calls = 0
        self.log: list[dict] = []

    def extract(self, source_id: str, sentences: list[Sentence]) -> ExtractionRecord:
        text = render_input(source_id, sentences)
        key = cache_key(text, self.prompt_hash)
        base = {
            "source_id": source_id,
            "cache_key": key,
            "llm_input_hash": sha256_hex(text),
            "input_sentence_ids": [s.sentence_id for s in sentences],
        }
        cached = self.cache.get(key)
        if cached is not None:
            return ExtractionRecord(
                status="ok", from_cache=True, candidates=cached, **base
            )
        if self.llm_fn is None:
            return ExtractionRecord(status="failed", error="llm_unavailable", **base)
        ids = {s.sentence_id for s in sentences}
        error, attempts = "", 0
        allowed = 1 + self.profile.budget.llm_retry_per_article
        while attempts < allowed:
            if attempts and self.retries_left <= 0:
                error = error or "retry_cap_reached"
                break
            if self.cancelled():
                error = "cancelled"
                break
            if attempts:
                self.retries_left -= 1
            attempts += 1
            self.calls += 1
            try:
                raw = self.llm_fn(self.system, text, EXTRACTION_SCHEMA)
            except Exception as exc:  # 호출 실패는 기사 단위 실패로 남긴다
                raw = {"content": "", "error": f"{type(exc).__name__}: {exc}"[:300]}
                error = "call_error"
            else:
                candidates, error = validate_response(raw, source_id, ids)
            self.log.append(
                {
                    "source_id": source_id,
                    "cache_key": key,
                    "attempt": attempts,
                    "model": raw.get("model", ""),
                    "system_fingerprint": raw.get("system_fingerprint", ""),
                    "usage": raw.get("usage", {}),
                    "finish_reason": raw.get("finish_reason", ""),
                    "content": raw.get("content", ""),
                    "error": error or raw.get("error", ""),
                }
            )
            if not error:
                self.cache[key] = candidates
                return ExtractionRecord(
                    status="ok", attempts=attempts, candidates=candidates, **base
                )
        return ExtractionRecord(status="failed", error=error, attempts=attempts, **base)
