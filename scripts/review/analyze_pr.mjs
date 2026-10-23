// PR 1건을 분석해 Notion '현재 작업 상황'에 기록하는 진입점이다(GitHub Actions 또는 로컬 미리보기).
// 순서: PR 수집 → 이전 상태 확인 → 규칙 점검·충돌 계산 → (필요할 때만) Claude 분석 → CI 결과 대기 → 준비 상태 → Notion 기록.
// AI나 Notion이 실패해도 팀원 PR에 실패 표시가 남지 않도록 경고만 남기고 정상 종료한다.
import { appendFileSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { randomBytes } from "node:crypto";
import { fileURLToPath } from "node:url";

import { runClaude } from "./engine.mjs";
import { computeConflict, createGitHub, fetchPull, readCi } from "./github.mjs";
import {
  baselineStatus, computeReadiness, fileSignature, filterBaselineRefs, findSecrets, maskPatch,
  moduleOf, parseMappings, parsePatch, runPrechecks, selectPatches, verifyFindings,
} from "./lib.mjs";
import { createNotion } from "./notion_store.mjs";
import { renderReport } from "./render.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../..");
const env = process.env;
const flag = (value) => value === "1" || value === "true";

const repository = env.GITHUB_REPOSITORY ?? "LG-CNS-RAG-Project1/LG-CNS-RAG-Project";
const prNumber = Number(env.PR_NUMBER);
const dryRun = flag(env.DRY_RUN);
const llmEnabled = flag(env.REVIEW_LLM_ENABLED);
const allowDraft = flag(env.ALLOW_DRAFT);
const force = flag(env.FORCE);
const ciWaitSeconds = Number(env.CI_WAIT_SECONDS ?? 600);
const model = env.REVIEW_MODEL || "opus";
const effort = env.REVIEW_EFFORT || "high";

if (!Number.isSafeInteger(prNumber) || prNumber < 1) throw new Error("PR_NUMBER는 양의 정수여야 합니다.");
if (!dryRun && (!env.NOTION_REVIEW_TOKEN || !env.NOTION_DASHBOARD_PAGE_ID || !env.NOTION_MEMORY_PAGE_ID)) {
  throw new Error("NOTION_REVIEW_TOKEN, NOTION_DASHBOARD_PAGE_ID, NOTION_MEMORY_PAGE_ID가 필요합니다.");
}

const warn = (message) => console.log(env.GITHUB_ACTIONS ? `::warning::${message}` : `경고: ${message}`);
const summary = (line) => env.GITHUB_STEP_SUMMARY && appendFileSync(env.GITHUB_STEP_SUMMARY, `${line}\n`);

const github = createGitHub({ repository, token: env.GITHUB_TOKEN });
const notion = createNotion({
  token: env.NOTION_REVIEW_TOKEN,
  dashboardPageId: env.NOTION_DASHBOARD_PAGE_ID,
  memoryPageId: env.NOTION_MEMORY_PAGE_ID,
  dryRun,
});

const pr = await fetchPull(github, prNumber);
console.log(`PR #${prNumber} (${pr.state}${pr.draft ? ", 초안" : ""}) head ${pr.head.sha.slice(0, 7)}`);

// 닫히거나 병합된 PR은 행 상태만 바꾼다.
if (env.EVENT_ACTION === "closed" || pr.state === "closed") {
  try {
    const count = await notion.markClosed(prNumber, Boolean(pr.merged_at));
    console.log(`행 ${count}개의 상태를 ${pr.merged_at ? "병합" : "닫힘"}으로 바꿨습니다.`);
  } catch (error) {
    warn(`Notion 상태 갱신 실패: ${error.message}`);
  }
  process.exit(0);
}
if (pr.draft && !allowDraft) {
  console.log("초안 PR이라 분석하지 않습니다('Ready for review' 시 분석).");
  process.exit(0);
}

let previous = null;
try {
  previous = await notion.readState(prNumber);
} catch (error) {
  warn(`이전 분석 상태를 읽지 못했습니다(전체 분석으로 진행): ${error.message}`);
}
if (previous?.head === pr.head.sha && !force) {
  console.log("이미 분석한 버전입니다. 건너뜁니다(force로 다시 분석 가능).");
  process.exit(0);
}

