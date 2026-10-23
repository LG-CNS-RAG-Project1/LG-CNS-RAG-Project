import assert from "node:assert/strict";
import { test } from "node:test";

import { buildArgs, buildEnv, parseResult } from "./engine.mjs";
import { fetchArgs } from "./github.mjs";
import {
  computeReadiness, fileSignature, findSecrets, maskPatch, moduleOf, parseMappings, parsePatch,
  runPrechecks, selectPatches, verifyFindings,
} from "./lib.mjs";
import { toNotionProperties } from "./notion_store.mjs";
import { nextActions, renderReport } from "./render.mjs";

// 비밀값 스캐너가 테스트용 가짜 값을 실제 키로 오인하지 않도록 실행 시 문자열을 합친다.
const FAKE_OPENAI = ["sk", "proj-abcdEFGH1234567890xyz"].join("-");

const PATCH = "@@ -1,2 +1,3 @@\n context\n-old line here\n+new line number one here\n+second added line\n";

test("parsePatch는 추가·삭제 줄에 줄 번호를 붙인다", () => {
  const { added, removed } = parsePatch(PATCH);
  assert.deepEqual(removed, [{ line: 2, text: "old line here" }]);
  assert.deepEqual(added.map((item) => item.line), [2, 3]);
});

test("fileSignature는 hunk 위치가 바뀌어도 같다", () => {
  const moved = PATCH.replace("@@ -1,2 +1,3 @@", "@@ -10,2 +10,3 @@");
  assert.equal(fileSignature({ status: "modified", patch: PATCH }), fileSignature({ status: "modified", patch: moved }));
});

test("findSecrets는 실제 키를 잡고 위젯 key·테스트 값·자리표시자는 무시한다", () => {
  const cases = [
    ["src/a.py", `OPENAI_API_KEY = "${FAKE_OPENAI}"`, true],
    ["src/a.py", 'api_key = "A1b2C3d4E5f6G7h8"', true],
    [".env.example", "DART_API_KEY=3f9c2a7b1e4d8f60a5c2b9e7d1f3a4c6b8e0d2f4", true],
    ["src/n.py", 'headers = {"X-NCP-APIGW-API-KEY": "aB3dE5gH7jK9"}', true],
    ["frontend/app.py", 'st.text_input("기업", key="company_a", max_chars=80)', false],
    ["src/a.py", 'password = os.getenv("DB_PASSWORD")', false],
    ["tests/test_x.py", '{"KIPRIS_API_KEY": "test-key"}', false],
    [".env.example", "NAVER_CLIENT_ID=", false],
    ["src/a.py", 'token = "your_token_here"', false],
  ];
  for (const [path, line, expected] of cases) {
    assert.equal(findSecrets(path, [{ line: 1, text: line }]).length > 0, expected, `${path}: ${line}`);
  }
  const [hit] = findSecrets("src/a.py", [{ line: 3, text: 'api_key = "A1b2C3d4E5f6G7h8"' }]);
  assert.match(hit.masked, /^\*\*\*\*\(16자, [0-9a-f]{8}\)$/);
  assert.ok(!JSON.stringify(hit).includes("A1b2C3d4E5f6G7h8"));
});

test("maskPatch는 patch 속 비밀값을 가린다", () => {
  const masked = maskPatch(`+OPENAI_API_KEY = "${FAKE_OPENAI}"`);
  assert.ok(!masked.includes(FAKE_OPENAI));
});

test("moduleOf는 가장 긴 접두사 매핑을 고른다", () => {
  const mappings = parseMappings("%% map src/ app\n%% map src/schemas.py pipeline\n%% map frontend/ frontend");
  assert.equal(moduleOf("src/schemas.py", mappings), "pipeline");
  assert.equal(moduleOf("src/ingestion/a.py", mappings), "app");
  assert.equal(moduleOf("README.md", mappings), null);
});

const basePr = {
  body: "## 변경 요약\n- a\n## 변경 유형\n- [x] 기능 추가\n## 주요 변경 내용\n- b\n## 검증 방법\n- [x] `pytest` 통과\n## 체크리스트\n- [x] develop",
  base: { ref: "develop" }, head: { ref: "feature/sample" }, user: { login: "author" },
};
const passedCi = { state: "passed", jobs: { Pytest: "success" } };

