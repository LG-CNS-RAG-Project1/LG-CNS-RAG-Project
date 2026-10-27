// PR 한 건을 이벤트 정책에 따라 처리한다. GitHub·Notion·OpenAI·git 접근은 모두 deps로 받는다(테스트에서 가짜로 바꿀 수 있음).
// 이벤트별 모델 호출 수
// - 초안 열림·수정본: 0회. 페이지·그림을 만들지 않는다. 초안 전환은 이미 있는 행의 상태만 '초안'으로 바꾼다.
// - 검토 요청 상태의 첫 분석(열림·Ready for review·다시 열림): 1회. 같은 응답에 보고서와 영역 카드 변경 후보가 함께 온다.
//   서비스 아키텍처 그림은 PR 페이지에 없을 때 한 번만 코드로 그린다.
// - 수정본(synchronize): 지난 '성공한' 분석 뒤 PR 변경 내용(파일 지문)이 바뀌었을 때만 1회, 바뀐 파일과 관련 카드만 넘긴다.
//   바뀌지 않은 파일의 결과는 프로그램이 유지하고, 그림은 다시 그리지 않는다(최초 구조라는 표시만 붙인다).
// - 병합: 0회. 분석 잡은 상태만 바꾸고, 카드 잡이 최종 변경과 대조해 검증된 카드 변경만 항목 단위로 반영한다.
// - 병합 없이 닫힘: 0회. 상태만 바꾼다.
// AI가 실패하면 마지막 성공 보고서를 그대로 보여 주고 현재 버전은 실패로 표시한다. 다른 모델이나 다른 제공자로 넘기지 않는다.
import { randomBytes } from "node:crypto";

import { parseMermaidModel } from "../notion/architecture.mjs";
import {
  CARD_KEYWORD_LIMIT, CARD_PR_LIMIT, annotateDelta, appendRecord, applyCardDelta, cardHasRecord, cardIsSufficient, cardSnapshot, formatCard, mergeDeltas,
  mergeList, relevantTags,
} from "./cards.mjs";
import { DEFAULT_INPUT_BUDGET, buildContext, priorSummary, quoted, quotedList } from "./context.mjs";
import { buildPrDiagram } from "./diagram.mjs";
import { fetchPull, readCi } from "./github.mjs";
import { LABELS } from "./labels.mjs";
import {
  baselineStatus, computeReadiness, decideMode, fileSignature, filesDigest, filterBaselineRefs, finalizeJudgment, findSecrets, keywordsOf,
  maskPatch, mergeFindings, parseMappings, parsePatch, parseTagRules, runPrechecks, sha256, tagOf, tagsOf, validateReviewOutput, verifyFindings,
} from "./lib.mjs";
import { safeMessage } from "./codex_engine.mjs";
import { STATE_VERSION, diagramFirstLine, diagramStatusText, renderReport } from "./render.mjs";
import { SCHEMA_NAME, SCHEMA_VERSION, buildReviewSchema } from "./review_schema.mjs";

export const ANALYZER = "pr-analysis-3";
export const MAX_ATTEMPTS_PER_HEAD = 2;
export const QUOTA_COOLDOWN_MS = 6 * 60 * 60 * 1000;
// 구독 사용 한도는 재설정 시각을 알면 그때까지, 모르면 1시간 멈춘다.
export const PLAN_LIMIT_COOLDOWN_MS = 60 * 60 * 1000;
// 분석기 제공자: openai=OpenAI API 키(Responses API), codex=Codex CLI + ChatGPT 구독 로그인. 설정한 하나만 쓰고 서로 대신하지 않는다.
export const PROVIDERS = ["openai", "codex"];
export const verificationSucceeded = (result) => result.llm_calls === 1 && ["done", "partial"].includes(result.ai_status);
// 다른 PR에서도 똑같이 실패할 오류(결제 한도·인증·모델 접근·응답 모델 불일치·요청 형식)
export const GLOBAL_STOP = ["quota", "plan_limit", "auth", "model_access", "model_mismatch", "invalid_request"];
export const MAX_SOURCE_FILES = 6;
// patch가 없어도 내용 검토 대상이 아닌 바이너리 파일(이미지·글꼴·압축·문서 등)
export const BINARY_FILE = /\.(png|jpe?g|gif|webp|ico|bmp|svgz|pdf|zip|gz|tgz|tar|7z|woff2?|ttf|otf|eot|mp3|mp4|mov|wav|parquet|pkl|npy|npz|db|sqlite|xlsx?|docx?|pptx?|hwp)$/i;
const short = (sha) => String(sha ?? "").slice(0, 7);
const bytes = (value) => Buffer.byteLength(String(value ?? ""));

export const promptVersion = (system) => sha256(`${system}\n${SCHEMA_VERSION}`).slice(0, 12);

