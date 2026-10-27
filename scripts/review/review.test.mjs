import assert from "node:assert/strict";
import { test } from "node:test";

import { createGitHub, fetchArgs } from "./github.mjs";
import {
  computeReadiness, decideMode, finalizeJudgment, fileSignature, findSecrets, keywordsOf, maskPatch, mergeFindings, moduleOf, parseMappings, parsePatch,
  parseTagRules, runPrechecks, sanitizeWords, selectPatches, tagOf, tagsOf, validateReviewOutput, verifyFindings,
} from "./lib.mjs";
import { createNotion, PR_DB_PROPERTIES, repeatable, splitSections, toNotionProperties } from "./notion_store.mjs";
import { aiNote, attemptText, diagramStatusText, judgmentLine, nextActions, renderReport, usageText } from "./render.mjs";
import { LABELS } from "./labels.mjs";
import { buildReviewSchema } from "./review_schema.mjs";

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
  assert.equal(verifyFindings([{ kind: "absence", file: "src/a.py" }], files, 7, { startSeq: 5 })[0].id, "F7-5");
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

test("fetchArgs는 전체 이력 저장소에서는 --depth를 쓰지 않는다", () => {
  assert.ok(!fetchArgs(false, ["abc"]).includes("--depth=1"));
  assert.ok(fetchArgs(true, ["abc"]).includes("--depth=1"));
});

const sampleAnalysis = {
  generated_at: "2026-10-23T01:00:00.000Z", repo: "o/r",
  pr: { number: 10, title: "제목", url: "https://github.com/o/r/pull/10", author: "a", branch: "feature/x", base: "develop", head_sha: "abcdef1234567", draft: false },
  baseline_draft: true,
  ci: { state: "passed", jobs: { "Black format check": "success", Pytest: "success" } },
  conflict: { state: "clean", files: [] },
  prechecks: [{ rule: "AGENTS_5_secrets", status: "ok", detail: "비밀값으로 보이는 값 없음" }],
  tags: ["frontend"], keywords: ["app"], mode: "full",
  scope: { changed: [], excluded: [], no_patch: [], truncated: [], added: 1, closed: 0 },
  coverage: { state: "full", excluded: [] },
  ai: { status: "done", head: "abcdef1234567", at: "2026-10-23T01:00:00.000Z", provider: "openai", model: "gpt-6-luna", response_model: "gpt-6-luna" },
  attempt: { head: "abcdef1234567", status: "done", model: "gpt-6-luna", response_model: "gpt-6-luna" },
  output: {
    summary: { one_line: "요약", what_changed: ["변경"], why: "이유" },
    goal_fit: { rating: "partial", primary_ref: "B-GOAL-3", baseline_refs: ["B-GOAL-3"], claims: [{ text: "주장", basis: "fact", evidence: ["e"] }] },
    module_fit: { rating: "no_role_data", touched_modules: ["frontend"], contract_impact: "none", claims: [] },
    next_actions: [{ owner: "author", action: "할 일" }], reviewer_focus: [{ file: "a.py", why: "이유" }], author_questions: ["질문"], digest: "메모",
  },
  findings: [{ id: "F10-1", severity: "major", category: "docs", file: "README.md", line: 3, title: "제목", evidence: "근거", suggestion: "제안", basis: "fact", confidence: "high", anchor_found: true }],
  readiness: { state: "leader_look", reasons: [{ state: "leader_look", reason: "사유" }], if_not_draft: null },
  judgment: null,
};
const usage = { input: 1200, cached: 300, cache_write: 0, output: 900, reasoning: 400, total: 2100 };

