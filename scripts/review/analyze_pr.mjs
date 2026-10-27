// PR 분석 자동화의 진입점이다(GitHub Actions 또는 로컬 미리보기).
// 환경변수로 설정을 읽어 GitHub·Notion·분석기·git 연결을 만들고 pipeline.mjs에 넘긴다.
// 분석기는 REVIEW_PROVIDER로 하나만 고른다: codex(기본, Codex CLI + ChatGPT 구독 로그인 CODEX_HOME) 또는 openai(OpenAI API 키).
// 고른 분석기의 인증 정보가 없으면 모델을 부르지 않고, 다른 분석기로 넘어가지 않는다.
// REVIEW_STEP=cards이면 분석 대신 병합된 PR의 검증된 카드 변경을 영역 카드에 반영한다(모델 호출 없음).
// AI나 Notion이 실패해도 팀원 PR에 실패 표시가 남지 않도록 경고만 남기고 정상 종료한다.
import { appendFileSync, existsSync, readFileSync, writeFileSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { DEFAULT_INPUT_BUDGET } from "./context.mjs";
import { createGitHub, createRepoReader } from "./github.mjs";
import { createNotion } from "./notion_store.mjs";
import { createCodexReviewer } from "./codex_engine.mjs";
import { createOpenAIReviewer, REASONING_EFFORTS } from "./openai_engine.mjs";
import { runPr, selectReviewer, verificationSucceeded } from "./pipeline.mjs";
import { logLine, warningLine } from "./logging.mjs";

const HERE = dirname(fileURLToPath(import.meta.url));
const ROOT = resolve(HERE, "../..");
const env = process.env;
const flag = (value) => value === "1" || value === "true";
const positive = (value, fallback) => (Number.isSafeInteger(Number(value)) && Number(value) > 0 ? Number(value) : fallback);
const effortOf = (value, fallback) => (REASONING_EFFORTS.includes(value) ? value : fallback);

const repository = env.GITHUB_REPOSITORY ?? "LG-CNS-RAG-Project1/LG-CNS-RAG-Project";
const prNumber = Number(env.PR_NUMBER);
const dryRun = flag(env.DRY_RUN);
const verifyModel = flag(env.REVIEW_VERIFY_MODEL);
const step = env.REVIEW_STEP === "cards" ? "cards" : "analyze";

const warn = (message) => console.log(warningLine(message, Boolean(env.GITHUB_ACTIONS)));
const summary = (line) => env.GITHUB_STEP_SUMMARY && appendFileSync(env.GITHUB_STEP_SUMMARY, `${line}\n`);

// 처리하지 못한 오류(네트워크 오류 등)도 팀원 PR에 실패 표시를 남기지 않도록 경고로 바꾸고 정상 종료한다.
const stop = (error) => {
  warn(`PR 분석을 마치지 못했습니다: ${error?.message ?? error}`);
  summary(`### PR 분석 (참고용)\n- PR #${prNumber} · 분석 중단: ${error?.message ?? error}`);
  process.exit(verifyModel ? 1 : 0);
};
process.on("uncaughtException", stop);

if (!Number.isSafeInteger(prNumber) || prNumber < 1) throw new Error("PR_NUMBER는 양의 정수여야 합니다.");
if (verifyModel && !dryRun) throw new Error("모델 확인은 DRY_RUN에서만 실행할 수 있습니다.");
if (!dryRun && (!env.NOTION_REVIEW_TOKEN || !env.NOTION_MEMORY_PAGE_ID || !(env.NOTION_PR_DATABASE_ID || env.NOTION_DASHBOARD_PAGE_ID))) {
  throw new Error("NOTION_REVIEW_TOKEN, NOTION_MEMORY_PAGE_ID와 NOTION_PR_DATABASE_ID(또는 NOTION_DASHBOARD_PAGE_ID)가 필요합니다.");
}

const admins = String(env.REVIEW_ADMINS ?? "").split(/[\s,]+/).filter(Boolean);
const config = {
  repository,
  prNumber,
  eventName: env.EVENT_NAME ?? "",
  eventAction: env.EVENT_ACTION ?? "",
  step,
  force: flag(env.FORCE) || verifyModel,
  dryRun,
  verifyModel,
  llmEnabled: flag(env.REVIEW_LLM_ENABLED),
  provider: env.REVIEW_PROVIDER || "codex",
  model: env.REVIEW_MODEL || "gpt-6-sol",
  effort: { full: effortOf(env.REVIEW_EFFORT_FULL, "medium"), incremental: effortOf(env.REVIEW_EFFORT_INCREMENTAL, "low") },
  maxOutputTokens: { full: positive(env.REVIEW_MAX_OUTPUT_TOKENS_FULL, 32_000), incremental: positive(env.REVIEW_MAX_OUTPUT_TOKENS_INCREMENTAL, 25_000) },
  inputBudget: positive(env.REVIEW_INPUT_BUDGET_BYTES, DEFAULT_INPUT_BUDGET),
  ciWaitSeconds: Number(env.CI_WAIT_SECONDS ?? 600),
  actorAllowed: env.EVENT_NAME !== "workflow_dispatch" || !admins.length || admins.includes(env.TRIGGERING_ACTOR),
};

// 카드 단계에는 분석기를 만들지 않는다. 워크플로는 상태만 바꾸는 이벤트에 인증 정보를 넘기지 않는다.
const reviewer = selectReviewer({
  step, provider: config.provider, env,
  factories: { codex: (codexHome) => createCodexReviewer({ codexHome }), openai: (apiKey) => createOpenAIReviewer({ apiKey }) },
  hasCodexLogin: (codexHome) => existsSync(join(codexHome, "auth.json")),
});

try {
  const result = await runPr({
    config,
    github: createGitHub({ repository, token: env.GITHUB_TOKEN }),
    notion: createNotion({
      token: env.NOTION_REVIEW_TOKEN,
      repository,
      dashboardPageId: env.NOTION_DASHBOARD_PAGE_ID,
      prDatabaseId: env.NOTION_PR_DATABASE_ID || undefined,
      cardDatabaseId: env.NOTION_CARD_DATABASE_ID || undefined,
      memoryPageId: env.NOTION_MEMORY_PAGE_ID,
      dryRun,
    }),
    reviewer,
    repo: createRepoReader(ROOT),
    texts: {
      system: readFileSync(join(HERE, "prompts/system.md"), "utf8"),
      baseline: readFileSync(join(ROOT, "docs/review-baseline.md"), "utf8"),
      architecture: readFileSync(join(ROOT, "docs/architecture.md"), "utf8"),
    },
    now: () => new Date(),
    log: (message) => console.log(logLine(message)),
    warn,
    summary,
    // 공개 로그에는 개수·ID·사용량만 남긴다(분석 내용은 남기지 않음).
    ledger: (entry) => {
      console.log(`PR_ANALYSIS_USAGE ${JSON.stringify(entry)}`);
      summary(`- 사용량: ${entry.purpose} · ${entry.result} · ${entry.response_model ?? entry.model} · 입력 ${entry.input_tokens}(캐시 ${entry.cached_tokens}) · 출력 ${entry.output_tokens}(추론 ${entry.reasoning_tokens}) · ${Math.round(entry.duration_ms / 1000)}초 · 재시도 ${entry.retries}`);
    },
    preview: env.REVIEW_PREVIEW_OUT ? (data) => writeFileSync(env.REVIEW_PREVIEW_OUT, `${JSON.stringify(data, null, 2)}\n`) : null,
  });
  if (verifyModel && !verificationSucceeded(result)) {
    warn("모델 확인 실패: 실제 모델 분석이 성공하지 않았습니다.");
    process.exitCode = 1;
  }
} catch (error) {
  stop(error);
}