// 공통 사용량 기록 한 줄(공개 로그에는 개수·ID·사용량만 남긴다)
export function ledgerEntry({ config, pr, purpose = "review", result, call = null, sections = {} }) {
  return {
    pr: pr.number,
    head: short(pr.head?.sha),
    event: config.eventAction || config.eventName || "manual",
    purpose,
    provider: config.provider,
    model: config.model,
    response_model: call?.response_model ?? null,
    input_tokens: call?.usage?.input ?? 0,
    cached_tokens: call?.usage?.cached ?? 0,
    cache_write_tokens: call?.usage?.cache_write ?? 0,
    output_tokens: call?.usage?.output ?? 0,
    reasoning_tokens: call?.usage?.reasoning ?? 0,
    sections,
    duration_ms: call?.duration_ms ?? 0,
    retries: call?.retries ?? 0,
    result,
  };
}

// 설정한 제공자의 분석기만 만든다. 인증 정보가 없으면 null이며, 다른 제공자의 인증 정보가 있어도 그쪽으로 넘어가지 않는다.
// factories: { codex(codexHome), openai(apiKey) }, hasCodexLogin(codexHome): auth.json 존재 여부
export function selectReviewer({ step, provider, env, factories, hasCodexLogin }) {
  if (step !== "analyze") return null;
  if (provider === "codex") return env.CODEX_HOME && hasCodexLogin(env.CODEX_HOME) ? factories.codex(env.CODEX_HOME) : null;
  if (provider === "openai") return env.OPENAI_API_KEY ? factories.openai(env.OPENAI_API_KEY) : null;
  return null;
}

export async function runPr(deps) {
  const { config, github, log } = deps;
  const pr = await fetchPull(github, config.prNumber);
  log(`PR #${pr.number} (${pr.state}${pr.draft ? ", 초안" : ""}) head ${short(pr.head.sha)}`);
  if (!config.verifyModel && config.step !== "cards" && pr.state === "closed") return closeFlow(deps, pr);
  if (!config.verifyModel && config.step !== "cards" && (config.eventAction === "closed" || (config.eventAction === "converted_to_draft" && !pr.draft))) {
    const state = pr.draft ? LABELS.prState.draft : LABELS.prState.open;
    try { await deps.notion.markStatus(pr.number, state); }
    catch (error) { deps.warn(`Notion 상태 갱신 실패: ${error.message}`); }
    log(`지난 이벤트를 건너뛰고 현재 PR 상태 ${state}만 반영합니다(AI 호출 없음).`);
    deps.ledger(ledgerEntry({ config, pr, purpose: "status", result: "skipped:stale_event" }));
    return { action: "status", status: state, llm_calls: 0 };
  }
  if (!config.verifyModel && config.step !== "cards" && pr.draft) return draftFlow(deps, pr);
  const files = await github.files(pr.number);
  const metadata = [pr.title, pr.head?.ref, pr.base?.ref, ...files.flatMap((file) => [file.filename, file.previous_filename])];
  if (metadata.some((value) => value && maskPatch(value) !== value)) {
    deps.warn("PR 제목·브랜치·파일 경로에 비밀값이 의심되어 모델 호출과 기록을 중단했습니다.");
    deps.ledger(ledgerEntry({ config, pr, result: "skipped:secret_metadata" }));
    return { action: "skipped", reason: "secret_metadata", llm_calls: 0 };
  }
  if (config.step === "cards") return applyCards({ ...deps, prFiles: files }, pr);
  return analyzeFlow({ ...deps, prFiles: files }, pr);
}

async function closeFlow(deps, pr) {
  const { config, notion, log, warn, ledger } = deps;
  const merged = Boolean(pr.merged_at);
  try {
    const count = await notion.markStatus(pr.number, merged ? LABELS.prState.merged : LABELS.prState.closed);
    log(`행 ${count}개의 상태를 ${merged ? "병합" : "닫힘"}으로 바꿨습니다(AI 호출 없음).`);
  } catch (error) {
    warn(`Notion 상태 갱신 실패: ${error.message}`);
  }
  ledger(ledgerEntry({ config, pr, purpose: "status", result: `skipped:${merged ? "merged" : "closed"}` }));
  return { action: "status", status: merged ? "merged" : "closed", llm_calls: 0 };
}

async function draftFlow(deps, pr) {
  const { config, notion, log, warn, ledger } = deps;
  try {
    const count = await notion.markStatus(pr.number, LABELS.prState.draft);
    log(`초안 PR의 기존 행 ${count}개 상태만 바꿨습니다(페이지·그림 없음, AI 호출 없음).`);
  } catch (error) {
    warn(`Notion 상태 갱신 실패: ${error.message}`);
  }
  ledger(ledgerEntry({ config, pr, result: "skipped:draft" }));
  return { action: "skipped", reason: "draft", llm_calls: 0 };
}

// 이전 형식(상태 버전이 다른) 상태는 성공 분석으로 쓰지 않고 차수만 이어받는다.
function upgradeState(previous) {
  if (!previous || previous.v === STATE_VERSION) return previous;
  return { v: STATE_VERSION, legacy: true, seq: previous.seq ?? 0, history: [] };
}