test("renderReport는 화면에 영문 내부 값을 내보내지 않고, 사용량은 캐시·추론을 더하지 않고 괄호로 보여 준다", () => {
  const report = renderReport(sampleAnalysis, [{ at: "2026-10-23T01:00:00.000Z", head: "abcdef1", mode: "full", result: "완료", readiness: "leader_look", model: "gpt-6-luna", usage }]);
  const visible = JSON.stringify(report.blocks);
  for (const raw of ["success", "leader_look", "no_role_data", "partial\"", "major\"", "AGENTS_5_secrets", "Claude"]) {
    assert.ok(!visible.includes(raw), `영문 값 노출: ${raw}`);
  }
  assert.ok(visible.includes("입력 1200(캐시 300) / 출력 900(추론 400) 토큰"));
  assert.ok(visible.includes("AI(OpenAI GPT)"));
  assert.equal(report.properties["준비 상태"], "🟡 리더가 한 번 보기");
  assert.equal(report.properties["AI 모델"], "openai · gpt-6-luna");
  assert.equal(report.properties["저장소"], "o/r");
  assert.equal(report.properties["분석 상태"], "AI 분석 완료");
  assert.match(aiNote(sampleAnalysis), /^✅ AI 분석 완료 · AI 내용 기준 버전 abcdef1 · openai gpt-6-luna/);
  assert.ok(report.block_count > 10);
  assert.equal(usageText(null), "-");
});

test("현재 버전 AI가 실패하면 마지막 성공 버전의 AI 내용임을 밝히고 '분석 상태'를 실패로 둔다", () => {
  const failed = {
    ...sampleAnalysis,
    pr: { ...sampleAnalysis.pr, head_sha: "9999999aaaa" },
    ai: { ...sampleAnalysis.ai, status: "failed", error_class: "rate_limit" },
    attempt: { head: "9999999aaaa", status: "failed", error_class: "rate_limit", retry_after_at: "2026-10-23T02:00:00.000Z" },
  };
  const note = aiNote(failed);
  assert.match(note, /AI 내용 기준 버전 abcdef1/);
  assert.match(note, /^❌ 이번 버전 9999999 AI 분석 실패: 속도 제한\. 아래 AI 내용은 AI 내용 기준 버전 abcdef1/);
  const report = renderReport(failed);
  assert.equal(report.properties["분석 상태"], "AI 분석 실패");
  assert.equal(report.properties["분석한 버전"], "abcdef1");
  assert.equal(report.properties["현재 버전"], "9999999");
  assert.match(report.properties["마지막 시도"], /^9999999 AI 분석 실패: 속도 제한 · 2026-10-23 11:00 KST 이후 다시 실행 가능\(자동 재실행 없음\)$/);
  assert.equal(attemptText({ head: "1234567890", status: "skipped", skip_reason: "no_change" }), "1234567 AI 호출 안 함: 의미 있는 변경 없음");
  const rulesOnly = renderReport({ ...failed, output: null, findings: [], ai: { status: "failed", error_class: "auth", head: null } });
  assert.equal(rulesOnly.properties["분석 상태"], "AI 분석 실패");
  assert.equal(rulesOnly.properties["분석한 버전"], "");
  assert.ok(JSON.stringify(rulesOnly.blocks).includes("❌ AI 분석 실패: 인증 오류(리더 확인 필요). 규칙 점검 결과만 보입니다."));
});

test("일부 범위 분석은 '완료(일부 범위)'로 표시하고 보지 못한 범위를 따로 적는다", () => {
  const partial = { ...sampleAnalysis, ai: { ...sampleAnalysis.ai, status: "partial" }, coverage: { state: "partial", excluded: ["src/big.py"] }, scope: { ...sampleAnalysis.scope, excluded: ["src/big.py"], no_patch: ["a.png"] } };
  const report = renderReport(partial);
  assert.equal(report.properties["분석 상태"], "AI 분석 완료(일부 범위)");
  const visible = JSON.stringify(report.blocks);
  assert.ok(visible.includes("이번 분석에서 보지 못한 범위"));
  assert.ok(visible.includes("입력 예산으로 patch를 넣지 못한 파일: src/big.py"));
  assert.ok(visible.includes("a.png"));
});

test("nextActions는 최대 3개이고 중요 지적을 먼저 넣는다", () => {
  const actions = nextActions(sampleAnalysis);
  assert.ok(actions.length <= 3);
  assert.match(actions[0], /^\[중요\]/);
});

