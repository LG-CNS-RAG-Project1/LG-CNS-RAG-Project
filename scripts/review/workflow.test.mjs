// 운영 경로 점검: 워크플로 구조(신뢰된 develop 스크립트만 실행·초안 제외·키 전달 범위·카드 직렬화)와 Claude 호출 경로가 없는지 확인한다.
import assert from "node:assert/strict";
import { readdirSync, readFileSync, mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { spawnSync } from "node:child_process";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { fileURLToPath } from "node:url";
import { test } from "node:test";
import { logLine, warningLine } from "./logging.mjs";

const ROOT = new URL("../../", import.meta.url);
const read = (path) => readFileSync(new URL(path, ROOT), "utf8");
const workflow = read(".github/workflows/pr-analysis.yml");
const jobs = Object.fromEntries(workflow.split(/\n  (?=[a-z-]+:\n)/).slice(1).map((chunk) => [chunk.split(":")[0], chunk]));

test("PR 값의 줄바꿈과 워크플로 명령을 로그에서 무력화한다", () => {
  const hostile = "src/demo\n::warning::fake\r::add-mask::value";
  const logged = logLine(hostile);
  assert.equal(logged.split("\n").length, 1);
  assert.ok(logged.startsWith("PR_ANALYSIS "));
  const warning = warningLine(`실패 ${hostile}%0A`, true);
  assert.equal(warning.split("\n").length, 1);
  assert.ok(warning.startsWith("::warning::"));
  assert.ok(warning.includes("%250A"));
});

test("운영 경로(워크플로·자동화 스크립트·Makefile)에 Claude CLI·Anthropic 호출·Claude 인증 참조가 없다", () => {
  const operational = [
    ...readdirSync(new URL(".github/workflows/", ROOT)).map((name) => `.github/workflows/${name}`),
    ...readdirSync(new URL("scripts/review/", ROOT)).filter((name) => name.endsWith(".mjs") && !name.endsWith(".test.mjs") && name !== "fakes.mjs").map((name) => `scripts/review/${name}`),
    ...readdirSync(new URL("scripts/review/prompts/", ROOT)).map((name) => `scripts/review/prompts/${name}`),
    ...readdirSync(new URL("scripts/notion/", ROOT)).filter((name) => !name.endsWith(".test.mjs")).map((name) => `scripts/notion/${name}`),
    "Makefile",
  ];
  for (const path of operational) {
    const text = read(path);
    for (const pattern of [/claude/i, /anthropic/i, /CLAUDE_CODE/]) assert.ok(!pattern.test(text), `${path}: ${pattern}`);
  }
  assert.deepEqual(workflow.match(/npm install -g .*/g), ['npm install -g "@openai/codex@${CODEX_VERSION}"'], "설치하는 CLI는 Codex 하나");
});

test("pull_request_target 잡은 모두 develop 스크립트만 받고 자격 증명을 남기지 않는다", () => {
  assert.match(workflow, /pull_request_target:/);
  for (const name of ["analyze", "cards", "notion-check"]) {
    assert.match(jobs[name], /ref: develop/, name);
    assert.match(jobs[name], /persist-credentials: false/, name);
    assert.match(jobs[name], /name: pr-analysis\n\s+deployment: false/, name);
  }
  assert.ok(!/github\.event\.pull_request\.head\.(sha|ref)/.test(workflow.replace(/head\.repo\.full_name/g, "")), "PR head를 checkout하지 않음");
});

test("초안 PR은 잡 단계에서 제외하고, 닫힘·초안 전환·카드·Notion 점검에는 모델 인증 정보를 넘기지 않는다", () => {
  const NEED = "github.event.action != 'closed' && github.event.action != 'converted_to_draft'";
  assert.match(jobs.analyze, /github\.event\.pull_request\.draft != true \|\| github\.event\.action == 'closed' \|\| github\.event\.action == 'converted_to_draft'/);
  const lines = (name) => workflow.split("\n").filter((line) => line.includes(name));
  assert.equal(lines("OPENAI_API_KEY").length, 1);
  assert.ok(lines("OPENAI_API_KEY")[0].includes(`vars.REVIEW_PROVIDER == 'openai' && ${NEED} && secrets.OPENAI_API_KEY`));
  assert.equal(lines("secrets.CODEX_AUTH_JSON").length, 1, "로그인 정보는 복원 단계에서만 읽음");
  assert.equal(lines("secrets.CODEX_AUTH_WRITE_TOKEN").length, 2, "쓰기 권한 확인과 되저장에만 사용");
  const step = (title) => jobs.analyze.split("      - ").find((chunk) => chunk.startsWith(`name: ${title}`)) ?? "";
  for (const title of ["Install pinned Codex CLI", "Check Codex tool isolation"]) {
    assert.ok(step(title).includes(`if: vars.REVIEW_PROVIDER != 'openai' && (vars.REVIEW_LLM_ENABLED == 'true' || inputs.task == 'verify-model') && ${NEED}`), title);
  }
  assert.match(step("Check Codex secret write access"), /steps\.codex_policy\.outcome == 'success'/);
  assert.match(step("Restore Codex ChatGPT sign-in"), /steps\.codex_pat\.outcome == 'success'/);
  assert.match(step("Restore Codex ChatGPT sign-in"), /umask 077/);
  assert.ok(!/echo "\$CODEX_AUTH_JSON"|cat .*auth\.json/.test(workflow), "로그인 정보를 출력하지 않음");
  const save = step("Save refreshed Codex sign-in");
  assert.match(save, /if: always\(\) && steps\.codex_auth\.outputs\.home != ''/);
  assert.match(save, /gh secret set CODEX_AUTH_JSON --env pr-analysis/);
  assert.match(save, /continue-on-error: true/);
  assert.match(save, /mask_codex_auth\.mjs "\$F" validate/);
  assert.match(save, /jq -e/);
  assert.match(step("Remove temporary Codex sign-in"), /if: always\(\)/);
  for (const name of ["cards", "notion-check"]) assert.ok(!/OPENAI_API_KEY|CODEX_AUTH|CODEX_HOME/.test(jobs[name]), name);
  assert.match(jobs.analyze, /NOTION_REVIEW_TOKEN: \$\{\{ inputs\.task != 'verify-model' && secrets\.NOTION_REVIEW_TOKEN \|\| '' \}\}/);
  assert.match(jobs.analyze, /DRY_RUN: \$\{\{ inputs\.task == 'verify-model' && '1' \|\| '' \}\}/);
});

test("Codex CLI 버전은 코드의 고정 버전과 같고, 모델 호출 잡은 저장소 전체에서 한 줄로 실행한다", () => {
  const engine = read("scripts/review/codex_policy.mjs");
  const pinned = /CODEX_VERSION = "([\d.]+)"/.exec(engine)[1];
  assert.ok(jobs.analyze.includes(`CODEX_VERSION: "${pinned}"`));
  assert.match(jobs.analyze, /pr-analysis-model.*pr-analysis-status-/);
  assert.match(jobs.analyze, /cancel-in-progress: false\n\s+queue: max/);
});

test("같은 PR 실행은 차례로, 카드 반영은 저장소 전체에서 한 줄로 세워 처리한다", () => {
  assert.ok(workflow.includes("group: pr-analysis-${{ inputs.task == 'verify-model' && 'verify-' || '' }}${{ github.event.pull_request.number || inputs.pr_number || 'notion-check' }}\n  cancel-in-progress: false\n  queue: max"));
  assert.match(jobs.cards, /group: pr-analysis-cards\n\s+cancel-in-progress: false\n\s+queue: max/);
  assert.match(jobs.cards, /needs: analyze/);
  assert.match(jobs.cards, /REVIEW_STEP: cards/);
});

test("갱신된 로그인 저장은 유효성·저장 실패를 처리하고 별도 단계가 파일을 지운다", () => {
  const dir = mkdtempSync(join(tmpdir(), "workflow-auth-test-"));
  try {
    const home = join(dir, "codex-home"), bin = join(dir, "bin"), file = join(home, "auth.json");
    mkdirSync(home); mkdirSync(bin);
    writeFileSync(join(bin, "gh"), '#!/bin/sh\ncat >/dev/null\nprintf called > "$TEST_MARKER"\nexit "${TEST_GH_EXIT:-0}"\n', { mode: 0o755 });
    const step = (title) => jobs.analyze.split("      - ").find((chunk) => chunk.startsWith(`name: ${title}`));
    const script = step("Save refreshed Codex sign-in").split("        run: |\n")[1].split("\n").map((line) => line.replace(/^          /, "")).join("\n");
    const env = { ...process.env, PATH: `${bin}:${process.env.PATH}`, CODEX_HOME_DIR: home, RUNNER_TEMP: dir, GH_TOKEN: "example", TEST_MARKER: join(dir, "called"), GITHUB_REPOSITORY: "owner/repo" };
    const cwd = fileURLToPath(ROOT);
    const run = (value, exit = "0") => {
      writeFileSync(file, value); writeFileSync(join(dir, "codex-auth.sha256"), "old-hash\n");
      return spawnSync("bash", ["-e", "-c", script], { cwd, env: { ...env, TEST_GH_EXIT: exit }, encoding: "utf8" });
    };
    const invalid = run('{"tokens":');
    assert.notEqual(invalid.status, 0);
    assert.match(invalid.stdout, /저장하지 않았습니다/);
    const token = "synthetic-token-for-test";
    const failed = run(JSON.stringify({ tokens: { refresh_token: token } }), "1");
    assert.notEqual(failed.status, 0);
    assert.match(failed.stdout, /저장하지 못했습니다/);
    assert.ok(failed.stdout.includes(`::add-mask::${token}`));
    const success = run(JSON.stringify({ tokens: { refresh_token: token } }));
    assert.equal(success.status, 0);
    assert.match(success.stdout, /다시 저장했습니다/);
    const cleanup = step("Remove temporary Codex sign-in").split("        run: ")[1].split("\n")[0];
    assert.equal(spawnSync("bash", ["-e", "-c", cleanup], { cwd, env }).status, 0);
    assert.throws(() => readFileSync(file));
  } finally { rmSync(dir, { recursive: true, force: true }); }
});

test("로그인 등록 스크립트는 선택한 기기 코드 방식을 쓰고 지정 저장소에만 저장한다", () => {
  const dir = mkdtempSync(join(tmpdir(), "seed-auth-test-"));
  try {
    const bin = join(dir, "bin"), temp = join(dir, "tmp");
    mkdirSync(bin); mkdirSync(temp);
    writeFileSync(join(bin, "codex"), '#!/bin/sh\nif [ "$2" = status ]; then echo "Logged in using ChatGPT"; else printf "%s\\n" "$*" > "$TEST_CODEX_ARGS"; printf "{}" > "$CODEX_HOME/auth.json"; fi\n', { mode: 0o755 });
    writeFileSync(join(bin, "gh"), '#!/bin/sh\nprintf "%s\\n" "$*" > "$TEST_GH_ARGS"\ncat >/dev/null\n', { mode: 0o755 });
    const env = { ...process.env, PATH: `${bin}:${process.env.PATH}`, TMPDIR: temp, REVIEW_CODEX_DEVICE_AUTH: "true", TEST_CODEX_ARGS: join(dir, "codex-args"), TEST_GH_ARGS: join(dir, "gh-args") };
    delete env.GITHUB_REPOSITORY;
    const result = spawnSync("bash", ["scripts/review/seed_codex_auth.sh"], { cwd: fileURLToPath(ROOT), env, encoding: "utf8" });
    assert.equal(result.status, 0, result.stderr);
    assert.equal(readFileSync(env.TEST_CODEX_ARGS, "utf8").trim(), "login --device-auth");
    assert.match(readFileSync(env.TEST_GH_ARGS, "utf8"), /--repo LG-CNS-RAG-Project1\/LG-CNS-RAG-Project/);
    assert.deepEqual(readdirSync(temp), []);
  } finally { rmSync(dir, { recursive: true, force: true }); }
});