// 카드 기준 SHA 뒤 develop에서 그 계층 파일이 바뀌었으면 오래된 카드로 본다.
async function staleTags({ github, cards, tags, baseSha, tagOfPath }) {
  const stale = [];
  const cache = new Map();
  for (const tag of tags) {
    const card = cards[tag];
    if (!cardIsSufficient(card) || !card.base_sha || baseSha.startsWith(card.base_sha)) continue;
    try {
      if (!cache.has(card.base_sha)) cache.set(card.base_sha, (await github.compare(card.base_sha, baseSha)).files ?? []);
      if (cache.get(card.base_sha).some((file) => tagOfPath(file.filename) === tag)) stale.push(tag);
    } catch {
      stale.push(tag);
    }
  }
  return stale;
}

// 프로그램이 확인한 사실 구획. PR 작성자가 정하는 글(파일·브랜치 이름, 점검 내용)은 한 줄 따옴표 문자열로만 넣고,
// 주석 규칙 후보 원문은 PR 구획(nonce 안)에 넣는다.
function factsText({ pr, baseSha, mergeBase, mode, decided, carried, tags, keywords, relevant, insufficient, ci, conflict, checks, comments }) {
  const modeLine = mode === "incremental"
    ? `incremental (이번 patch에는 지난 성공 분석 뒤 바뀐 파일 ${decided.changed.length}개${carried.length ? `와 지난번 입력 예산으로 제외됐던 파일 ${carried.length}개` : ""}만 포함${decided.removed.length ? `, PR에서 빠진 파일: ${quotedList(decided.removed)}` : ""})`
    : "full (PR 전체 분석)";
  return [
    "# 프로그램이 확인한 사실",
    `- 분석 대상 head: ${pr.head.sha}`,
    `- develop 기준: ${baseSha} / merge base: ${mergeBase}`,
    `- 분석 방식: ${modeLine}`,
    `- 태그(서비스 계층): ${tags.join(", ") || "없음"} / 키워드: ${keywords.join(", ") || "없음"}`,
    `- 넘긴 영역 카드: ${relevant.join(", ") || "없음"}${insufficient.length ? ` (카드가 없거나 오래돼 develop 원본을 함께 넘긴 계층: ${insufficient.join(", ")})` : ""}`,
    `- 자동 검사(ci.yml): ${ci.state} ${JSON.stringify(ci.jobs)}`,
    `- 충돌: ${conflict.state}${conflict.files.length ? ` (${quotedList(conflict.files)})` : ""}`,
    ...checks.map((check) => `- ${check.rule}: ${check.status} — ${quoted(check.detail)}`),
    comments.length ? `- 주석 규칙 후보: ${comments.length}건(내용은 PR 구획)` : "",
  ].filter(Boolean).join("\n");
}