test("toNotionProperties는 쉼표를 뺀 select 값과 날짜를 만들고, 넘긴 열만 쓴다", () => {
  const properties = toNotionProperties("[PR #1] t", { "PR 번호": 1, "준비 상태": "a,b", "마지막 분석": "2026-10-23T00:00:00Z", "태그": ["x"], "키워드": "market, news" });
  assert.equal(properties["준비 상태"].select.name, "a b");
  assert.equal(properties["마지막 분석"].date.start, "2026-10-23T00:00:00Z");
  assert.deepEqual(properties["태그"].multi_select, [{ name: "x" }]);
  assert.equal(properties["키워드"].rich_text[0].text.content, "market, news");
  assert.equal(properties["기록"], undefined);
  assert.ok(toNotionProperties("t", {}, "Name").Name.title);
  assert.deepEqual(Object.keys(toNotionProperties(null, { "상태": "병합" })), ["상태"]);
  for (const name of ["저장소", "현재 버전", "마지막 시도", "AI 모델", "카드 반영"]) assert.ok(PR_DB_PROPERTIES[name].rich_text, name);
});

test("splitSections는 보고서·그림·리더 메모를 나누고, 이전 형식 페이지(그림 없음)도 리더 메모 앞까지만 보고서로 본다", () => {
  const block = (type, content = "") => ({ id: `${type}-${content}`, type, [type]: { rich_text: [{ plain_text: content }] } });
  const page = [
    block("callout", "요약"), block("heading_2", "다음에 할 일"), block("divider"),
    block("heading_2", "서비스 아키텍처 (PR 최초 분석 시점)"), block("code", "flowchart LR"), block("paragraph", "최초 생성: head abc1234"),
    block("divider"), block("heading_2", "리더 메모"), block("paragraph", "사람이 쓴 메모"),
  ];
  const sections = splitSections(page);
  assert.deepEqual(sections.report.map((item) => item.type), ["callout", "heading_2"]);
  assert.equal(sections.diagram.codeText, "flowchart LR");
  assert.equal(sections.diagram.statusText, "최초 생성: head abc1234");
  assert.equal(sections.hasMemo, true);
  const legacy = splitSections([block("callout", "요약"), block("table"), block("divider"), block("heading_2", "리더 메모"), block("paragraph", "")]);
  assert.deepEqual(legacy.report.map((item) => item.type), ["callout", "table"]);
  assert.equal(legacy.diagram, null);
});

test("그림 상태 줄은 첫 줄(최초 생성)을 지키고 이후 수정본이 있으면 최초 구조라고 덧붙인다", () => {
  const first = "최초 생성: head abc1234 · 2026-10-26 17:40 KST";
  assert.equal(diagramStatusText({ firstLine: first, latestHead: "abc1234ffff", firstHead: "abc1234" }), first);
  assert.match(diagramStatusText({ firstLine: first, latestHead: "def5678aaaa", firstHead: "abc1234" }), /^최초 생성: head abc1234 · 2026-10-26 17:40 KST\n이후 수정본\(def5678\)이 있어 이 그림은 PR 최초 분석 시점의 구조입니다/);
});

test("열 추가가 다른 실행과 겹쳐 400이 나면 표 구조를 다시 읽고 한 번 더 맞춘다", async () => {
  let reads = 0;
  let patches = 0;
  const fetchImpl = async (url, init) => {
    const path = url.replace("https://api.notion.com/v1/", "").split("?")[0];
    let status = 200;
    let data = {};
    if (path === "databases/pr-db") data = { id: "pr-db", data_sources: [{ id: "ds" }] };
    else if (path === "data_sources/ds" && init.method === "GET") {
      reads += 1;
      const full = Object.fromEntries(Object.entries(PR_DB_PROPERTIES).map(([name, config]) => [name, { type: Object.keys(config)[0] }]));
      data = { properties: reads === 1 ? { "이름": { type: "title" }, "담당 영역": { type: "multi_select" } } : full };
    } else if (path === "data_sources/ds" && init.method === "PATCH") {
      patches += 1;
      status = 400;
      data = { code: "validation_error", message: "Could not find property" };
    } else if (path === "data_sources/ds/query") data = { results: [] };
    return { ok: status < 400, status, headers: { get: () => null }, json: async () => data };
  };
  const notion = createNotion({ token: "t", repository: "o/r", prDatabaseId: "pr-db", memoryPageId: "memory", delayMs: 0, fetchImpl });
  assert.equal(await notion.markStatus(1, "병합"), 0);
  assert.deepEqual([reads, patches], [2, 1]);
});

