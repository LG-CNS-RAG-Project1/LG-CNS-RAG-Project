// OpenAI Responses API를 호출해 구조화된 PR 분석 결과를 받고, 공통 반환 계약으로 바꾼다.
// - 요청: model·instructions·input·text.format(json_schema, strict)·reasoning.effort·max_output_tokens·store:false.
//   헤더에는 Authorization(OPENAI_API_KEY)만 넣는다. GitHub·Notion 자격증명은 받지도 보내지도 않는다.
// - 응답: 상태(completed·incomplete·failed), 거절, 실제 응답 모델, 사용량을 읽고 스키마를 로컬에서 다시 검증한다.
// - 오류 분류: auth·model_access·quota·rate_limit·server·timeout·network·invalid_request·incomplete·refusal·schema·model_mismatch.
// - 재시도: 일시적 속도 제한(429)·서버 오류(5xx)·연결 오류만 최대 maxRetries번, 대기 시간이 maxWaitMs 이하일 때만 다시 보낸다.
//   다른 모델로 바꾸거나 다른 제공자로 넘기지 않는다.
import { validateValue } from "./schema_check.mjs";

export const OPENAI_RESPONSES_URL = "https://api.openai.com/v1/responses";
// GPT-6 Luna 모델 문서의 reasoning.effort 허용값
export const REASONING_EFFORTS = ["none", "low", "medium", "high", "xhigh", "max"];
// 다시 보내도 풀리지 않는 결제·한도 오류(공식 오류 코드 문서 기준)
const QUOTA_CODES = new Set([
  "insufficient_quota", "credit_balance_exhausted", "organization_spend_limit_exceeded",
  "project_spend_limit_exceeded", "organization_usage_limit_exceeded",
]);

// 'x-ratelimit-reset-*' 값(예: 1s, 6m0s, 250ms)을 밀리초로 바꾼다. 읽지 못하면 null.
export function parseDuration(value) {
  const text = String(value ?? "").trim();
  if (!text) return null;
  let total = 0;
  let matched = false;
  for (const [, amount, unit] of text.matchAll(/(\d+(?:\.\d+)?)(ms|h|m|s)/g)) {
    matched = true;
    total += Number(amount) * { ms: 1, s: 1000, m: 60_000, h: 3_600_000 }[unit];
  }
  return matched ? Math.round(total) : null;
}

// 응답 헤더에서 다시 보내기 전 기다릴 시간(밀리초)을 구한다. Retry-After를 최소값으로 쓰고, 없으면 reset 헤더 중 큰 값을 쓴다.
export function waitFromHeaders(headers) {
  const get = (name) => headers?.get?.(name) ?? null;
  const retryAfter = Number(get("retry-after"));
  if (Number.isFinite(retryAfter) && retryAfter > 0) return retryAfter * 1000;
  const resets = ["x-ratelimit-reset-requests", "x-ratelimit-reset-tokens", "x-ratelimit-reset-project-tokens"].map((name) => parseDuration(get(name))).filter((ms) => ms !== null);
  return resets.length ? Math.max(...resets) : null;
}

// HTTP 오류 응답을 분류한다. 오류 메시지 원문은 키 일부가 들어 있을 수 있어 돌려주지 않고 type·code만 남긴다.
export function classifyHttpError(status, body, headers) {
  const error = body?.error ?? {};
  const code = String(error.code ?? "");
  const type = String(error.type ?? "");
  const base = { http_status: status, error_code: code || null, error_type: type || null, retryable: false, wait_ms: null };
  if (status === 401) return { ...base, error_class: "auth" };
  if (status === 403) return { ...base, error_class: code === "model_not_found" ? "model_access" : "auth" };
  if (status === 404) return { ...base, error_class: "model_access" };
  if (status === 429) {
    if (QUOTA_CODES.has(code) || QUOTA_CODES.has(type)) return { ...base, error_class: "quota", wait_ms: waitFromHeaders(headers) };
    return { ...base, error_class: "rate_limit", retryable: true, wait_ms: waitFromHeaders(headers) };
  }
  if (status >= 500) return { ...base, error_class: "server", retryable: true, wait_ms: waitFromHeaders(headers) };
  if (status === 400 && (error.param === "model" || /model/.test(code))) return { ...base, error_class: "model_access" };
  return { ...base, error_class: "invalid_request" };
}

// 응답 모델이 요청 모델과 같은지 본다. 날짜 스냅샷 이름(예: gpt-6-luna-2026-05-18)은 같은 모델로 본다.
export function modelMatches(requested, actual) {
  if (!actual) return false;
  if (actual === requested) return true;
  return actual.startsWith(`${requested}-`) && /^\d{4}-\d{2}-\d{2}$/.test(actual.slice(requested.length + 1));
}

// 공식 사용량 필드를 그대로 옮긴다. cached는 input의 일부, reasoning은 output의 일부이므로 따로 더하지 않는다.
export function normalizeUsage(usage) {
  if (!usage) return null;
  return {
    input: usage.input_tokens ?? 0,
    cached: usage.input_tokens_details?.cached_tokens ?? 0,
    cache_write: usage.input_tokens_details?.cache_write_tokens ?? 0,
    output: usage.output_tokens ?? 0,
    reasoning: usage.output_tokens_details?.reasoning_tokens ?? 0,
    total: usage.total_tokens ?? (usage.input_tokens ?? 0) + (usage.output_tokens ?? 0),
  };
}

