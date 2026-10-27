// Codex 설정과 모델 호출 전 기능 점검을 한곳에서 관리한다.
import { spawnSync } from "node:child_process";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";

export const CODEX_VERSION = "0.160.1";
export const DISABLED_FEATURES = [
  "shell_tool", "unified_exec", "unified_exec_tty", "js_repl", "code_mode", "code_mode_host", "code_mode_only",
  "view_image", "multi_agent", "multi_agent_v2", "standalone_web_search", "browser_use", "browser_use_external",
  "browser_use_full_cdp_access", "computer_use", "plugins", "remote_plugin", "plugin_sharing", "tool_search",
  "tool_suggest", "image_generation", "apps", "hooks", "memories", "skill_search", "skill_mcp_dependency_install",
  "in_app_browser", "in_app_local_automation", "request_permissions_tool", "deferred_executor", "worktrees",
  "auth_elicitation", "tool_call_mcp_elicitation", "shell_snapshot", "sleep_tool", "goals", "workspace_dependencies",
  "write_stdin_approval", "in_app_chat", "in_app_dictation", "in_app_updates", "step_model_switching",
  "current_time_reminder", "send_message_to_user_async", "token_budget",
];
export const POLICY_ARGS = ["-c", 'web_search="disabled"', "-c", "tools.update_plan.enabled=false", "-c", "tools.experimental_request_user_input.enabled=false", "-c", "agents.enabled=false", ...DISABLED_FEATURES.flatMap((name) => ["-c", `features.${name}=false`])];
const TOOL_FEATURE = /(?:shell_tool|shell_snapshot|unified_exec|js_repl|code_mode|view_image|multi_agent|web_search|browser_use|computer_use|plugins|remote_plugin|plugin_sharing|tool_search|tool_suggest|image_generation|^apps$|^hooks$|^memories$|skill_search|skill_mcp|in_app_|request_permissions_tool|deferred_executor|^worktrees$|auth_elicitation|tool_call_mcp_elicitation|sleep_tool|^goals$|workspace_dependencies|write_stdin_approval|step_model_switching|current_time_reminder|send_message_to_user_async|token_budget)/;

export function inspectFeatures(output) {
  const found = new Map();
  for (const line of String(output).trim().split("\n")) {
    const match = /^(\S+)\s{2,}(under development|experimental|stable|removed|deprecated)\s+(true|false)$/.exec(line.trim());
    if (!match || found.has(match[1])) throw new Error("Codex 기능 목록 형식을 확인할 수 없습니다.");
    found.set(match[1], { stage: match[2], enabled: match[3] === "true" });
  }
  for (const name of DISABLED_FEATURES) if (!found.has(name)) throw new Error(`Codex 기능이 누락되었습니다: ${name}`);
  for (const [name, info] of found) {
    if (TOOL_FEATURE.test(name) && info.stage !== "removed" && info.enabled) throw new Error(`Codex 도구 기능이 켜져 있습니다: ${name}`);
  }
}

export function checkCodexPolicy({ bin = "codex", path = process.env.PATH ?? "", spawnImpl = spawnSync } = {}) {
  const dir = mkdtempSync(join(tmpdir(), "pr-review-policy-"));
  try {
    const env = { PATH: path, HOME: dir, CODEX_HOME: dir, LANG: "en_US.UTF-8" };
    const version = spawnImpl(bin, ["--version"], { env, cwd: dir, encoding: "utf8", timeout: 20_000 });
    if (version.status !== 0 || version.stdout?.trim() !== `codex-cli ${CODEX_VERSION}`) throw new Error("Codex CLI 버전을 확인할 수 없습니다.");
    const features = spawnImpl(bin, ["features", "list", ...POLICY_ARGS], { env, cwd: dir, encoding: "utf8", timeout: 20_000 });
    if (features.status !== 0) throw new Error("Codex 기능 목록을 읽을 수 없습니다.");
    inspectFeatures(features.stdout);
    // 0.160.1은 모델 메타데이터에 따라 apply_patch를 등록한다. features list는 실제 도구 목록을 증명하지 못한다.
    throw new Error("Codex 실제 도구 노출을 검증할 수 없어 모델 호출을 차단합니다.");
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  try { checkCodexPolicy(); } catch (error) { console.error(error.message); process.exitCode = 1; }
}