test("runPrechecks는 양식·체크 모순·브랜치·커밋 규칙을 점검한다", () => {
  const files = [{ filename: "src/a.py", status: "modified", additions: 3, deletions: 1, patch: PATCH }];
  const commits = [{ parents: [{}], author: { login: "author" }, commit: { message: "feat: add thing" } }];
  const failedCi = { state: "failed", jobs: { Pytest: "failure" } };
  const { checks } = runPrechecks({ pr: basePr, files, commits, ci: failedCi, secretHits: [], mappings: [] });
  const byRule = Object.fromEntries(checks.map((check) => [check.rule, check.status]));
  assert.equal(byRule.template, "ok");
  assert.equal(byRule.check_mismatch, "warn");
  assert.equal(byRule.branch_name, "ok");
  assert.equal(byRule.AGENTS_8_commits, "warn");
  assert.equal(byRule.AGENTS_5_secrets, "ok");
});

test("verifyFindings는 20자 이상·한 곳만 맞는 앵커만 위치 확인으로 본다", () => {
  const files = [{ filename: "src/a.py", patch: PATCH }];
  const [found, short, outside] = verifyFindings([
    { kind: "presence", file: "src/a.py", anchor: "new line number one here", side: "new", severity: "major" },
    { kind: "presence", file: "src/a.py", anchor: "second", side: "new", severity: "minor" },
    { kind: "presence", file: "other.py", anchor: "anything at all here ok", side: "new", severity: "minor" },
  ], files, 7);
  assert.equal(found.anchor_found, true);
  assert.equal(found.line, 2);
  assert.equal(found.id, "F7-1");
  assert.equal(short.anchor_found, false);
  assert.equal(outside, undefined);
});

test("computeReadiness는 보안·충돌을 AI 지적보다 먼저 보고, AI 지적만으로는 보완 후 검토가 되지 않는다", () => {
  const common = { draft: false, ci: passedCi, conflict: { state: "clean", files: [] }, output: null, coverage: "full", llmStatus: "done", files: [] };
  const major = [{ severity: "major" }];
  assert.equal(computeReadiness({ ...common, checks: [], findings: major }).state, "leader_look");
  const secret = [{ rule: "AGENTS_5_secrets", status: "fail" }];
  assert.equal(computeReadiness({ ...common, checks: secret, findings: major }).state, "needs_fix");
  assert.equal(computeReadiness({ ...common, checks: [], findings: [] }).state, "ready");
  assert.equal(computeReadiness({ ...common, conflict: { state: "conflict", files: ["a"] }, checks: [], findings: [] }).state, "needs_fix");
  const draft = computeReadiness({ ...common, draft: true, checks: [], findings: [] });
  assert.equal(draft.state, "draft");
  assert.equal(draft.if_not_draft[0].state, "ready");
});

test("selectPatches는 40KB를 넘으면 src를 우선해 예산 안에서 고른다", () => {
  const big = "x".repeat(30_000);
  const files = [
    { filename: "docs/a.md", patch: big },
    { filename: "src/a.py", patch: big },
    { filename: "tests/t.py", patch: big },
  ];
  const { included } = selectPatches(files, [], { small: 40_000, max: 70_000 });
  assert.deepEqual(included.map((file) => file.filename), ["src/a.py", "tests/t.py"]);
});

