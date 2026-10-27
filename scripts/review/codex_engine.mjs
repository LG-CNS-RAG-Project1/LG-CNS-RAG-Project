// Codex CLI(ChatGPT 구독 로그인)를 비대화형으로 한 번 실행해 구조화된 PR 분석 결과를 받고, 공통 반환 계약으로 바꾼다.
// - 인증: CODEX_HOME의 auth.json(ChatGPT 로그인)만 쓴다. API 키·GitHub·Notion 자격증명 환경변수는 자식 프로세스에 넘기지 않는다.
// - 격리: 명령 실행 도구·웹 검색·커넥터·다중 에이전트·훅·메모리를 끄고, 빈 작업 폴더·읽기 전용 샌드박스·세션 미저장으로 실행한다.
//   도구 차단이 검증되지 않으면 호출하지 않는다.
// - 지시문: model_instructions_file로 Codex 기본 지시문 대신 분석 지시문만 쓴다.
// - 출력: --output-schema로 구조화 출력을 받고, --json 이벤트의 turn.completed에서 사용량을 읽는다.
//   Codex는 응답 모델 이름과 출력 토큰 상한 설정을 제공하지 않으므로 요청 모델(-m)과 reasoning 강도만 지정한다.
// - 재시도: 이 모듈은 다시 실행하지 않는다(연결 재시도는 Codex 내부에서 한다).
import { spawn } from "node:child_process";
import { existsSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { maskPatch } from "./lib.mjs";
import { REASONING_EFFORTS } from "./openai_engine.mjs";
import { validateValue } from "./schema_check.mjs";
import { checkCodexPolicy, CODEX_VERSION, POLICY_ARGS } from "./codex_policy.mjs";

export { CODEX_VERSION };
const OUTPUT_LIMIT = 16 * 1024 * 1024;

// Codex 실행 인자. 도구 관련 기능을 끄고 결과 형식을 지정한다.
export function codexArgs({ model, effort, workDir, instructionsFile, schemaFile, lastFile }) {
  return [
    "exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check",
    "-C", workDir, "-s", "read-only", "-m", model,
    "-c", `model_reasoning_effort=${JSON.stringify(effort)}`,
    "-c", `model_instructions_file=${JSON.stringify(instructionsFile)}`,
    "-c", 'approval_policy="never"',
    ...POLICY_ARGS,
    "-c", 'history.persistence="none"',
    "--output-schema", schemaFile, "-o", lastFile, "--json", "-",
  ];
}

// 자식 프로세스 환경변수: 실행에 필요한 것만 넘긴다(OPENAI_API_KEY·CODEX_API_KEY가 있으면 구독 대신 API 키를 쓰게 되므로 넘기지 않는다).
export const codexEnv = (source, { codexHome, home }) => ({
  PATH: source.PATH ?? "",
  HOME: home,
  CODEX_HOME: codexHome,
  LANG: "en_US.UTF-8",
  TZ: "UTC",
});

// --json 이벤트(JSON Lines)에서 사용량·오류·스레드 ID를 읽는다.
export function parseEvents(text) {
  const result = { usage: null, messages: [], failed: false, model_rerouted: false, thread_id: null };
  for (const line of String(text ?? "").split("\n")) {
    if (!line.trim()) continue;
    let event;
    try {
      event = JSON.parse(line);
    } catch {
      continue;
    }
    if (event.type === "thread.started") result.thread_id = event.thread_id ?? null;
    if (event.type === "turn.completed" && event.usage) result.usage = event.usage;
    if (event.type === "turn.failed") {
      result.failed = true;
      result.messages.push(String(event.error?.message ?? "turn.failed"));
    }
    if (event.type === "error") result.messages.push(String(event.message ?? ""));
    if (event.type === "item.completed" && event.item?.type === "error" && /^model rerouted:/i.test(String(event.item.message ?? ""))) result.model_rerouted = true;
  }
  return result;
}

// 사용량: 공식 필드 그대로. cached는 input의 일부, reasoning은 output의 일부다.
export const codexUsage = (usage) => (usage ? {
  input: usage.input_tokens ?? 0,
  cached: usage.cached_input_tokens ?? 0,
  cache_write: usage.cache_write_input_tokens ?? 0,
  output: usage.output_tokens ?? 0,
  reasoning: usage.reasoning_output_tokens ?? 0,
  total: (usage.input_tokens ?? 0) + (usage.output_tokens ?? 0),
} : null);

// 로그에 남길 오류 글: 토큰처럼 보이는 값을 가리고 한 줄 200자로 자른다.
export const safeMessage = (value) =>
  maskPatch(String(value ?? "")).replace(/eyJ[\w-]{10,}\.[\w-]{10,}\.[\w-]{10,}/g, "****(토큰 가림)").replace(/\s+/g, " ").slice(0, 200);

// '… try again at 3:05 PM'·'resets in 2h 10m' 같은 안내에서 재시도 가능 시각을 읽는다. 못 읽으면 null.
export function parseRetryAt(messages, now) {
  const text = messages.join(" ");
  const absolute = /\b(?:try again at|resets? at)\s+(?:(Jan(?:uary)?|Feb(?:ruary)?|Mar(?:ch)?|Apr(?:il)?|May|Jun(?:e)?|Jul(?:y)?|Aug(?:ust)?|Sep(?:tember)?|Oct(?:ober)?|Nov(?:ember)?|Dec(?:ember)?)\s+(\d{1,2})(?:st|nd|rd|th)?[,]?\s+(\d{4})\s+)?(\d{1,2}):(\d{2})\s*(AM|PM)\b/i.exec(text);
  if (absolute) {
    const [, monthName, day, year, hourText, minuteText, meridiem] = absolute;
    const hour = Number(hourText), minute = Number(minuteText);
    if (hour < 1 || hour > 12 || minute > 59) return null;
    const current = new Date(now);
    const month = monthName ? ["jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"].indexOf(monthName.slice(0, 3).toLowerCase()) : current.getUTCMonth();
    const y = year ? Number(year) : current.getUTCFullYear();
    const d = day ? Number(day) : current.getUTCDate();
    const date = new Date(Date.UTC(y, month, d, hour % 12 + (meridiem.toUpperCase() === "PM" ? 12 : 0), minute));
    if (date.getUTCFullYear() !== y || date.getUTCMonth() !== month || date.getUTCDate() !== d) return null;
    if (!monthName && date.getTime() <= now) date.setUTCDate(date.getUTCDate() + 1);
    return date.getTime() > now ? date.toISOString() : null;
  }
  const relative = /\b(?:in|after)\s+(\d+)\s*(h|hours?|m|mins?|minutes?)\b(?:\s*(\d+)\s*(?:m|mins?|minutes?)\b)?/i.exec(text);
  if (!relative) return null;
  const first = Number(relative[1]);
  const minutes = /^h/i.test(relative[2]) ? first * 60 + Number(relative[3] ?? 0) : first;
  return new Date(now + minutes * 60_000).toISOString();
}

// 실행 결과를 오류 분류로 바꾼다.
export function classifyCodexFailure({ timedOut, messages, now }) {
  const text = messages.join(" ");
  const status = Number(/\b(4\d\d|5\d\d)\b/.exec(text)?.[1]) || null;
  const base = { http_status: status, retry_after_at: null };
  if (timedOut) return { ...base, error_class: "timeout" };
  if (/usage limit|hit your .*limit|plan limit|quota/i.test(text)) return { ...base, error_class: "plan_limit", retry_after_at: parseRetryAt(messages, now) };
  if (status === 429 || /rate limit|too many requests/i.test(text)) return { ...base, error_class: "rate_limit", retry_after_at: parseRetryAt(messages, now) };
  if (status === 401 || status === 403 || /unauthori[sz]ed|not logged in|log ?in again|authentication|could not be refreshed|sign in again|refresh token/i.test(text)) return { ...base, error_class: "auth" };
  if (status === 404 || /model .*(not found|not supported|does not exist|unavailable|access)/i.test(text)) return { ...base, error_class: "model_access" };
  if (status >= 500) return { ...base, error_class: "server" };
  return { ...base, error_class: "codex_failed" };
}

// 자식 프로세스를 실행하고 끝나기를 기다린다. 시간이 지나면 종료한다.
function run(spawnImpl, bin, args, { input, env, cwd, timeoutMs }) {
  return new Promise((resolve) => {
    let stdout = "";
    let stderr = "";
    let timedOut = false;
    let child;
    try {
      child = spawnImpl(bin, args, { env, cwd, stdio: ["pipe", "pipe", "pipe"] });
    } catch (error) {
      resolve({ code: null, stdout, stderr: String(error?.message ?? error), timedOut, spawnError: true });
      return;
    }
    const timer = setTimeout(() => {
      timedOut = true;
      child.kill("SIGTERM");
      setTimeout(() => child.kill("SIGKILL"), 5_000).unref?.();
    }, timeoutMs);
    child.stdout.on("data", (chunk) => { if (stdout.length < OUTPUT_LIMIT) stdout += chunk; });
    child.stderr.on("data", (chunk) => { if (stderr.length < OUTPUT_LIMIT) stderr += chunk; });
    child.on("error", (error) => {
      clearTimeout(timer);
      resolve({ code: null, stdout, stderr: String(error?.message ?? error), timedOut, spawnError: true });
    });
    child.on("close", (code) => {
      clearTimeout(timer);
      resolve({ code, stdout, stderr, timedOut });
    });
    child.stdin.on("error", () => {});
    child.stdin.end(input);
  });
}

export function createCodexReviewer({
  codexHome, bin = "codex", spawnImpl = spawn, timeoutMs = 10 * 60 * 1000, now = () => Date.now(), tmpRoot = tmpdir(), source = process.env, policyCheck = checkCodexPolicy,
}) {
  if (!codexHome || !existsSync(join(codexHome, "auth.json"))) throw new Error("CODEX_HOME에 ChatGPT 로그인 정보(auth.json)가 필요합니다.");

  return {
    provider: "codex",

    // request: { model, instructions, input, schema, schemaName, effort } (maxOutputTokens는 Codex가 지원하지 않아 쓰지 않는다)
    async review(request) {
      if (!REASONING_EFFORTS.includes(request.effort)) throw new Error(`지원하지 않는 reasoning.effort: ${request.effort}`);
      try {
        policyCheck({ bin, path: source.PATH });
      } catch {
        return { provider: "codex", requested_model: request.model, response_model: null, status: "failed", error_class: "codex_failed", http_status: null, retry_after_at: null, usage: null, duration_ms: 0, retries: 0, model_calls: 0, output: null, problems: ["Codex 보안 점검 실패: 도구 차단을 확인할 수 없어 호출하지 않았습니다."] };
      }
      const sandbox = mkdtempSync(join(tmpRoot, "pr-review-codex-"));
      const started = now();
      try {
        const workDir = join(sandbox, "work");
        const home = join(sandbox, "home");
        for (const dir of [workDir, home]) mkdirSync(dir, { recursive: true });
        const instructionsFile = join(sandbox, "instructions.md");
        const schemaFile = join(sandbox, "schema.json");
        const lastFile = join(sandbox, "last.json");
        writeFileSync(instructionsFile, request.instructions);
        writeFileSync(schemaFile, JSON.stringify(request.schema));
        const args = codexArgs({ model: request.model, effort: request.effort, workDir, instructionsFile, schemaFile, lastFile });
        const done = await run(spawnImpl, bin, args, { input: request.input, env: codexEnv(source, { codexHome, home }), cwd: workDir, timeoutMs });
        const events = parseEvents(done.stdout);
        const base = {
          provider: "codex", requested_model: request.model, response_model: null, response_id: events.thread_id, response_status: null,
          usage: codexUsage(events.usage), duration_ms: now() - started, retries: 0, incomplete_reason: null, refusal: false,
          error_code: null, output: null, problems: [],
        };
        const output = existsSync(lastFile) ? readFileSync(lastFile, "utf8") : "";
        if (events.model_rerouted) return { ...base, status: "failed", error_class: "model_mismatch", http_status: null, retry_after_at: null, problems: ["Codex가 요청 모델을 다른 모델로 전환해 결과를 폐기했습니다."] };
        if (done.code === 0 && !events.failed && output.trim()) {
          let parsed;
          try {
            parsed = JSON.parse(output);
          } catch {
            return { ...base, status: "failed", error_class: "schema", http_status: null, retry_after_at: null, problems: ["JSON으로 읽을 수 없음"] };
          }
          const problems = validateValue(parsed, request.schema);
          if (problems.length) return { ...base, status: "failed", error_class: "schema", http_status: null, retry_after_at: null, problems: ["응답 스키마 검증 실패"] };
          return { ...base, status: "done", error_class: null, http_status: null, retry_after_at: null, output: parsed };
        }
        const messages = [...events.messages, ...(done.stderr ? [done.stderr] : [])];
        const failure = classifyCodexFailure({ timedOut: done.timedOut, messages, now: now() });
        // 인증 서버 등의 임의 텍스트는 새로운 토큰을 포함할 수 있으므로 공개 로그에 넘기지 않는다.
        const descriptions = { auth: "Codex 인증 또는 토큰 갱신 실패", plan_limit: "Codex 구독 사용 한도", rate_limit: "Codex 요청 속도 제한", server: "Codex 서버 오류", timeout: "Codex 실행 시간 초과", model_access: "Codex 모델 접근 실패", codex_failed: "Codex 실행 실패" };
        return { ...base, status: "failed", ...failure, problems: [descriptions[failure.error_class] ?? "Codex 실행 실패"] };
      } finally {
        rmSync(sandbox, { recursive: true, force: true });
      }
    },
  };
}
