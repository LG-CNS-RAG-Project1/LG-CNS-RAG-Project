// OpenAI Responses API 어댑터 테스트: 요청 형식, 공통 반환 계약, 오류 분류, 제한된 재시도
import assert from "node:assert/strict";
import { test } from "node:test";

import { createFakeOpenAI, okResponse } from "./fakes.mjs";
import { classifyHttpError, createOpenAIReviewer, modelMatches, normalizeUsage, parseDuration } from "./openai_engine.mjs";
import { buildReviewSchema } from "./review_schema.mjs";
import { checkStrictSchema, validateValue } from "./schema_check.mjs";

const SCHEMA = { type: "object", additionalProperties: false, required: ["ok"], properties: { ok: { type: "boolean" } } };
const REQUEST = { model: "gpt-6-sol", instructions: "지시", input: "입력", schema: SCHEMA, schemaName: "check", effort: "medium", maxOutputTokens: 32_000 };

function reviewerWith(respond, options = {}) {
  const fake = createFakeOpenAI(respond);
  const sleeps = [];
  let clock = Date.parse("2026-10-26T08:00:00Z");
  const reviewer = createOpenAIReviewer({
    apiKey: "test-key", fetchImpl: fake.fetchImpl, sleep: async (ms) => { sleeps.push(ms); clock += ms; }, now: () => clock, random: () => 0, ...options,
  });
  return { reviewer, fake, sleeps };
}

test("요청은 모델·strict json_schema·reasoning·출력 상한·store:false를 명시하고, 헤더에는 API 키 인증만 넣는다", async () => {
  const { reviewer, fake } = reviewerWith(() => okResponse({ ok: true }));
  const result = await reviewer.review(REQUEST);
  assert.equal(result.status, "done");
  const [{ url, headers, body }] = fake.requests;
  assert.equal(url, "https://api.openai.com/v1/responses");
  assert.deepEqual(Object.keys(headers).sort(), ["Authorization", "Content-Type"]);
  assert.equal(headers.Authorization, "Bearer test-key");
  assert.equal(body.model, "gpt-6-sol");
  assert.equal(body.store, false);
  assert.deepEqual(body.reasoning, { effort: "medium" });
  assert.equal(body.max_output_tokens, 32_000);
  assert.deepEqual(body.text.format, { type: "json_schema", name: "check", schema: SCHEMA, strict: true });
  assert.equal(body.instructions, "지시");
  assert.equal(body.input, "입력");
  await assert.rejects(reviewer.review({ ...REQUEST, effort: "minimal" }), /reasoning.effort/);
});

test("성공 응답은 공통 계약으로 바뀌고, 캐시는 입력의 일부·추론은 출력의 일부로 그대로 둔다", async () => {
  const { reviewer } = reviewerWith(() => okResponse({ ok: true }));
  const result = await reviewer.review(REQUEST);
  assert.deepEqual(result.output, { ok: true });
  assert.equal(result.response_model, "gpt-6-sol");
  assert.equal(result.requested_model, "gpt-6-sol");
  assert.deepEqual(result.usage, { input: 1200, cached: 300, cache_write: 0, output: 900, reasoning: 400, total: 2100 });
  assert.equal(result.retries, 0);
  assert.ok(result.usage.cached <= result.usage.input && result.usage.reasoning <= result.usage.output);
  assert.equal(normalizeUsage(null), null);
});

test("응답 모델이 요청 모델(또는 그 날짜 스냅샷)이 아니면 결과를 쓰지 않는다", async () => {
  assert.ok(modelMatches("gpt-6-sol", "gpt-6-sol"));
  assert.ok(modelMatches("gpt-6-sol", "gpt-6-sol-2026-05-18"));
  assert.ok(!modelMatches("gpt-6-sol", "gpt-6-sol-mini"));
  assert.ok(!modelMatches("gpt-6-sol", "gpt-6-luna"));
  assert.ok(!modelMatches("gpt-6-sol", "gpt-6.1-sol"));
  const { reviewer } = reviewerWith(() => okResponse({ ok: true }, { model: "gpt-6.1-sol" }));
  const result = await reviewer.review(REQUEST);
  assert.deepEqual([result.status, result.error_class, result.output], ["failed", "model_mismatch", null]);
});

test("일시적 속도 제한(429)은 Retry-After 이상 기다린 뒤 다시 보내고, 성공하면 재시도 수를 남긴다", async () => {
  const { reviewer, fake, sleeps } = reviewerWith((body, index) => (index === 0
    ? { status: 429, headers: { "retry-after": "2" }, body: { error: { type: "rate_limit_error", code: "rate_limit_exceeded" } } }
    : okResponse({ ok: true })));
  const result = await reviewer.review(REQUEST);
  assert.equal(result.status, "done");
  assert.equal(result.retries, 1);
  assert.equal(fake.requests.length, 2);
  assert.ok(sleeps[0] >= 2000);
});

test("재설정까지 오래 걸리는 속도 제한은 다시 보내지 않고 재시도 가능 시각을 남긴다", async () => {
  const { reviewer, fake } = reviewerWith(() => ({ status: 429, headers: { "x-ratelimit-reset-tokens": "6m0s" }, body: { error: { type: "rate_limit_error" } } }));
  const result = await reviewer.review(REQUEST);
  assert.deepEqual([result.status, result.error_class, fake.requests.length], ["failed", "rate_limit", 1]);
  assert.equal(result.retry_after_at, "2026-10-26T08:06:00.000Z");
  assert.equal(parseDuration("1m30s"), 90_000);
  assert.equal(parseDuration("250ms"), 250);
  assert.equal(parseDuration(""), null);
});