async function analyzeFlow(deps, pr) {
  const { config, github, notion, repo, texts, log, warn, ledger } = deps;
  const now = deps.now();
  const versions = { analyzer: ANALYZER, prompt: promptVersion(texts.system), schema: SCHEMA_VERSION, provider: config.provider, model: config.model };

  let previous = null;
  try {
    previous = upgradeState(await notion.readState(pr.number));
  } catch (error) {
    warn(`이전 분석 상태를 읽지 못했습니다(기존 페이지는 PR 번호로 다시 찾습니다): ${error.message}`);
  }
  if (previous && maskPatch(JSON.stringify(previous)) !== JSON.stringify(previous)) {
    warn("이전 분석 상태에 비밀값이 의심되어 모델 호출과 기록을 중단했습니다.");
    ledger(ledgerEntry({ config, pr, result: "skipped:secret_state" }));
    return { action: "skipped", reason: "secret_state", llm_calls: 0 };
  }
  const success = previous?.last_successful_analysis ?? null;
  const sameVersions = Boolean(success) && Object.keys(versions).every((key) => success.versions?.[key] === versions[key]);
  if (!config.force && success && success.head === pr.head.sha && sameVersions && previous.last_attempt?.published !== false) {
    log(`이 버전(${short(pr.head.sha)})은 같은 설정으로 이미 분석했습니다. 건너뜁니다(force로 다시 분석 가능).`);
    // 초안 전환 뒤 'Ready for review'나 닫힌 뒤 다시 열기는 코드가 같아도 PR 상태가 바뀌었으므로 상태 열만 '열림'으로 고친다.
    if (["ready_for_review", "reopened"].includes(config.eventAction)) {
      try {
        await notion.markStatus(pr.number, LABELS.prState.open);
      } catch (error) {
        warn(`Notion 상태 갱신 실패: ${error.message}`);
      }
    }
    ledger(ledgerEntry({ config, pr, result: "skipped:same_head" }));
    return { action: "skipped", reason: "same_head", llm_calls: 0 };
  }

  // ---------- 수집·규칙 점검 ----------
  const [files, commits, baseSha] = await Promise.all([deps.prFiles, github.commits(pr.number), github.branchSha(pr.base.ref)]);
  const mergeBase = await github.mergeBase(baseSha, pr.head.sha);
  const conflict = repo.conflict({ prNumber: pr.number, headSha: pr.head.sha, baseSha, mergeBaseSha: mergeBase });
  if ((conflict.files ?? []).some((path) => maskPatch(path) !== path)) {
    warn("충돌 파일 경로에 비밀값이 의심되어 모델 호출과 기록을 중단했습니다.");
    ledger(ledgerEntry({ config, pr, result: "skipped:secret_metadata" }));
    return { action: "skipped", reason: "secret_metadata", llm_calls: 0 };
  }
  const secretHits = files.flatMap((file) => findSecrets(file.filename, parsePatch(file.patch).added));
  for (const commit of commits.filter((item) => (item.parents ?? []).length === 1)) {
    const detail = await github.commit(commit.sha);
    for (const file of detail.files ?? []) secretHits.push(...findSecrets(file.filename, parsePatch(file.patch).added, commit.sha.slice(0, 7)));
  }
  const mappings = parseMappings(texts.architecture);
  const tagRules = parseTagRules(texts.baseline);
  const statusMap = baselineStatus(texts.baseline);
  let ci = await readCi(github, pr);
  let { checks, comments } = runPrechecks({ pr, files, commits, ci, secretHits, mappings });
  const paths = files.map((file) => file.filename);
  const tagOfPath = (path) => tagOf(path, mappings, tagRules);
  const tags = tagsOf(paths, mappings, tagRules);
  const keywords = keywordsOf(paths);
  const signatures = Object.fromEntries(files.map((file) => [file.filename, fileSignature(file)]));
  const currentSecret = checks.some((check) => check.rule === "AGENTS_5_secrets" && check.status === "fail");

  // ---------- 분석 방식·호출 여부 ----------
  const decided = decideMode({ success, signatures, force: config.force, versionChanged: Boolean(success) && !sameVersions });
  const mode = decided.mode;
  const lastAttempt = previous?.last_attempt;
  // 같은 버전의 실패 횟수와 재시도 가능 시각은 대기로 건너뛴 실행이 있어도 이어진다(성공하거나 버전이 바뀌면 처음부터).
  const sameHeadAttempt = lastAttempt?.head === pr.head.sha ? lastAttempt : null;
  const failedAttempts = sameHeadAttempt?.failed_attempts ?? 0;
  let ops = {};
  try {
    ops = await notion.readOps();
  } catch (error) {
    warn(`운영 상태를 읽지 못했습니다: ${error.message}`);
  }
  const waits = [ops.cooldown_until, sameHeadAttempt?.retry_after_at].map((value) => Date.parse(value ?? "")).filter(Number.isFinite);
  const cooling = !config.force && waits.some((time) => time > now.getTime());
  let skip = null;
  if (mode === "none") skip = "no_change";
  else if (!config.llmEnabled) skip = "llm_disabled";
  else if (!PROVIDERS.includes(config.provider) || config.model !== "gpt-6-sol") skip = "config";
  else if (!deps.reviewer) skip = "no_key";
  else if (!config.actorAllowed) skip = "actor";
  else if (currentSecret) skip = "secret";
  else if (!config.force && failedAttempts >= MAX_ATTEMPTS_PER_HEAD) skip = "retry_limit";
  else if (cooling) skip = "cooldown";

  // ---------- 모델 호출(필요할 때만 1회) ----------
  const carried = mode === "incremental" ? (success.coverage?.excluded ?? []).filter((path) => paths.includes(path) && !decided.changed.includes(path)) : [];
  const targetPaths = mode === "incremental" ? [...decided.changed, ...carried] : paths;
  let call = null;
  let validated = null;
  let context = null;
  let relevant = [];
  let snapshots = {};
  if (!skip) {
    let cards = {};
    try {
      cards = await notion.readCards();
    } catch (error) {
      warn(`영역 카드를 읽지 못했습니다(카드 없이 분석): ${error.message}`);
    }
    if (maskPatch(JSON.stringify(cards)) !== JSON.stringify(cards)) {
      warn("영역 카드에 비밀값이 의심되어 모델 호출과 기록을 중단했습니다.");
      ledger(ledgerEntry({ config, pr, result: "skipped:secret_card" }));
      return { action: "skipped", reason: "secret_card", llm_calls: 0 };
    }
    relevant = relevantTags(targetPaths, tagOfPath, cards);
    snapshots = Object.fromEntries(relevant.map((tag) => [tag, cardSnapshot(cards[tag])]));
    const stale = await staleTags({ github, cards, tags: relevant, baseSha, tagOfPath });
    const insufficient = relevant.filter((tag) => !cardIsSufficient(cards[tag]) || stale.includes(tag));
    const sources = files
      .filter((file) => file.status !== "added" && targetPaths.includes(file.filename) && insufficient.includes(tagOfPath(file.previous_filename ?? file.filename)))
      .slice(0, MAX_SOURCE_FILES)
      .map((file) => {
        const path = file.previous_filename ?? file.filename;
        return { path, tag: tagOfPath(path), sha: baseSha, content: repo.showFile(baseSha, path) };
      })
      .filter((source) => source.content);
    const prior = mode === "incremental" ? priorSummary(success) : null;
    const instructions = `${texts.system}\n\n# 안내서\n\n${texts.baseline}`;
    const schema = buildReviewSchema(relevant);
    context = buildContext({
      nonce: deps.nonce?.() ?? randomBytes(6).toString("hex"),
      budget: config.inputBudget ?? DEFAULT_INPUT_BUDGET,
      fixedBytes: bytes(instructions) + bytes(JSON.stringify(schema)),
      facts: factsText({ pr, baseSha, mergeBase, mode, decided, carried, tags, keywords, relevant, insufficient, ci, conflict, checks, comments }),
      pr, commits, files, targetFiles: files.filter((file) => targetPaths.includes(file.filename)), mode, prior,
      cardsText: relevant.map((tag) => formatCard(tag, cards[tag], stale.includes(tag))).join("\n\n") || "이 PR 변경 파일에 해당하는 계층 태그 없음.",
      sources, mappings, comments,
    });
    const effort = mode === "incremental" ? config.effort.incremental : config.effort.full;
    const maxOutputTokens = mode === "incremental" ? config.maxOutputTokens.incremental : config.maxOutputTokens.full;
    log(`GPT 분석: ${config.model} · reasoning ${effort} · 출력 상한 ${maxOutputTokens} · 방식 ${mode} · 입력 ${context.total_bytes}바이트(예산 ${config.inputBudget ?? DEFAULT_INPUT_BUDGET}) · 카드 ${relevant.join(", ") || "없음"}`);
    call = await deps.reviewer.review({ model: config.model, instructions, input: context.input, schema, schemaName: SCHEMA_NAME, effort, maxOutputTokens });
    if (call.status === "done") {
      if (maskPatch(JSON.stringify(call.output)) !== JSON.stringify(call.output)) call = { ...call, status: "failed", error_class: "schema", output: null, problems: ["응답에 비밀값이 의심되어 폐기했습니다."] };
    }
    if (call.status === "done") {
      validated = validateReviewOutput(call.output, {
        headSha: pr.head.sha, files, includedPaths: context.included, priorIds: (prior?.open_findings ?? []).map((item) => item.id), cardTags: relevant, snapshots, tagOfPath, cards,
      });
      if (validated.fatal) call = { ...call, status: "failed", error_class: "schema", problems: [validated.fatal] };
      else if (validated.dropped.length) log(`응답 검증: 대상과 맞지 않는 항목 ${validated.dropped.length}개를 버렸습니다(${[...new Set(validated.dropped)].join(", ")}).`);
    }
    if (call.status === "done") log(`  완료: ${Math.round(call.duration_ms / 1000)}초, 응답 모델 ${call.response_model}, 재시도 ${call.retries}회`);
    else {
      // 스키마 오류의 키 이름에는 모델이 출력한 임의 문자열이 들어갈 수 있다.
      const details = (call.error_class === "schema" && call.problems?.length ? ["응답 스키마 검증 실패"] : call.problems ?? []).slice(0, 3).map((item) => safeMessage(item));
      warn(`AI 분석 실패(${LABELS.error[call.error_class] ?? call.error_class}${call.http_status ? `, HTTP ${call.http_status}` : ""}${call.incomplete_reason ? `, ${call.incomplete_reason}` : ""}). 마지막 성공 결과를 유지하고 이번 버전은 실패로 표시합니다.${details.length ? ` 요약: ${details.join(" | ")}` : ""}`);
    }
    ledger(ledgerEntry({ config, pr, call, sections: context.sections, result: call.status === "done" ? "success" : `failed:${call.error_class}` }));
  } else {
    log(`AI를 부르지 않습니다: ${LABELS.skip[skip] ?? skip}`);
    ledger(ledgerEntry({ config, pr, result: `skipped:${skip}` }));
  }

  // ---------- 결과 합치기 ----------
  const nextSeq = previous?.next_finding_seq ?? 1;
  let output = null;
  let findings = [];
  let ai;
  let coverage = { state: "full", excluded: [] };
  let scope = { changed: mode === "incremental" ? targetPaths : [], excluded: [], no_patch: [], truncated: [], added: 0, closed: 0 };
  let nextFindingSeq = nextSeq;
  if (call?.status === "done") {
    output = validated.output;
    if (output.goal_fit) {
      output.goal_fit.baseline_refs = filterBaselineRefs(output.goal_fit.baseline_refs, statusMap);
      if (!filterBaselineRefs([output.goal_fit.primary_ref], statusMap).length) output.goal_fit.primary_ref = output.goal_fit.baseline_refs[0] ?? "";
    }
    const fresh = verifyFindings(output.findings, files, pr.number, { startSeq: nextSeq });
    nextFindingSeq = nextSeq + fresh.length;
    const merged = mode === "incremental"
      ? mergeFindings({ previous: success.findings ?? [], fresh, priorStatuses: output.prior_findings, changed: decided.changed, removed: decided.removed, files })
      : { findings: fresh, closed: [], added: fresh };
    findings = merged.findings;
    // AI가 보지 못한 파일: 입력 예산으로 뺀 patch와, patch가 없는 바이너리 외 파일. 참고 자료가 잘렸어도 '일부 범위'로 남긴다.
    const unreviewed = [...context.excluded, ...context.no_patch.filter((path) => !BINARY_FILE.test(path))];
    coverage = { state: unreviewed.length ? "partial" : "full", excluded: unreviewed };
    scope = { ...scope, excluded: context.excluded, no_patch: context.no_patch, truncated: context.truncated, added: merged.added.length, closed: merged.closed.length };
    ai = {
      status: coverage.state === "partial" || context.truncated.length ? "partial" : "done",
      head: pr.head.sha, at: now.toISOString(), provider: config.provider, model: config.model, response_model: call.response_model,
    };
  } else if (success) {
    output = success.output;
    findings = success.findings ?? [];
    coverage = success.coverage ?? coverage;
    ai = {
      status: mode === "none" ? "reused" : call ? "failed" : "skipped", head: success.head, at: success.at,
      provider: success.versions?.provider, model: success.versions?.model, response_model: success.response_model, error_class: call?.error_class ?? null, skip_reason: skip,
    };
  } else {
    ai = { status: call ? "failed" : "skipped", head: null, provider: config.provider, model: config.model, error_class: call?.error_class ?? null, skip_reason: skip };
  }

  if (ci.state === "running" || ci.state === "none") {
    log(`자동 검사 결과를 최대 ${config.ciWaitSeconds}초 기다립니다.`);
    ci = await readCi(github, pr, { waitSeconds: config.ciWaitSeconds });
    ({ checks, comments } = runPrechecks({ pr, files, commits, ci, secretHits, mappings }));
  }
  const readiness = computeReadiness({ draft: false, checks, ci, conflict, output, findings, coverage: coverage.state, llmStatus: ai.status === "partial" ? "done" : ai.status, files });
  const judgment = finalizeJudgment(output, readiness, findings);
  const displayMode = call?.status === "done" ? mode : mode === "none" ? "none" : "deterministic";
  const attempt = {
    head: pr.head.sha, at: now.toISOString(), event: config.eventAction || config.eventName || "manual", mode: displayMode,
    status: call ? (call.status === "done" ? ai.status : "failed") : "skipped", skip_reason: skip, error_class: call?.status === "done" ? null : call?.error_class ?? null,
    retry_after_at: call ? call.retry_after_at ?? null : sameHeadAttempt?.retry_after_at ?? null, model: config.model, response_model: call?.response_model ?? null,
  };
  const resultLabel = attempt.status === "skipped" ? `호출 안 함: ${LABELS.skip[skip] ?? skip}` : attempt.status === "failed" ? `실패: ${LABELS.error[attempt.error_class] ?? attempt.error_class}` : LABELS.analysis[attempt.status];
  const history = [...(previous?.history ?? []), {
    at: attempt.at, head: short(pr.head.sha), mode: displayMode, result: resultLabel, readiness: readiness.state, findings: findings.length,
    model: call?.response_model ?? null, usage: call?.usage ?? null,
  }].slice(-10);

  const analysis = {
    repo: config.repository,
    generated_at: now.toISOString(),
    pr: { number: pr.number, title: pr.title, url: pr.html_url, author: pr.user.login, branch: pr.head.ref, base: pr.base.ref, head_sha: pr.head.sha, draft: false },
    baseline_draft: [...statusMap.values()].includes("초안"),
    ci, conflict, prechecks: checks, comment_candidates: comments, tags, keywords,
    mode: displayMode, scope, coverage, ai, attempt, output, findings, readiness, judgment,
  };
  const report = renderReport(analysis, history);
  deps.preview?.({ analysis, report });

  // ---------- Notion 기록(페이지 하나를 제자리에서 고침) ----------
  const makeDiagram = () => {
    try {
      return buildPrDiagram({ repo, architecture: texts.architecture, baseSha, conflict, headSha: pr.head.sha, prNumber: pr.number, files, at: now.toISOString() });
    } catch (error) {
      warn(`서비스 아키텍처 그림을 만들지 못했습니다: ${error.message}`);
      return null;
    }
  };
  const diagramStatus = (existing) => {
    const firstHead = parseMermaidModel(existing.code_text)?.sha ?? "";
    const firstLine = existing.status_text.split("\n")[0] || diagramFirstLine({ head: firstHead, at: now.toISOString(), note: "생성 시각 미확인" });
    return diagramStatusText({ firstLine, latestHead: pr.head.sha, firstHead });
  };
  let published = null;
  try {
    published = await notion.publishPr({
      prNumber: pr.number, report, pageIdHint: previous?.page_id ?? null, makeDiagram, diagramStatus,
      previousReportIds: [...(previous?.report_block_ids ?? []), ...(previous?.pending_delete_ids ?? [])],
    });
    log(`Notion 기록 완료: ${published.url} (${published.created ? "새 페이지" : `기존 페이지 갱신, 이전 보고서 블록 ${published.deleted}개 휴지통 이동`}${published.diagram?.created ? ", 그림 생성" : ""}${published.undeleted_ids.length ? `, 삭제 실패 ${published.undeleted_ids.length}개(다음 실행에서 다시 정리)` : ""})`);
  } catch (error) {
    warn(`Notion 기록 실패: ${error.message}${error.code === "restricted_resource" ? " (Notion 블록 한도 초과로 보입니다)" : ""}`);
  }

  // ---------- 상태 저장 ----------
  const newSuccess = call?.status === "done" ? {
    head: pr.head.sha, base: baseSha, merge_base: mergeBase, at: now.toISOString(), versions, response_model: call.response_model,
    mode, scope: { changed: targetPaths, excluded: context.excluded, no_patch: context.no_patch, truncated: context.truncated, sources: context.sources },
    coverage, card_revisions_used: Object.fromEntries(relevant.map((tag) => [tag, snapshots[tag].revision])),
    files: Object.fromEntries(Object.entries(signatures).map(([path, sig]) => [path, { sig }])),
    files_digest: filesDigest(signatures),
    output, findings, usage: call.usage,
  } : null;
  const state = {
    v: STATE_VERSION,
    repo: config.repository,
    pr: pr.number,
    page_id: published?.page_id ?? previous?.page_id ?? null,
    report_block_ids: published ? published.report_block_ids : previous?.report_block_ids ?? [],
    pending_delete_ids: published ? published.undeleted_ids : previous?.pending_delete_ids ?? [],
    last_attempt: {
      ...attempt,
      failed_attempts: attempt.status === "failed" ? failedAttempts + 1 : call?.status === "done" ? 0 : failedAttempts,
      published: Boolean(published), usage: call?.usage ?? null,
    },
    last_successful_analysis: newSuccess ?? success,
    // 카드 변경 후보: 전체 분석이면 새 응답으로, 수정본이면 이번에 다시 본 파일 근거 항목만 바꾸고 나머지는 이어받는다.
    card_delta: newSuccess
      ? {
        head: pr.head.sha,
        items: mergeDeltas(
          mode === "incremental" ? previous?.card_delta?.items ?? [] : [],
          (output.candidate_card_delta ?? []).map((item) => annotateDelta(item, snapshots[item.tag])),
          context.included,
        ),
        card_revisions: Object.fromEntries(relevant.map((tag) => [tag, snapshots[tag].revision])),
      }
      : previous?.card_delta ?? null,
    card_application: previous?.card_application ?? null,
    diagram: published?.diagram?.created ? { head: pr.head.sha, at: now.toISOString() } : previous?.diagram ?? null,
    next_finding_seq: nextFindingSeq,
    history,
    seq: (previous?.seq ?? 0) + 1,
  };
  try {
    await notion.saveState(pr.number, state);
  } catch (error) {
    warn(`분석 상태 저장 실패: ${error.message}. 다음 실행은 PR 번호로 기존 페이지·그림을 먼저 찾아 중복을 만들지 않습니다.`);
  }
  // 설정·결제 문제(모든 PR에 같은 실패가 반복되는 경우)는 저장소 전체 AI 호출을 멈춘다. 속도 제한은 재설정 시각까지만 멈춘다.
  if (call && call.status !== "done" && (GLOBAL_STOP.includes(call.error_class) || call.error_class === "rate_limit")) {
    const until = call.error_class === "rate_limit"
      ? call.retry_after_at
      : call.error_class === "plan_limit"
        ? call.retry_after_at ?? new Date(now.getTime() + PLAN_LIMIT_COOLDOWN_MS).toISOString()
        : new Date(now.getTime() + QUOTA_COOLDOWN_MS).toISOString();
    if (until && Date.parse(until) > now.getTime() + 60_000) {
      try {
        await notion.saveOps({ ...ops, cooldown_until: until, reason: call.error_class, set_at: now.toISOString(), pr: pr.number });
        warn(`전체 AI 호출을 ${until}까지 멈춥니다(${LABELS.error[call.error_class]}). 수동 실행의 force로만 앞당길 수 있습니다.`);
      } catch (error) {
        warn(`운영 상태 저장 실패: ${error.message}`);
      }
    }
  }
  deps.summary?.(`### PR 분석 (참고용)\n- PR #${pr.number} · ${short(pr.head.sha)} · 방식 ${LABELS.mode[displayMode]} · AI ${resultLabel} · 준비 상태 ${LABELS.readiness[readiness.state]} · 확인할 점 ${findings.length}건 · Notion ${published ? "기록" : "실패"}`);
  return { action: "analyzed", mode: displayMode, ai_status: ai.status, llm_calls: call ? (call.model_calls ?? 1) : 0, published, state, report };
}

