// Codex CLI(ChatGPT 구독) 어댑터 테스트: 실행 인자·환경 격리, 공통 반환 계약, 오류 분류, 분석기 선택
import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { PassThrough } from "node:stream";
import { test } from "node:test";

import { classifyCodexFailure, codexArgs, codexEnv, createCodexReviewer, parseEvents, parseRetryAt, safeMessage } from "./codex_engine.mjs";
import { checkCodexPolicy, DISABLED_FEATURES, inspectFeatures } from "./codex_policy.mjs";
import { selectReviewer } from "./pipeline.mjs";

const SCHEMA = { type: "object", additionalProperties: false, required: ["ok"], properties: { ok: { type: "boolean" } } };
const REQUEST = { model: "gpt-6-luna", instructions: "분석 지시문", input: "PR 입력", schema: SCHEMA, schemaName: "check", effort: "medium", maxOutputTokens: 32_000 };

function codexHome() {
  const dir = mkdtempSync(join(tmpdir(), "codex-home-test-"));
  writeFileSync(join(dir, "auth.json"), "{}");
  return dir;
}

// 가짜 codex 프로세스: plan(args, stdin)이 { events, last, code, hang }을 정한다.
function fakeSpawn(plan) {
  const calls = [];
  const spawnImpl = (bin, args, options) => {
    const child = new EventEmitter();
    child.stdout = new PassThrough();
    child.stderr = new PassThrough();
    child.stdin = new PassThrough();
    child.kill = () => setImmediate(() => child.emit("close", null));
    let input = "";
    child.stdin.on("data", (chunk) => { input += chunk; });
    child.stdin.on("end", () => {
      const lastFile = args[args.indexOf("-o") + 1];
      const instructionsFile = JSON.parse(args.find((arg) => arg.startsWith("model_instructions_file=")).split("=").slice(1).join("="));
      const schemaFile = args[args.indexOf("--output-schema") + 1];
      calls.push({ bin, args, env: options.env, input, instructions: readFileSync(instructionsFile, "utf8"), schema: JSON.parse(readFileSync(schemaFile, "utf8")), sandbox: join(lastFile, "..") });
      const result = plan(args, input);
      if (result.hang) return;
      if (result.last !== undefined) writeFileSync(lastFile, result.last);
      child.stdout.end((result.events ?? []).map((event) => JSON.stringify(event)).join("\n"));
      child.stderr.end(result.stderr ?? "");
      setImmediate(() => child.emit("close", result.code ?? 0));
    });
    return child;
  };
  return { spawnImpl, calls };
}

const ok = { events: [{ type: "thread.started", thread_id: "t-1" }, { type: "turn.completed", usage: { input_tokens: 18670, cached_input_tokens: 2000, cache_write_input_tokens: 0, output_tokens: 1701, reasoning_output_tokens: 352 } }], last: JSON.stringify({ ok: true }) };

test("실행 인자는 명령 실행·웹 검색·커넥터·다중 에이전트·훅·메모리를 끄고 사용자 설정을 읽지 않으며, 자식 환경에는 API 키·GitHub·Notion 토큰을 넘기지 않는다", async () => {
  const args = codexArgs({ model: "gpt-6-luna", effort: "medium", workDir: "/w", instructionsFile: "/i.md", schemaFile: "/s.json", lastFile: "/l.json" });
  for (const expected of ["--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check", "features.shell_tool=false", 'web_search="disabled"', "features.apps=false", "features.multi_agent=false", "features.hooks=false", "features.memories=false", "tools.update_plan.enabled=false", "tools.experimental_request_user_input.enabled=false", "agents.enabled=false", 'approval_policy="never"', 'history.persistence="none"', 'model_reasoning_effort="medium"', "--json"]) {
    assert.ok(args.includes(expected), expected);
  }
  assert.deepEqual(args.slice(args.indexOf("-s"), args.indexOf("-s") + 2), ["-s", "read-only"]);
  assert.equal(args.at(-1), "-");
  const env = codexEnv({ PATH: "/bin", OPENAI_API_KEY: "k", CODEX_API_KEY: "c", GITHUB_TOKEN: "g", NOTION_REVIEW_TOKEN: "n", CODEX_AUTH_JSON: "a" }, { codexHome: "/h/.codex", home: "/tmp/home" });
  assert.deepEqual(Object.keys(env).sort(), ["CODEX_HOME", "HOME", "LANG", "PATH", "TZ"]);
  assert.equal(env.TZ, "UTC");

  const home = codexHome();
  const fake = fakeSpawn(() => ok);
  const reviewer = createCodexReviewer({ codexHome: home, policyCheck: () => {}, spawnImpl: fake.spawnImpl, source: { PATH: "/bin", OPENAI_API_KEY: "k", GITHUB_TOKEN: "g" } });
  await reviewer.review(REQUEST);
  const [call] = fake.calls;
  assert.equal(call.bin, "codex");
  assert.deepEqual(Object.keys(call.env).sort(), ["CODEX_HOME", "HOME", "LANG", "PATH", "TZ"]);
  assert.equal(call.env.CODEX_HOME, home);
  assert.equal(call.input, "PR 입력");
  assert.equal(call.instructions, "분석 지시문");
  assert.deepEqual(call.schema, SCHEMA);
  assert.ok(!existsSync(call.sandbox), "임시 폴더 정리");
});