test("결제·사용 한도 429는 다시 보내지 않는다", async () => {
  for (const error of [{ type: "insufficient_quota" }, { code: "credit_balance_exhausted" }, { code: "project_spend_limit_exceeded" }]) {
    const { reviewer, fake } = reviewerWith(() => ({ status: 429, body: { error } }));
    const result = await reviewer.review(REQUEST);
    assert.deepEqual([result.error_class, fake.requests.length], ["quota", 1]);
  }
});

test("서버 오류·연결 오류는 최대 2번만 다시 보내고, 인증·모델 접근·요청 형식 오류는 다시 보내지 않는다", async () => {
  const server = reviewerWith(() => ({ status: 503, body: { error: { type: "service_unavailable_error", code: "server_is_overloaded" } } }));
  const failed = await server.reviewer.review(REQUEST);
  assert.deepEqual([failed.error_class, failed.retries, server.fake.requests.length], ["server", 2, 3]);

  let attempts = 0;
  const network = createOpenAIReviewer({ apiKey: "k", fetchImpl: async () => { attempts += 1; if (attempts === 1) throw new TypeError("fetch failed"); return { ok: true, status: 200, headers: { get: () => null }, json: async () => okResponse({ ok: true }) }; }, sleep: async () => {}, random: () => 0 });
  assert.equal((await network.review(REQUEST)).status, "done");

  for (const [status, error, expected] of [[401, { code: "invalid_api_key" }, "auth"], [404, { code: "model_not_found" }, "model_access"], [400, { param: "model", code: "model_not_found" }, "model_access"], [400, { code: "invalid_json_schema" }, "invalid_request"]]) {
    const { reviewer, fake } = reviewerWith(() => ({ status, body: { error: { message: "Incorrect API key provided: sk-…abcd", ...error } } }));
    const result = await reviewer.review(REQUEST);
    assert.deepEqual([result.error_class, fake.requests.length], [expected, 1]);
    assert.ok(!JSON.stringify(result).includes("Incorrect API key"), "오류 메시지 원문은 남기지 않음");
  }
});

test("미완료·거절·스키마 위반 응답은 각각 분류하고 결과를 쓰지 않는다", async () => {
  const incomplete = reviewerWith(() => ({ ...okResponse({ ok: true }), status: "incomplete", incomplete_details: { reason: "max_output_tokens" } }));
  const a = await incomplete.reviewer.review(REQUEST);
  assert.deepEqual([a.error_class, a.incomplete_reason, a.output, a.usage.output], ["incomplete", "max_output_tokens", null, 900]);

  const refusal = reviewerWith(() => ({ ...okResponse({}), output: [{ type: "message", content: [{ type: "refusal", refusal: "거절" }] }] }));
  const b = await refusal.reviewer.review(REQUEST);
  assert.deepEqual([b.error_class, b.refusal], ["refusal", true]);

  const invalid = reviewerWith(() => okResponse({ ok: "yes", extra: 1 }));
  const c = await invalid.reviewer.review(REQUEST);
  assert.equal(c.error_class, "schema");
  assert.ok(c.problems.length >= 2);
});

test("시간 초과는 다시 보내지 않는다", async () => {
  const reviewer = createOpenAIReviewer({
    apiKey: "k", timeoutMs: 10, sleep: async () => {},
    fetchImpl: (url, { signal }) => new Promise((resolve, reject) => signal.addEventListener("abort", () => reject(Object.assign(new Error("aborted"), { name: "AbortError" })))),
  });
  const result = await reviewer.review(REQUEST);
  assert.deepEqual([result.error_class, result.retries], ["timeout", 0]);
});

test("HTTP 오류 분류표", () => {
  assert.equal(classifyHttpError(403, { error: {} }).error_class, "auth");
  assert.equal(classifyHttpError(500, {}).retryable, true);
  assert.equal(classifyHttpError(429, { error: { code: "slow_down", type: "rate_limit_error" } }).error_class, "rate_limit");
});

test("PR 분석 응답 스키마는 OpenAI strict 규칙을 지키고, 로컬 검증은 빠진 항목·정의되지 않은 항목·허용되지 않은 값·개수 초과를 잡는다", () => {
  assert.deepEqual(checkStrictSchema(buildReviewSchema(["ingestion", "retrieval"])), []);
  assert.deepEqual(checkStrictSchema(buildReviewSchema([])), []);
  assert.ok(checkStrictSchema({ type: "object", properties: { a: { type: "string" } } }).length >= 2);
  const schema = buildReviewSchema(["ingestion"]);
  const problems = validateValue({ head_sha: 1, extra: true, findings: Array.from({ length: 9 }, () => ({})) }, schema);
  assert.ok(problems.some((item) => item.includes("$.summary: 없음")));
  assert.ok(problems.some((item) => item.includes("$.extra: 정의되지 않은 항목")));
  assert.ok(problems.some((item) => item.includes("$.head_sha: string")));
  assert.ok(problems.some((item) => item.includes("최대 8")));
});