test("엔진은 도구를 끄고, 출입증이 있으면 허용 목록 환경변수만 넘긴다", () => {
  const args = buildArgs({ schema: "{}", systemFile: "/tmp/s.md", model: "opus", effort: "high" });
  assert.ok(!args.includes("--bare"));
  assert.equal(args[args.indexOf("--tools") + 1], "");
  const env = buildEnv({ PATH: "/bin", CLAUDE_CODE_OAUTH_TOKEN: "t", GITHUB_TOKEN: "g", NOTION_REVIEW_TOKEN: "n", ANTHROPIC_API_KEY: "a" }, "/tmp/x");
  assert.deepEqual(Object.keys(env).sort(), ["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC", "CLAUDE_CODE_MAX_RETRIES", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CONFIG_DIR", "HOME", "LANG", "PATH"]);
  const local = buildEnv({ PATH: "/bin", HOME: "/h", GITHUB_TOKEN: "g", ANTHROPIC_API_KEY: "a" }, "/tmp/x");
  assert.equal(local.GITHUB_TOKEN, undefined);
  assert.equal(local.ANTHROPIC_API_KEY, undefined);
});

test("fetchArgs는 전체 이력 저장소에서는 --depth를 쓰지 않는다", () => {
  assert.ok(!fetchArgs(false, ["abc"]).includes("--depth=1"));
  assert.ok(fetchArgs(true, ["abc"]).includes("--depth=1"));
});

test("parseResult는 subtype이 success여도 is_error면 실패로, 401은 auth로 분류한다", () => {
  const failed = parseResult(JSON.stringify({ subtype: "success", is_error: true, api_error_status: 401, terminal_reason: "api_error" }), 1);
  assert.equal(failed.status, "failed");
  assert.equal(failed.error_class, "auth");
  const ok = parseResult(JSON.stringify({ subtype: "success", is_error: false, structured_output: { a: 1 }, modelUsage: { m: {} } }), 0);
  assert.equal(ok.status, "done");
  assert.deepEqual(ok.output, { a: 1 });
});

const sampleAnalysis = {
  analyzer: "test", generated_at: "2026-10-23T01:00:00.000Z", repo: "o/r",
  pr: { number: 10, title: "제목", url: "https://github.com/o/r/pull/10", author: "a", branch: "feature/x", base: "develop", head_sha: "abcdef1234567", draft: false },
  merge_base: "m", baseline_draft: true,
  ci: { state: "passed", jobs: { "Black format check": "success", Pytest: "success" } },
  conflict: { state: "clean", files: [] },
  prechecks: [{ rule: "AGENTS_5_secrets", status: "ok", detail: "비밀값으로 보이는 값 없음" }],
  touched_modules: ["frontend"], coverage: { state: "full", excluded: [] }, mode: "full",
  llm: { status: "done", models: ["claude-opus-5-5"], usage: { input: 2, output: 10, cache_read: 5, cache_write: 100 } },
  output: {
    summary: { one_line: "요약", what_changed: ["변경"], why: "이유" },
    goal_fit: { rating: "partial", primary_ref: "B-GOAL-3", baseline_refs: ["B-GOAL-3"], claims: [{ text: "주장", basis: "fact", evidence: ["e"] }] },
    module_fit: { rating: "no_role_data", touched_modules: ["frontend"], contract_impact: "none", claims: [] },
    next_actions: [{ owner: "author", action: "할 일" }], reviewer_focus: [{ file: "a.py", why: "이유" }], author_questions: ["질문"], digest: "메모",
  },
  findings: [{ id: "F10-1", severity: "major", category: "docs", file: "README.md", line: 3, title: "제목", evidence: "근거", suggestion: "제안", basis: "fact", confidence: "high", anchor_found: true }],
  readiness: { state: "leader_look", reasons: [{ state: "leader_look", reason: "사유" }], if_not_draft: null },
  files: [{ path: "a.py", sig: "s" }],
};

test("renderReport는 화면에 영문 내부 값을 내보내지 않고 토큰 합계를 표시한다", () => {
  const report = renderReport(sampleAnalysis);
  const visible = JSON.stringify(report.blocks);
  for (const raw of ["success", "leader_look", "no_role_data", "partial\"", "major\"", "AGENTS_5_secrets"]) {
    assert.ok(!visible.includes(raw), `영문 값 노출: ${raw}`);
  }
  assert.ok(visible.includes("입력 107토큰"));
  assert.equal(report.properties["준비 상태"], "🟡 리더가 한 번 보기");
  assert.equal(report.state.seq, 1);
  assert.ok(report.block_count > 10);
});

test("nextActions는 최대 3개이고 중요 지적을 먼저 넣는다", () => {
  const actions = nextActions(sampleAnalysis);
  assert.ok(actions.length <= 3);
  assert.match(actions[0], /^\[중요\]/);
});

test("toNotionProperties는 쉼표를 뺀 select 값과 날짜를 만든다", () => {
  const properties = toNotionProperties("[PR #1] t", { "PR 번호": 1, "준비 상태": "a,b", "마지막 분석": "2026-10-23T00:00:00Z", "담당 영역": ["x"] });
  assert.equal(properties["준비 상태"].select.name, "a b");
  assert.equal(properties["마지막 분석"].date.start, "2026-10-23T00:00:00Z");
  assert.deepEqual(properties["담당 영역"].multi_select, [{ name: "x" }]);
});