test("decideMode는 성공한 분석이 없으면 첫 분석, 강제·버전 변경·계약 파일·대부분 변경이면 전체, 일부만 바뀌면 바뀐 파일만 본다", () => {
  const success = { output: { digest: "d" }, files: { "a.py": { sig: "1" }, "b.py": { sig: "2" }, "c.py": { sig: "3" }, "d.py": { sig: "4" } } };
  const same = { "a.py": "1", "b.py": "2", "c.py": "3", "d.py": "4" };
  assert.deepEqual([decideMode({ success: null, signatures: same }).mode, decideMode({ success: null, signatures: same }).reason], ["full", "first"]);
  assert.equal(decideMode({ success, signatures: same }).mode, "none");
  assert.equal(decideMode({ success, signatures: same, force: true }).reason, "force");
  assert.equal(decideMode({ success, signatures: same, versionChanged: true }).reason, "version");
  const partial = decideMode({ success, signatures: { ...same, "b.py": "x" } });
  assert.deepEqual([partial.mode, partial.changed], ["incremental", ["b.py"]]);
  assert.equal(decideMode({ success, signatures: { ...same, "a.py": "x", "b.py": "x", "c.py": "x" } }).reason, "most_changed");
  const contract = { ...success, files: { ...success.files, "src/schemas.py": { sig: "5" } } };
  assert.equal(decideMode({ success: contract, signatures: { ...same, "src/schemas.py": "x" } }).reason, "contract");
  const dropped = decideMode({ success, signatures: { "a.py": "1", "b.py": "2", "c.py": "3" } });
  assert.deepEqual([dropped.mode, dropped.removed], ["incremental", ["d.py"]]);
});

test("keywordsOf는 파일 이름에서 흔한 단어를 빼고 키워드를 뽑는다", () => {
  assert.deepEqual(keywordsOf(["src/ingestion/market_processor.py", "tests/test_market.py", "src/__init__.py", "requirements.txt", "frontend/app.py"]), ["market", "processor", "app"]);
});

test("finalizeJudgment는 근거 세 문장을 순서대로 남기고, 보완 후 검토·꼭 고칠 점이 있으면 '병합 가능'을 낮추며 이유를 그 사유로 바꾼다", () => {
  const output = { judgment: { verdict: "merge_ok", reason: " 문제 없음 " }, rationale: { result: "가.", causality: " 나. ", basis: "다. 리더 승인 필요" } };
  assert.deepEqual(finalizeJudgment(output, { state: "ready", reasons: [] }), { verdict: "merge_ok", reason: "문제 없음", rationale: ["가.", "나.", "다. 리더 확인 필요"], capped: false });
  const needsFix = finalizeJudgment(output, { state: "needs_fix", reasons: [{ reason: "다른 작업과 충돌" }] });
  assert.deepEqual([needsFix.verdict, needsFix.capped, needsFix.reason], ["fix_then_merge", true, "다른 작업과 충돌 (AI 원래 판단: 병합 가능)"]);
  const blocker = finalizeJudgment(output, { state: "leader_look", reasons: [] }, [{ severity: "blocker" }]);
  assert.deepEqual([blocker.verdict, blocker.reason], ["fix_then_merge", "꼭 고칠 점 1건 (AI 원래 판단: 병합 가능)"]);
  assert.equal(finalizeJudgment({ ...output, judgment: { verdict: "discuss", reason: "r" } }, { state: "needs_fix", reasons: [] }).verdict, "discuss");
  assert.equal(finalizeJudgment(null, { state: "ready" }), null);
  assert.equal(finalizeJudgment({ judgment: { verdict: "approve", reason: "r" } }, { state: "ready" }), null);
  assert.equal(sanitizeWords("승인 대기"), "확인 대기");
});

