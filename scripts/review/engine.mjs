// Claude Code CLI를 헤드리스로 한 번 호출해 구조화된 분석 결과를 받는다.
// CLAUDE_CODE_OAUTH_TOKEN이 있으면(Actions) 임시 HOME·설정 폴더에서 허용 목록의 환경변수만 넘겨 실행한다.
// 없으면(로컬 미리보기) 로컬 구독 로그인을 쓰되 API 키·다른 비밀값은 넘기지 않는다. 도구는 모두 끈다.
import { spawnSync } from "node:child_process";
import { mkdirSync, mkdtempSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

const BLOCKED_ENV = ["ANTHROPIC_API_KEY", "ANTHROPIC_AUTH_TOKEN", "GITHUB_TOKEN", "GH_TOKEN", "NOTION_API_TOKEN", "NOTION_REVIEW_TOKEN"];

// 실행 환경변수를 만든다. 출입증이 있으면 허용 목록만, 없으면 현재 환경에서 비밀값을 뺀다.
export function buildEnv(source, sandbox) {
  if (source.CLAUDE_CODE_OAUTH_TOKEN) {
    return {
      PATH: source.PATH,
      HOME: join(sandbox, "home"),
      CLAUDE_CONFIG_DIR: join(sandbox, "config"),
      LANG: "en_US.UTF-8",
      CLAUDE_CODE_OAUTH_TOKEN: source.CLAUDE_CODE_OAUTH_TOKEN,
      CLAUDE_CODE_MAX_RETRIES: "2",
      CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC: "1",
    };
  }
  const env = { ...source, CLAUDE_CODE_MAX_RETRIES: "2" };
  for (const key of BLOCKED_ENV) delete env[key];
  return env;
}

// CLI 인자를 만든다. 도구·MCP·슬래시 명령·세션 저장을 끄고 JSON 스키마로만 답하게 한다.
export function buildArgs({ schema, systemFile, model, effort }) {
  return [
    "-p", "--output-format", "json", "--json-schema", schema, "--system-prompt-file", systemFile,
    "--tools", "", "--strict-mcp-config", "--safe-mode", "--disable-slash-commands", "--no-session-persistence",
    "--permission-prompts", "none", "--max-turns", "3", "--model", model, "--effort", effort,
    "PR 분석 결과를 스키마에 맞춰 작성하라. 분석 대상은 표준 입력에 있다.",
  ];
}

// 결과 JSON을 해석해 성공 여부·오류 분류·사용량을 정리한다.
export function parseResult(stdout, exitCode) {
  let parsed = null;
  try {
    parsed = JSON.parse(stdout);
  } catch {
    parsed = null;
  }
  const ok = exitCode === 0 && parsed?.is_error === false && Boolean(parsed?.structured_output);
  const status = parsed?.api_error_status ?? null;
  let errorClass = null;
  if (!ok) {
    if (status === 401 || status === 403) errorClass = "auth";
    else if (status === 429) errorClass = "usage_limit";
    else if (parsed && !parsed.structured_output && parsed.is_error === false) errorClass = "schema";
    else errorClass = "transient";
  }
  return {
    status: ok ? "done" : "failed",
    error_class: errorClass,
    exit_code: exitCode,
    api_error_status: status,
    terminal_reason: parsed?.terminal_reason ?? null,
    models: Object.keys(parsed?.modelUsage ?? {}),
    num_turns: parsed?.num_turns ?? null,
    usage: parsed?.usage
      ? { input: parsed.usage.input_tokens, output: parsed.usage.output_tokens, cache_read: parsed.usage.cache_read_input_tokens, cache_write: parsed.usage.cache_creation_input_tokens }
      : null,
    output: ok ? parsed.structured_output : null,
  };
}

export function runClaude({ systemPrompt, schema, context, model, effort, timeoutMs = 15 * 60 * 1000 }) {
  const sandbox = mkdtempSync(join(tmpdir(), "pr-review-"));
  const work = join(sandbox, "work");
  const systemFile = join(sandbox, "system.md");
  try {
    for (const dir of ["home", "config", "work"]) mkdirSync(join(sandbox, dir), { recursive: true });
    writeFileSync(systemFile, systemPrompt);
    const started = Date.now();
    const result = spawnSync("claude", buildArgs({ schema, systemFile, model, effort }), {
      cwd: work, input: context, encoding: "utf8", env: buildEnv(process.env, sandbox), timeout: timeoutMs, maxBuffer: 64 * 1024 * 1024,
    });
    return { ...parseResult(result.stdout, result.status), duration_ms: Date.now() - started };
  } finally {
    rmSync(sandbox, { recursive: true, force: true });
  }
}