test("성공하면 공통 반환 계약으로 바꾸고, 사용량은 캐시·추론을 더하지 않으며 응답 모델은 Codex가 알려 주지 않아 null로 둔다", async () => {
  const fake = fakeSpawn(() => ok);
  const result = await createCodexReviewer({ codexHome: codexHome(), policyCheck: () => {}, spawnImpl: fake.spawnImpl }).review(REQUEST);
  assert.equal(result.status, "done");
  assert.deepEqual(result.output, { ok: true });
  assert.deepEqual(result.usage, { input: 18670, cached: 2000, cache_write: 0, output: 1701, reasoning: 352, total: 20371 });
  assert.deepEqual([result.provider, result.requested_model, result.response_model, result.response_id, result.retries], ["codex", "gpt-6-luna", null, "t-1", 0]);
});

test("결과 파일이 스키마에 맞지 않거나 JSON이 아니면 형식 실패로 둔다", async () => {
  for (const last of [JSON.stringify({ ok: "yes", extra: 1 }), "not json"]) {
    const fake = fakeSpawn(() => ({ ...ok, last }));
    const result = await createCodexReviewer({ codexHome: codexHome(), policyCheck: () => {}, spawnImpl: fake.spawnImpl }).review(REQUEST);
    assert.deepEqual([result.status, result.error_class, result.output], ["failed", "schema", null]);
  }
});

test("실패는 인증·구독 한도·속도 제한·서버·시간 초과로 나누고, 로그용 글에서는 토큰처럼 보이는 값을 가린다", async () => {
  const now = Date.parse("2026-10-27T01:00:00Z");
  const failed = (message) => ({ events: [{ type: "error", message }, { type: "turn.failed", error: { message } }], code: 1 });
  const cases = [
    ["Reconnecting... 5/5 (unexpected status 401 Unauthorized: Missing bearer)", "auth"],
    ["You've hit your usage limit. Try again in 2h 5m.", "plan_limit"],
    ["unexpected status 429 Too Many Requests", "rate_limit"],
    ["unexpected status 503 Service Unavailable", "server"],
    ["something else broke", "codex_failed"],
  ];
  for (const [message, expected] of cases) {
    const fake = fakeSpawn(() => failed(message));
    const result = await createCodexReviewer({ codexHome: codexHome(), policyCheck: () => {}, spawnImpl: fake.spawnImpl, now: () => now }).review(REQUEST);
    assert.deepEqual([result.status, result.error_class], ["failed", expected], message);
  }
  assert.equal(classifyCodexFailure({ timedOut: false, messages: ["You've hit your usage limit. Try again in 2h 5m."], now }).retry_after_at, "2026-10-27T03:05:00.000Z");
  const hang = fakeSpawn(() => ({ hang: true }));
  const timedOut = await createCodexReviewer({ codexHome: codexHome(), policyCheck: () => {}, spawnImpl: hang.spawnImpl, timeoutMs: 20 }).review(REQUEST);
  assert.equal(timedOut.error_class, "timeout");
  const jwt = ["eyJhbGciOiJSUzI1NiJ9", "eyJzdWIiOiIxMjM0NTY3ODkwIn0", "c2lnbmF0dXJlc2lnbmF0dXJl"].join(".");
  assert.ok(!safeMessage(`token ${jwt} 실패`).includes(jwt));
  assert.deepEqual(parseEvents('{"type":"thread.started","thread_id":"x"}\nnot json\n{"type":"turn.completed","usage":{"input_tokens":1}}').usage, { input_tokens: 1 });
});

test("ChatGPT 로그인 정보가 없으면 Codex 분석기를 만들지 않는다", () => {
  const empty = mkdtempSync(join(tmpdir(), "codex-empty-"));
  mkdirSync(join(empty, "x"));
  assert.throws(() => createCodexReviewer({ codexHome: empty }), /auth\.json/);
});