test("병합 판단은 표 열과 맨 위 상자에 한글 등급·이유·근거 세 문장으로 나오고 영문 값은 보이지 않는다", () => {
  const judgment = { verdict: "fix_then_merge", reason: "테스트 보강 필요", rationale: ["결과 문장.", "인과 문장.", "근거 문장."], capped: true };
  const report = renderReport({ ...sampleAnalysis, judgment });
  assert.equal(report.properties["병합 판단"], "보완 후 병합");
  assert.equal(report.properties["판단 근거"], "보완 후 병합 — 테스트 보강 필요\n• 결과 문장.\n• 인과 문장.\n• 근거 문장.");
  const visible = JSON.stringify(report.blocks);
  assert.ok(visible.includes("병합 판단(AI 참고): "));
  const position = report.blocks.findIndex((item) => item.type === "callout" && JSON.stringify(item).includes("병합 판단(AI 참고)"));
  assert.equal(position, 2, "판단 상자는 읽는 법·요약 상자 바로 다음");
  for (const raw of ["fix_then_merge", "merge_ok", "\"discuss\"", "\"hold\""]) assert.ok(!visible.includes(raw), `영문 값 노출: ${raw}`);
  for (const verdict of Object.keys(LABELS.verdict)) {
    assert.equal(renderReport({ ...sampleAnalysis, judgment: { ...judgment, verdict, capped: false } }).properties["병합 판단"], LABELS.verdict[verdict]);
  }
  const none = renderReport({ ...sampleAnalysis, judgment: null });
  assert.equal(none.properties["병합 판단"], null);
  assert.equal(none.properties["판단 근거"], "AI 판단 없음");
  assert.equal(judgmentLine(null), "AI 판단 없음");
});

test("출력 형식의 병합 판단 등급은 화면 라벨과 일치하고 필수 항목이다", () => {
  const schema = buildReviewSchema(["ingestion"]);
  assert.ok(schema.required.includes("judgment") && schema.required.includes("rationale") && schema.required.includes("candidate_card_delta"));
  assert.deepEqual(schema.properties.judgment.properties.verdict.enum, Object.keys(LABELS.verdict));
  assert.deepEqual(schema.properties.rationale.required, ["result", "causality", "basis"]);
  assert.deepEqual(schema.properties.candidate_card_delta.items.properties.tag.enum, ["ingestion"]);
});

const FILES = [
  { filename: "src/a.py", status: "modified", patch: "@@ -1,1 +1,2 @@\n x = 1\n+def load_items(path: str) -> list:\n" },
  { filename: "b.png", status: "added", patch: undefined },
];