// Responses API 응답 본문을 공통 계약의 일부로 바꾼다.
export function readResponse(json, { model, schema }) {
  const result = {
    response_id: json?.id ?? null,
    response_model: json?.model ?? null,
    response_status: json?.status ?? null,
    usage: normalizeUsage(json?.usage),
    incomplete_reason: json?.incomplete_details?.reason ?? null,
    refusal: false,
    output: null,
    problems: [],
    error_class: null,
    error_code: null,
  };
  if (json?.status === "incomplete") return { ...result, error_class: "incomplete" };
  if (json?.status !== "completed") return { ...result, error_class: "server", error_code: json?.error?.code ?? json?.status ?? null };
  if (!modelMatches(model, json.model)) return { ...result, error_class: "model_mismatch" };
  const parts = (json.output ?? []).filter((item) => item.type === "message").flatMap((item) => item.content ?? []);
  if (parts.some((part) => part.type === "refusal")) return { ...result, refusal: true, error_class: "refusal" };
  const text = parts.filter((part) => part.type === "output_text").map((part) => part.text).join("");
  let parsed;
  try {
    parsed = JSON.parse(text);
  } catch {
    return { ...result, error_class: "schema", problems: ["JSON으로 읽을 수 없음"] };
  }
  const problems = validateValue(parsed, schema);
  if (problems.length) return { ...result, error_class: "schema", problems };
  return { ...result, output: parsed };
}

const sleepFor = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// Node 내장 fetch는 응답 헤더를 300초까지만 기다리므로 그보다 짧게 끊어 '시간 초과'로 분류한다.
export const DEFAULT_TIMEOUT_MS = 280_000;
const TIMEOUT_CODES = new Set(["UND_ERR_HEADERS_TIMEOUT", "UND_ERR_BODY_TIMEOUT", "UND_ERR_CONNECT_TIMEOUT"]);

export function createOpenAIReviewer({
  apiKey, fetchImpl = fetch, sleep = sleepFor, now = () => Date.now(), random = Math.random,
  timeoutMs = DEFAULT_TIMEOUT_MS, maxRetries = 2, maxWaitMs = 60_000, url = OPENAI_RESPONSES_URL,
}) {
  if (!apiKey) throw new Error("OPENAI_API_KEY가 필요합니다.");

  // 한 번 보내고 응답을 읽는다. 시간 초과는 다시 보내지 않는다(같은 비용을 또 쓰므로).
  async function send(body, request) {
    const controller = new AbortController();
    const timer = setTimeout(() => controller.abort(), timeoutMs);
    try {
      const response = await fetchImpl(url, {
        method: "POST",
        headers: { Authorization: `Bearer ${apiKey}`, "Content-Type": "application/json" },
        body: JSON.stringify(body),
        signal: controller.signal,
      });
      const json = await response.json().catch(() => null);
      if (!response.ok) return { failed: classifyHttpError(response.status, json, response.headers) };
      return { read: readResponse(json, request), http_status: response.status };
    } catch (error) {
      if (error?.name === "AbortError" || TIMEOUT_CODES.has(error?.cause?.code) || TIMEOUT_CODES.has(error?.code)) return { failed: { error_class: "timeout", retryable: false } };
      return { failed: { error_class: "network", retryable: true, wait_ms: null } };
    } finally {
      clearTimeout(timer);
    }
  }

  return {
    provider: "openai",

    // request: { model, instructions, input, schema, schemaName, effort, maxOutputTokens }
    async review(request) {
      if (!REASONING_EFFORTS.includes(request.effort)) throw new Error(`지원하지 않는 reasoning.effort: ${request.effort}`);
      const body = {
        model: request.model,
        instructions: request.instructions,
        input: request.input,
        store: false,
        reasoning: { effort: request.effort },
        max_output_tokens: request.maxOutputTokens,
        text: { format: { type: "json_schema", name: request.schemaName, schema: request.schema, strict: true } },
      };
      const started = now();
      let retries = 0;
      for (;;) {
        const sent = await send(body, request);
        const base = { provider: "openai", requested_model: request.model, retries, duration_ms: now() - started };
        if (sent.read) {
          const { error_class: errorClass, ...rest } = sent.read;
          return { ...base, ...rest, status: errorClass ? "failed" : "done", error_class: errorClass, http_status: sent.http_status, retry_after_at: null };
        }
        const failure = sent.failed;
        const backoff = 1000 * 2 ** retries + Math.round(random() * 500);
        const wait = (failure.wait_ms ?? backoff) + Math.round(random() * 250);
        if (failure.retryable && retries < maxRetries && wait <= maxWaitMs) {
          retries += 1;
          await sleep(wait);
          continue;
        }
        const retryAfterAt = failure.wait_ms ? new Date(now() + failure.wait_ms).toISOString() : null;
        return {
          ...base, status: "failed", error_class: failure.error_class, error_code: failure.error_code ?? null, http_status: failure.http_status ?? null,
          retry_after_at: retryAfterAt, response_id: null, response_model: null, response_status: null, usage: null,
          incomplete_reason: null, refusal: false, output: null, problems: [],
        };
      }
    },
  };
}