// ---------- 수집·점검 ----------
const [files, commits, baseSha] = await Promise.all([github.files(prNumber), github.commits(prNumber), github.branchSha(pr.base.ref)]);
const mergeBase = await github.mergeBase(baseSha, pr.head.sha);
const conflict = computeConflict(ROOT, { prNumber, headSha: pr.head.sha, baseSha, mergeBaseSha: mergeBase });
const architecture = readFileSync(join(ROOT, "docs/architecture.md"), "utf8");
const baseline = readFileSync(join(ROOT, "docs/review-baseline.md"), "utf8");
const mappings = parseMappings(architecture);
const statusMap = baselineStatus(baseline);

const secretHits = files.flatMap((file) => findSecrets(file.filename, parsePatch(file.patch).added));
for (const commit of commits.filter((item) => (item.parents ?? []).length === 1)) {
  const detail = await github.commit(commit.sha);
  for (const file of detail.files ?? []) secretHits.push(...findSecrets(file.filename, parsePatch(file.patch).added, commit.sha.slice(0, 7)));
}
let ci = await readCi(github, pr);
let { checks, comments } = runPrechecks({ pr, files, commits, ci, secretHits, mappings });
const touched = [...new Set(files.map((file) => moduleOf(file.filename, mappings)).filter(Boolean))];
const signatures = Object.fromEntries(files.map((file) => [file.filename, fileSignature(file)]));

// ---------- 분석 방식 ----------
const sameFiles = previous?.output && previous.files &&
  Object.keys(signatures).length === Object.keys(previous.files).length &&
  Object.entries(signatures).every(([path, sig]) => previous.files[path]?.sig === sig);
let mode = sameFiles && !force ? "none" : "full";
const { included, total } = selectPatches(files, mappings);
const excluded = files.filter((file) => !included.includes(file)).map((file) => file.filename);
const coverage = { state: excluded.some((path) => files.find((file) => file.filename === path)?.patch) ? "partial" : "full", excluded, patch_bytes: total };

let llm = { status: "skipped", models: [], usage: null };
let output = null;
const currentSecret = checks.some((check) => check.rule === "AGENTS_5_secrets" && check.status === "fail");
const admins = String(env.REVIEW_ADMINS ?? "").split(/[\s,]+/).filter(Boolean);
const actorAllowed = env.EVENT_NAME !== "workflow_dispatch" || !admins.length || admins.includes(env.TRIGGERING_ACTOR);

if (mode === "none") {
  output = previous.output;
  llm = { status: "reused", models: previous.llm?.models ?? [], usage: null };
  console.log("파일 변경 지문이 지난 분석과 같아 AI를 다시 부르지 않습니다.");
} else if (!llmEnabled || !actorAllowed) {
  mode = "deterministic";
  console.log(llmEnabled ? "수동 실행 권한이 없어 규칙 점검만 합니다." : "REVIEW_LLM_ENABLED가 꺼져 있어 규칙 점검만 합니다.");
} else if (currentSecret) {
  mode = "deterministic";
  console.log("현재 버전에 비밀값으로 보이는 값이 있어 AI 분석을 생략합니다.");
} else {
  const nonce = randomBytes(6).toString("hex");
  const escape = (value) => String(value).replaceAll("untrusted_pr_", "untrusted-pr-");
  const context = [
    "# 이전 분석 메모",
    previous?.output?.digest ? `${previous.output.digest} (검증 안 됨)` : "없음(첫 분석).",
    "",
    "# 프로그램이 확인한 사실",
    `- 자동 검사(ci.yml): ${ci.state} ${JSON.stringify(ci.jobs)}`,
    `- 충돌: ${conflict.state}${conflict.files.length ? ` (${conflict.files.join(", ")})` : ""}`,
    `- 초안 여부: ${pr.draft ? "초안" : "검토 요청됨"}`,
    `- 아키텍처 매핑상 변경 영역: ${touched.join(", ") || "없음"}`,
    ...checks.map((check) => `- ${check.rule}: ${check.status} — ${check.detail}`),
    comments.length ? `- 주석 규칙 후보: ${comments.map((item) => `${item.path}:${item.line} "${item.text}"`).join(" / ")}` : "",
    coverage.state === "partial" ? `- 입력 예산으로 제외한 파일: ${excluded.join(", ")}` : "",
    "",
    `<untrusted_pr_${nonce}>`,
    escape(`제목: ${pr.title}`),
    escape(`작성자: ${pr.user.login} / 브랜치: ${pr.head.ref} → ${pr.base.ref}`),
    "본문:",
    escape(pr.body || "(비어 있음)"),
    "커밋 메시지:",
    ...commits.map((commit) => escape(`- ${String(commit.commit.message).split("\n")[0]}`)),
    "변경 파일:",
    ...files.map((file) => escape(`- ${file.filename} (${file.status} +${file.additions} -${file.deletions})`)),
    "patch:",
    ...included.map((file) => escape(`### ${file.filename}\n${maskPatch(file.patch)}`)),
    `</untrusted_pr_${nonce}>`,
  ].filter((line) => line !== "").join("\n");
  console.log(`Claude 분석: model=${model}, effort=${effort}, 입력 ${Buffer.byteLength(context)}바이트, 범위 ${coverage.state}`);
  const systemPrompt = `${readFileSync(join(HERE, "prompts/system.md"), "utf8")}\n\n# 안내서\n\n${baseline}`;
  const schema = readFileSync(join(HERE, "prompts/schema.json"), "utf8");
  const result = runClaude({ systemPrompt, schema, context, model, effort });
  llm = { status: result.status, error_class: result.error_class, models: result.models, usage: result.usage, duration_ms: result.duration_ms };
  output = result.output;
  if (result.status === "done") console.log(`  완료: ${Math.round(result.duration_ms / 1000)}초, 모델 ${result.models.join(", ")}`);
  else warn(`AI 분석 실패(${result.error_class}, HTTP ${result.api_error_status ?? "-"}). 규칙 점검 결과만 기록합니다.`);
}