test("validateReviewOutput는 head가 다르면 전체를 버리고, 대상 밖 파일·없는 ID·patch로 확인되지 않는 카드 후보는 항목만 버린다", () => {
  const files = [
    { filename: "src/a.py", status: "modified", patch: "@@ -1,2 +1,2 @@\n x = 1\n-def old_fn(path):\n+def load_items(path: str) -> list:\n" },
    { filename: "README.md", status: "modified", patch: "@@ -1 +1 @@\n-old_doc\n+b\n" },
    { filename: "b.png", status: "added", patch: undefined },
  ];
  const tagOfPath = (path) => (path.startsWith("src/") ? "ingestion" : null);
  const output = {
    head_sha: "abc1234",
    findings: [{ kind: "presence", file: "src/a.py" }, { kind: "presence", file: "src/other.py" }, { kind: "absence", file: "b.png" }],
    reviewer_focus: [{ file: "src/a.py", why: "" }, { file: "x.py", why: "" }],
    prior_findings: [{ id: "F1-1", status: "resolved" }, { id: "F9-9", status: "resolved" }],
    candidate_card_delta: [
      { tag: "ingestion", scope_add: ["  목록  읽기 "], scope_remove: ["지우려는 범위"], contracts_upsert: [
        { key: "load_items", text: "목록을 읽음", evidence_file: "src/a.py", evidence_symbol: "load_items" },
        { key: "ghost", text: "없는 함수", evidence_file: "src/a.py", evidence_symbol: "ghost_fn" },
        { key: "short", text: "짧은 심볼", evidence_file: "src/a.py", evidence_symbol: "+b" },
        { key: "doc", text: "다른 계층 파일 근거", evidence_file: "README.md", evidence_symbol: "old_doc" },
      ], contracts_remove: ["old_fn", "never", "keep_fn"] },
      { tag: "-", scope_add: ["x"], contracts_upsert: [], contracts_remove: [] },
    ],
  };
  const snapshots = { ingestion: { contracts: { old_fn: "t", keep_fn: "u" } } };
  const options = { headSha: "abc1234ffffffff", files, includedPaths: ["src/a.py", "README.md"], priorIds: ["F1-1"], cardTags: ["ingestion"], snapshots, tagOfPath, cards: {} };
  const { fatal, output: clean, dropped } = validateReviewOutput(output, options);
  assert.equal(fatal, null);
  assert.deepEqual(clean.findings.map((item) => item.file), ["src/a.py", "b.png"]);
  assert.deepEqual(clean.reviewer_focus.map((item) => item.file), ["src/a.py"]);
  assert.deepEqual(clean.prior_findings.map((item) => item.id), ["F1-1"]);
  assert.equal(clean.candidate_card_delta.length, 1);
  const [delta] = clean.candidate_card_delta;
  assert.deepEqual(delta.scope_add, ["목록 읽기"]);
  assert.deepEqual(delta.scope_remove, [], "범위 삭제는 모델 후보로 받지 않음");
  assert.deepEqual(delta.contracts_upsert.map((item) => item.key), ["load_items"]);
  assert.deepEqual(delta.contracts_remove, ["old_fn"], "삭제 줄 근거가 있는 key만 지움");
  assert.ok(dropped.length >= 8);
  assert.equal(validateReviewOutput({ ...output, head_sha: "fffffff" }, options).fatal, "head_mismatch");
  assert.equal(validateReviewOutput({ ...output, head_sha: "abc" }, options).fatal, "head_mismatch");
  const readmeOnly = validateReviewOutput({ ...output, candidate_card_delta: [{ tag: "ingestion", scope_add: ["끼워 넣은 범위"], contracts_upsert: [], contracts_remove: ["old_fn"] }] }, { ...options, files: [files[1]], includedPaths: ["README.md"] });
  assert.deepEqual([readmeOnly.output.candidate_card_delta[0].scope_add, readmeOnly.output.candidate_card_delta[0].contracts_remove], [[], []], "README만 바꾼 PR은 카드 범위·계약을 바꾸지 못함");
});

test("mergeFindings는 바뀌지 않은 파일의 지적을 유지하고, 바뀐 파일은 모델 판정에 따라 닫거나 남기며, 빠진 파일의 지적은 닫는다", () => {
  const files = [
    { filename: "src/a.py", patch: "@@ -1 +1,2 @@\n x\n+value = compute_total(items, discount)\n" },
    { filename: "src/b.py", patch: "@@ -1 +1 @@\n+y = 2\n" },
  ];
  const previous = [
    { id: "F1-1", file: "src/b.py", title: "유지", kind: "absence" },
    { id: "F1-2", file: "src/a.py", title: "해결됨", kind: "presence", anchor: "old" },
    { id: "F1-3", file: "src/a.py", title: "남음", kind: "presence", anchor: "value = compute_total(items, discount)", side: "new" },
    { id: "F1-4", file: "src/gone.py", title: "사라짐" },
  ];
  const fresh = [{ id: "F1-5", file: "src/a.py", title: "새 지적" }, { id: "F1-6", file: "src/a.py", title: "남음" }];
  const merged = mergeFindings({ previous, fresh, priorStatuses: [{ id: "F1-2", status: "resolved" }, { id: "F1-3", status: "still_open" }], changed: ["src/a.py"], removed: ["src/gone.py"], files });
  assert.deepEqual(merged.findings.map((item) => item.id), ["F1-1", "F1-3", "F1-5"]);
  assert.equal(merged.findings[1].anchor_found, true);
  assert.deepEqual(merged.closed.map((item) => item.id).sort(), ["F1-2", "F1-4"]);
});