// 병합된 PR의 카드 변경 후보를 검증해 항목 단위로 반영한다(모델 호출 없음).
async function applyCards(deps, pr) {
  const { config, github, notion, texts, log, warn, ledger } = deps;
  const now = deps.now();
  if (!pr.merged_at) {
    log("병합되지 않은 PR이라 영역 카드를 갱신하지 않습니다.");
    return { action: "cards", status: "not_merged", llm_calls: 0 };
  }
  ledger(ledgerEntry({ config, pr, purpose: "cards", result: "skipped:merge" }));
  const state = upgradeState(await notion.readState(pr.number));
  if (state && maskPatch(JSON.stringify(state)) !== JSON.stringify(state)) {
    warn("기존 분석 상태에 비밀값이 의심되어 카드 반영을 중단했습니다.");
    return { action: "cards", status: "secret_state", llm_calls: 0 };
  }
  const mergeSha = pr.merge_commit_sha;
  if (state?.card_application?.merge_sha === mergeSha) {
    log(`PR #${pr.number}의 카드 반영은 이미 처리했습니다(${state.card_application.status}).`);
    return { action: "cards", status: "already", llm_calls: 0 };
  }
  const success = state?.last_successful_analysis;
  const delta = state?.card_delta;
  const mappings = parseMappings(texts.architecture);
  const tagRules = parseTagRules(texts.baseline);
  const tagOfPath = (path) => tagOf(path, mappings, tagRules);
  let application;
  if (!success || !delta || delta.head !== success.head) application = { status: "no_analysis" };
  else if (!(delta.items ?? []).length) application = { status: "no_delta" };
  else {
    // 분석한 변경과 최종 병합된 PR 변경을 파일 지문으로 대조한다(병합·squash·rebase 커밋 SHA를 직접 비교하지 않는다).
    const finalFiles = deps.prFiles;
    const finalSigs = Object.fromEntries(finalFiles.map((file) => [file.filename, fileSignature(file)]));
    // 상태 크기 때문에 파일별 지문을 버린 경우에는 요약 해시로 대조한다.
    const differ = success.files
      ? [...new Set([...Object.keys(finalSigs), ...Object.keys(success.files)])].filter((path) => success.files[path]?.sig !== finalSigs[path])
      : success.files_digest === filesDigest(finalSigs) ? [] : ["(파일 지문 요약 불일치)"];
    if (differ.length) application = { status: "unverified", files: differ.slice(0, 20) };
    else {
      const results = {};
      let cards = await notion.readCards({ fresh: true });
      if (maskPatch(JSON.stringify(cards)) !== JSON.stringify(cards)) {
        warn("영역 카드에 비밀값이 의심되어 카드 반영을 중단했습니다.");
        return { action: "cards", status: "secret_card", llm_calls: 0 };
      }
      for (const item of delta.items) {
        const tagFiles = finalFiles.map((file) => file.filename).filter((path) => tagOfPath(path) === item.tag);
        for (let round = 0; round < 2; round += 1) {
          const card = cards[item.tag];
          if (card && cardHasRecord(card, pr.number)) {
            results[item.tag] = { status: "already" };
            break;
          }
          const { next, applied, conflicts } = applyCardDelta(card, item, null);
          const revision = (card?.revision ?? 0) + (applied.length ? 1 : 0);
          const updated = {
            tag: item.tag, scope: next.scope, contracts: next.contracts, evidence: next.evidence, revision,
            base_sha: applied.length ? mergeSha : card?.base_sha ?? "",
            prs: applied.length ? mergeList(card?.prs, [`#${pr.number}`], CARD_PR_LIMIT) : card?.prs ?? "",
            records: appendRecord(card?.records, pr.number, `${short(mergeSha)} 리비전 ${card?.revision ?? 0}→${revision} · 적용 ${applied.length} · 충돌 ${conflicts.length}${conflicts.length ? `(${conflicts.join("; ")})` : ""}`),
            keywords: mergeList(card?.keywords, keywordsOf(tagFiles), CARD_KEYWORD_LIMIT),
            updated_at: now.toISOString(),
          };
          if (await notion.writeCard(item.tag, updated, card?.revision ?? 0)) {
            results[item.tag] = { status: "written", applied: applied.length, conflicts };
            break;
          }
          // 읽은 뒤 다른 쪽이 카드를 고쳤다. 다시 읽어 같은 3-way 비교를 한 번 더 한다.
          cards = await notion.readCards({ fresh: true });
          if (maskPatch(JSON.stringify(cards)) !== JSON.stringify(cards)) {
            warn("갱신된 영역 카드에 비밀값이 의심되어 이후 카드 반영을 중단했습니다.");
            return { action: "cards", status: "secret_card", llm_calls: 0 };
          }
          if (round === 1) results[item.tag] = { status: "revision_changed" };
        }
      }
      application = { status: "applied", tags: results };
    }
  }
  application = { ...application, merge_sha: mergeSha, at: now.toISOString() };
  const text = cardResultText(application);
  log(`영역 카드: ${text}`);
  try {
    await notion.saveState(pr.number, { ...(state ?? { v: STATE_VERSION, repo: config.repository, pr: pr.number, history: [], seq: 0 }), card_application: application, seq: (state?.seq ?? 0) + 1 });
    await notion.setPrProperties(pr.number, { "카드 반영": text });
  } catch (error) {
    warn(`카드 반영 결과 기록 실패: ${error.message}`);
  }
  return { action: "cards", status: application.status, application, llm_calls: 0 };
}

export function cardResultText(application) {
  switch (application.status) {
    case "no_analysis": return "반영 안 함: 성공한 AI 분석 없음";
    case "no_delta": return "반영 안 함: 카드 변경 후보 없음";
    case "unverified": return `반영 안 함: 분석 뒤 병합 전 변경 있음(${application.files.slice(0, 5).join(", ")})`;
    case "applied": return Object.entries(application.tags).map(([tag, result]) =>
      result.status === "written" ? `${tag} 적용 ${result.applied}·충돌 ${result.conflicts.length}` : `${tag} ${result.status === "already" ? "이미 반영" : "리비전 변경으로 보류"}`).join(", ") || "반영할 항목 없음";
    default: return application.status;
  }
}