// ---------- 검증·CI 대기·준비 상태 ----------
const findings = mode === "none" ? verifyFindings(previous.output?.findings, files, prNumber) : verifyFindings(output?.findings, files, prNumber);
if (output) {
  output.goal_fit.baseline_refs = filterBaselineRefs(output.goal_fit.baseline_refs, statusMap);
  if (!filterBaselineRefs([output.goal_fit.primary_ref], statusMap).length) output.goal_fit.primary_ref = output.goal_fit.baseline_refs[0] ?? "";
}
if (ci.state === "running" || ci.state === "none") {
  console.log(`자동 검사 결과를 최대 ${ciWaitSeconds}초 기다립니다.`);
  ci = await readCi(github, pr, { waitSeconds: ciWaitSeconds });
  ({ checks, comments } = runPrechecks({ pr, files, commits, ci, secretHits, mappings }));
}
const readiness = computeReadiness({ draft: pr.draft, checks, ci, conflict, output, findings, coverage: coverage.state, llmStatus: llm.status, files });

const analysis = {
  analyzer: "pr-analysis-1",
  generated_at: new Date().toISOString(),
  repo: repository,
  pr: {
    number: pr.number, title: pr.title, url: pr.html_url, author: pr.user.login, branch: pr.head.ref,
    base: pr.base.ref, head_sha: pr.head.sha, draft: pr.draft,
  },
  merge_base: mergeBase,
  baseline_draft: [...statusMap.values()].includes("초안"),
  ci, conflict, prechecks: checks, comment_candidates: comments,
  touched_modules: touched, coverage, mode, llm, output, findings, readiness,
  files: files.map((file) => ({ path: file.filename, sig: signatures[file.filename] })),
};
const report = renderReport(analysis, previous?.history ?? []);
if (env.REVIEW_PREVIEW_OUT) writeFileSync(env.REVIEW_PREVIEW_OUT, `${JSON.stringify({ analysis, report }, null, 2)}\n`);

try {
  const result = await notion.publish(prNumber, report);
  console.log(`Notion 기록 완료: ${result.url} (요청 ${result.requests}회, 블록 ${report.block_count}개)`);
  summary(`### PR 분석 (참고용)\n- PR #${prNumber} · 방식 ${mode} · 준비 상태 ${readiness.state} · 확인할 점 ${findings.length}건 · Notion 기록 완료`);
} catch (error) {
  warn(`Notion 기록 실패: ${error.message}${error.code === "restricted_resource" ? " (Notion 블록 한도 초과로 보입니다)" : ""}`);
  summary(`### PR 분석 (참고용)\n- PR #${prNumber} · Notion 기록 실패: ${error.status ?? ""} ${error.code ?? ""}`);
}