test("태그는 안내서 태그 규칙을 먼저, 없으면 구조도 매핑을 쓰고 설명 문장 속 규칙 표기는 읽지 않는다", () => {
  const rules = parseTagRules("설명: `%% tag 패턴 태그` 형식\n%% tag tests/test_market* ingestion\n%% tag **/*kipris* ingestion\n");
  assert.deepEqual(rules.map((rule) => rule.pattern), ["tests/test_market*", "**/*kipris*"]);
  const mappings = parseMappings("%% map src/ingestion/ ingestion\n%% map src/retrieval/ retrieval\n%% map frontend/ frontend");
  assert.equal(tagOf("tests/test_market.py", mappings, rules), "ingestion");
  assert.equal(tagOf("scripts/kipris_tool.py", mappings, rules), "ingestion");
  assert.equal(tagOf("src/retrieval/market_search.py", mappings, rules), "retrieval");
  assert.equal(tagOf("tests/test_frontend.py", mappings, rules), null);
  assert.deepEqual(tagsOf(["src/ingestion/a.py", "src/ingestion/b.py", "frontend/app.py", "README.md"], mappings, rules), ["ingestion", "frontend"]);
  const deep = parseTagRules("%% tag src/**/*.py python");
  assert.equal(tagOf("src/main.py", [], deep), "python");
  assert.equal(tagOf("src/a/b/c.py", [], deep), "python");
  assert.equal(tagOf("src/a/b/c.md", [], deep), null);
});

test("keywordsOf는 파일 이름에서 흔한 단어를 빼고 키워드를 뽑는다", () => {
  assert.deepEqual(keywordsOf(["src/ingestion/market_processor.py", "tests/test_market.py", "src/__init__.py", "requirements.txt", "frontend/app.py"]), ["market", "processor", "app"]);
});

test("연결 오류(fetch failed)가 나면 GitHub 조회는 다시 보내고, Notion은 반복해도 안전한 요청만 다시 보낸다", async () => {
  const original = globalThis.fetch;
  let githubCalls = 0;
  globalThis.fetch = async () => {
    githubCalls += 1;
    if (githubCalls < 3) throw new TypeError("fetch failed");
    return { ok: true, status: 200, headers: { get: () => null }, json: async () => ({ number: 7 }) };
  };
  try {
    const github = createGitHub({ repository: "o/r", token: "t", retryDelayMs: 0 });
    assert.deepEqual(await github.pull(7), { number: 7 });
    assert.equal(githubCalls, 3);

    const notionCalls = [];
    globalThis.fetch = async (url, init) => {
      notionCalls.push(`${init.method} ${url.split("/v1/")[1]}`);
      throw new TypeError("fetch failed");
    };
    const notion = createNotion({ token: "t", repository: "o/r", prDatabaseId: "pr-db", memoryPageId: "memory", delayMs: 0 });
    await assert.rejects(notion.markStatus(7, "병합"), /fetch failed/);
    assert.equal(notionCalls.filter((call) => call === "GET databases/pr-db").length, 4);
  } finally {
    globalThis.fetch = original;
  }
  assert.ok(repeatable("GET", "databases/x") && repeatable("POST", "data_sources/x/query") && repeatable("PATCH", "pages/x") && repeatable("PATCH", "data_sources/x") && repeatable("PATCH", "blocks/x"));
  assert.ok(!repeatable("POST", "pages") && !repeatable("PATCH", "blocks/x/children") && !repeatable("POST", "databases"));
});

test("상태 JSON이 Notion 한도를 넘으면 기록·출력 원문·지적 세부 순으로 줄이고, 그래도 넘으면 잘린 JSON 대신 오류를 낸다", async () => {
  const { fitState, STATE_CHARS } = await import("./notion_store.mjs");
  const big = {
    history: Array.from({ length: 10 }, () => ({ note: "x".repeat(5_000) })),
    last_successful_analysis: { output: { digest: "y".repeat(185_000) }, files: { "a.py": { sig: "s" } }, findings: [{ id: "F1-1", evidence: "z".repeat(1_000), anchor: "a" }], scope: { sources: ["a"] } },
    card_delta: { items: [{ tag: "t" }] },
  };
  const json = fitState(big);
  assert.ok(json.length <= STATE_CHARS);
  const parsed = JSON.parse(json);
  assert.ok(parsed.last_successful_analysis.output === null, "출력 원문을 먼저 버림");
  assert.equal(parsed.history.length, 3);
  assert.deepEqual(parsed.last_successful_analysis.files, { "a.py": { sig: "s" } });
  assert.deepEqual(parsed.card_delta, big.card_delta);
  assert.throws(() => fitState({ card_delta: { note: "w".repeat(STATE_CHARS + 1) } }), /저장하지 않았습니다/);
});