test("갱신 토큰 오류와 UTC 절대 시각을 분류한다", () => {
  const now = Date.parse("2026-10-27T16:00:00Z");
  for (const cause of ["already used", "has expired", "was revoked"]) {
    assert.equal(classifyCodexFailure({ messages: [`Your access token could not be refreshed because your refresh token ${cause}. Please sign in again.`], now }).error_class, "auth");
  }
  for (const [message, expected] of [
    ["Try again at 3:05 PM", "2026-10-28T15:05:00.000Z"],
    ["Try again at 12:05 AM", "2026-10-28T00:05:00.000Z"],
    ["Try again at Oct 29th, 2026 3:05 PM", "2026-10-29T15:05:00.000Z"],
    ["Try again at Feb 30th, 2026 3:05 PM", null],
    ["Try again at 13:05 PM", null],
  ]) assert.equal(parseRetryAt([message], now), expected, message);
});

test("stderr에만 나온 갱신 오류도 인증 오류이며 원문은 반환하지 않는다", async () => {
  const fake = fakeSpawn(() => ({ code: 1, stderr: "Your refresh token was revoked; sign in again. synthetic-private-value" }));
  const reviewer = createCodexReviewer({ codexHome: codexHome(), policyCheck: () => {}, spawnImpl: fake.spawnImpl });
  const result = await reviewer.review(REQUEST);
  assert.equal(result.error_class, "auth");
  assert.ok(!JSON.stringify(result).includes("synthetic-private-value"));
});

test("Codex가 모델 전환을 보고하면 성공 결과도 폐기한다", async () => {
  const fake = fakeSpawn(() => ({ ...ok, events: [{ type: "item.completed", item: { type: "error", message: "model rerouted: gpt-6-luna -> other (reason)" } }, ...ok.events] }));
  const reviewer = createCodexReviewer({ codexHome: codexHome(), policyCheck: () => {}, spawnImpl: fake.spawnImpl });
  const result = await reviewer.review(REQUEST);
  assert.equal(result.error_class, "model_mismatch");
  assert.equal(result.output, null);
});

test("기능 목록의 도구 기능이 켜지거나 형식이 바뀌면 차단하고, 실제 도구 노출을 입증할 수 없으면 호출하지 않는다", async () => {
  const lines = DISABLED_FEATURES.map((name) => `${name}  stable  false`).join("\n");
  assert.doesNotThrow(() => inspectFeatures(lines));
  assert.throws(() => inspectFeatures(lines.replace("unified_exec  stable  false", "unified_exec  stable  true")), /unified_exec/);
  assert.throws(() => inspectFeatures(`${lines}\nunknown_browser_use  stable  true`), /unknown_browser_use/);
  assert.throws(() => inspectFeatures("malformed"), /형식/);
  const fakeSync = (bin, args) => ({ status: 0, stdout: args[0] === "--version" ? "codex-cli 0.160.1\n" : lines });
  assert.throws(() => checkCodexPolicy({ spawnImpl: fakeSync }), /실제 도구 노출/);
  let spawned = false;
  const reviewer = createCodexReviewer({ codexHome: codexHome(), policyCheck: () => { throw new Error("blocked"); }, spawnImpl: () => { spawned = true; } });
  const result = await reviewer.review(REQUEST);
  assert.equal(result.status, "failed");
  assert.equal(spawned, false);
});

test("분석기는 설정한 제공자 하나만 만들고, 인증 정보가 없으면 다른 제공자로 넘어가지 않는다", () => {
  const factories = { codex: () => "codex-reviewer", openai: () => "openai-reviewer" };
  const pick = (provider, env, has = true, step = "analyze") => selectReviewer({ step, provider, env, factories, hasCodexLogin: () => has });
  assert.equal(pick("codex", { CODEX_HOME: "/h" }), "codex-reviewer");
  assert.equal(pick("codex", { OPENAI_API_KEY: "k" }), null, "Codex 로그인이 없으면 API 키가 있어도 쓰지 않음");
  assert.equal(pick("codex", { CODEX_HOME: "/h" }, false), null);
  assert.equal(pick("openai", { OPENAI_API_KEY: "k", CODEX_HOME: "/h" }), "openai-reviewer");
  assert.equal(pick("openai", { CODEX_HOME: "/h" }), null, "API 키가 없으면 Codex 로그인이 있어도 쓰지 않음");
  assert.equal(pick("anthropic", { OPENAI_API_KEY: "k", CODEX_HOME: "/h" }), null);
  assert.equal(pick("codex", { CODEX_HOME: "/h" }, true, "cards"), null);
});
