// PR 분석에 쓰는 순수 함수 모음이다. 네트워크·파일 접근 없이 patch 해석, 비밀값 탐지, 영역 매핑,
// 규칙 점검, AI 출력 검증, 준비 상태 계산을 한다.
import { createHash } from "node:crypto";

export const CI_JOBS = ["Black format check", "Pytest", "Automation script tests", "Docker build"];

export const sha256 = (value) => createHash("sha256").update(value).digest("hex");

// patch를 줄 번호가 붙은 추가·삭제 줄 목록으로 바꾼다.
export function parsePatch(patch = "") {
  const added = [];
  const removed = [];
  let oldLine = 0;
  let newLine = 0;
  for (const raw of String(patch).split("\n")) {
    const hunk = /^@@ -(\d+)(?:,\d+)? \+(\d+)(?:,\d+)? @@/.exec(raw);
    if (hunk) {
      oldLine = Number(hunk[1]);
      newLine = Number(hunk[2]);
      continue;
    }
    if (raw.startsWith("+")) added.push({ line: newLine++, text: raw.slice(1) });
    else if (raw.startsWith("-")) removed.push({ line: oldLine++, text: raw.slice(1) });
    else if (!raw.startsWith("\\")) {
      oldLine += 1;
      newLine += 1;
    }
  }
  return { added, removed };
}

// 파일 변경 지문: 상태·이전 경로·추가/삭제 줄만으로 만든다(hunk 위치가 바뀌어도 같다).
export function fileSignature(file) {
  const { added, removed } = parsePatch(file.patch);
  const body = file.patch ? [...added, ...removed].map((item) => item.text).join("\n") : String(file.sha ?? "");
  return sha256(`${file.status}|${file.previous_filename ?? ""}|${body}`).slice(0, 16);
}

// ---------- 비밀값 ----------
export const SECRET_PATTERNS = [
  /\b(sk-[A-Za-z0-9_-]{16,}|ghp_[A-Za-z0-9]{20,}|github_pat_[A-Za-z0-9_]{20,}|ntn_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16})\b/,
  /-----BEGIN [A-Z ]*PRIVATE KEY-----/,
  /(?:NAVER_CLIENT_SECRET|X-NCP-APIGW-API-KEY(?:-ID)?|KIPRIS_API_KEY|DART_API_KEY|OPENAI_API_KEY)["']?\s*[:=]\s*["']?([^"'\s$<{][^"'\s,)]{5,})/i,
  /\b(?:api[_-]?key|secret[_-]?key|client[_-]?secret|access[_-]?token|auth[_-]?token|refresh[_-]?token|bearer|password|passwd)\b["']?\s*[:=]\s*["']([^"'${<\s][^"'\s]{7,})["']/i,
];
const ENV_FILE_PATTERN = /^[A-Z0-9_]*(KEY|SECRET|TOKEN|PASSWORD|_ID)\s*=\s*(\S{6,})/;
const PLACEHOLDER = /^(your_|xxx|<|\$\{|\$\(|changeme|example)/i;
const TEST_VALUE = /^["']?(test|dummy|fake|example|sample)/i;
// 위젯 key·식별자처럼 보이는 값(소문자·밑줄·하이픈만)은 비밀값으로 보지 않는다.
const IDENTIFIER_LIKE = /^[a-z][a-z_-]*$/;

export const maskValue = (value) => `****(${value.length}자, ${sha256(value).slice(0, 8)})`;

// 추가된 줄에서 비밀값으로 보이는 값을 찾는다. 값 자체는 돌려주지 않고 가린 표시와 지문만 돌려준다.
export function findSecrets(path, lines, commit = null) {
  const hits = [];
  const isEnvFile = /(^|\/)\.env/.test(path);
  for (const { line, text } of lines) {
    if (/os\.getenv|os\.environ/.test(text)) continue;
    const candidates = [];
    for (const pattern of SECRET_PATTERNS) {
      const match = pattern.exec(text);
      if (match) candidates.push(match[1] ?? match[0]);
    }
    if (isEnvFile) {
      const match = ENV_FILE_PATTERN.exec(text.trim());
      if (match) candidates.push(match[2]);
    }
    for (const value of candidates) {
      const clean = value.replace(/^["']|["']$/g, "");
      if (!clean || PLACEHOLDER.test(clean) || IDENTIFIER_LIKE.test(clean)) continue;
      if (path.startsWith("tests/") && TEST_VALUE.test(clean)) continue;
      hits.push({ path, line: commit ? null : line, commit, masked: maskValue(clean), fingerprint: sha256(clean).slice(0, 8) });
    }
  }
  return hits;
}

// AI 입력에 넣기 전에 patch 속 비밀값을 가린다.
export function maskPatch(patch = "") {
  let out = String(patch);
  for (const pattern of SECRET_PATTERNS) {
    const global = new RegExp(pattern.source, `${pattern.flags.replace("g", "")}g`);
    out = out.replace(global, (whole, group) => (group ? whole.replace(group, maskValue(group)) : maskValue(whole)));
  }
  return out;
}

// ---------- 아키텍처 영역 ----------
export function parseMappings(markdown) {
  return [...String(markdown).matchAll(/%% map (\S+) (\S+)/g)].map((match) => ({ prefix: match[1], node: match[2] }));
}

// 가장 긴 접두사 하나로 파일의 영역을 정한다.
export function moduleOf(path, mappings) {
  let best = null;
  for (const { prefix, node } of mappings) {
    const hit = prefix.endsWith("/") ? path.startsWith(prefix) : path === prefix || path.startsWith(`${prefix}/`);
    if (hit && (!best || prefix.length > best.prefix.length)) best = { prefix, node };
  }
  return best?.node ?? null;
}

export const isCommonPath = (path) =>
  path === "README.md" || /^requirements.*\.txt$/.test(path) || path === ".env.example" ||
  path === ".gitignore" || path.startsWith("docs/") || path.startsWith("configs/");

// ---------- 규칙 점검 ----------
const COMMENT_PATTERNS = [
  /\b20\d{2}[-./]\d{1,2}([-./]\d{1,2})?\b/, /\bv\d+(\.\d+)+\b/, /@author|author:|작성자\s*[:：]/i,
  /\b(?=[0-9a-f]*\d)(?=[0-9a-f]*[a-f])[0-9a-f]{7,40}\b/, /(수정|변경)\s*(이력|내역)|changelog/i,
];
const CONVENTIONAL = /^(feat|fix|chore|docs|refactor|test|style|ci|build|perf)(\(.+\))?!?:/i;

// PR·파일·커밋·CI 정보로 결정적 점검 결과 목록을 만든다.
export function runPrechecks({ pr, files, commits, ci, secretHits, mappings }) {
  const checks = [];
  const add = (rule, status, detail) => checks.push({ rule, status, detail });
  const body = pr.body ?? "";

  const required = ["## 변경 요약", "## 변경 유형", "## 주요 변경 내용", "## 검증 방법", "## 체크리스트"];
  const missing = required.filter((section) => !body.includes(section));
  const typeBlock = body.split("## 변경 유형")[1]?.split("\n## ")[0] ?? "";
  const typesChecked = (typeBlock.match(/- \[x\]/gi) ?? []).length;
  if (missing.length) add("template", "warn", `PR 양식 섹션 없음: ${missing.map((section) => section.replace("## ", "")).join(", ")}`);
  else if (!typesChecked) add("template", "warn", "변경 유형이 하나도 선택되지 않음");
  else add("template", "ok", "PR 양식 섹션과 변경 유형이 채워져 있음");
  if (pr.base?.ref !== "develop") add("template", "warn", `합칠 대상이 develop이 아님(${pr.base?.ref})`);

  const mismatch = [];
  if (/- \[x\] `?black --check/i.test(body) && ci.jobs["Black format check"] === "failure") mismatch.push("black 통과 체크 ↔ 검사 실패");
  if (/- \[x\] `?pytest/i.test(body) && ci.jobs.Pytest === "failure") mismatch.push("pytest 통과 체크 ↔ 검사 실패");
  add("check_mismatch", mismatch.length ? "warn" : "ok", mismatch.join(", ") || "체크 표시와 검사 결과가 맞음");

  const current = new Set(secretHits.filter((hit) => !hit.commit).map((hit) => hit.fingerprint));
  const unscannable = files.filter((file) => !file.patch && file.status !== "removed").map((file) => file.filename);
  if (current.size) add("AGENTS_5_secrets", "fail", "현재 버전에 비밀값으로 보이는 값이 있음");
  else if (secretHits.length) add("AGENTS_5_secrets", "warn", "지운 비밀값이 커밋 기록에 남아 있음(키 폐기 확인 필요)");
  else add("AGENTS_5_secrets", unscannable.length ? "warn" : "ok", unscannable.length ? `보안 점검 일부 못 함: ${unscannable.join(", ")}` : "비밀값으로 보이는 값 없음");

  const readmeChanged = files.some((file) => file.filename === "README.md");
  const addedFiles = files.filter((file) => file.status === "added" && !file.filename.startsWith("tests/"));
  if (readmeChanged) add("AGENTS_4_docs", "ok", "README.md가 함께 갱신됨");
  else if (addedFiles.length) add("AGENTS_4_docs", "warn", `새 파일 ${addedFiles.length}개가 추가됐지만 README.md는 그대로`);
  else add("AGENTS_4_docs", "ok", "문서 갱신이 필요한 신규 파일 없음");

  const nonMerge = commits.filter((commit) => (commit.parents ?? []).length === 1);
  const productModules = new Set();
  let productLines = 0;
  for (const file of files) {
    if (isCommonPath(file.filename) || file.filename.startsWith("tests/")) continue;
    const node = moduleOf(file.filename, mappings);
    if (node && node !== "runtime") productModules.add(node);
    productLines += (file.additions ?? 0) + (file.deletions ?? 0);
  }
  const others = nonMerge.filter((commit) => commit.author?.login && commit.author.login !== pr.user?.login);
  const signals = [];
  if (productModules.size >= 3) signals.push(`제품 영역 ${productModules.size}개(${[...productModules].join(", ")})`);
  if (productLines > 800) signals.push(`공용 경로 제외 변경 ${productLines}줄`);
  if (others.length) signals.push(`다른 작성자 커밋 ${others.length}개(다른 브랜치 커밋 섞임)`);
  add("AGENTS_2_scope", signals.length ? "warn" : "ok", signals.join(", ") || `제품 영역 ${productModules.size}개, 변경 ${productLines}줄`);

  const branchOk = /^feature\/[a-z0-9-]+$/.test(pr.head?.ref ?? "");
  add("branch_name", branchOk ? "ok" : "warn", branchOk ? `브랜치 이름 규칙 맞음(${pr.head.ref})` : `브랜치 이름이 규칙과 다름(${pr.head?.ref})`);

  const own = nonMerge.filter((commit) => !commit.author?.login || commit.author.login === pr.user?.login);
  const bad = own.filter((commit) => {
    const [title, ...rest] = String(commit.commit?.message ?? "").split("\n");
    return CONVENTIONAL.test(title) || !rest.some((line) => line.trim().startsWith("- "));
  });
  add("AGENTS_8_commits", bad.length ? "warn" : "ok", bad.length ? `커밋 형식과 다른 커밋 ${bad.length}개 / ${own.length}개` : `커밋 ${own.length}개 모두 형식에 맞음`);

  const comments = [];
  for (const file of files) {
    if (file.filename.endsWith(".md")) continue;
    const { added, removed } = parsePatch(file.patch);
    const removedText = new Set(removed.map((item) => item.text.trim()));
    for (const { line, text } of added) {
      const comment = /^\s*(#|\/\/)\s?(.*)$/.exec(text);
      if (!comment || removedText.has(text.trim())) continue;
      if (COMMENT_PATTERNS.some((pattern) => pattern.test(comment[2]))) comments.push({ path: file.filename, line, text: comment[2].slice(0, 120) });
    }
  }
  add("AGENTS_6_comments", comments.length ? "warn" : "ok", comments.length ? `주석 규칙 후보 ${comments.length}건` : "주석 규칙 후보 없음");

  return { checks, comments };
}

// ---------- AI 출력 검증 ----------
const normalize = (value) => String(value).replace(/^\s*[+-]\s?/, "").replace(/\s+/g, " ").trim();

// 앵커가 해당 파일 변경 줄에서 20자 이상·토큰 3개 이상으로 정확히 한 곳과 맞을 때만 위치 확인으로 본다.
export function verifyFindings(findings, files, prNumber, limit = 8) {
  const index = new Map(files.map((file) => [file.filename, parsePatch(file.patch)]));
  return (findings ?? []).slice(0, limit).map((finding, position) => {
    const lines = index.get(finding.file);
    let anchorFound = false;
    let line = null;
    if (lines && finding.kind === "presence" && finding.anchor) {
      const anchor = normalize(finding.anchor);
      const pool = finding.side === "old" ? lines.removed : lines.added;
      const matches = pool.filter((item) => normalize(item.text).includes(anchor));
      if (anchor.length >= 20 && anchor.split(" ").length >= 3 && matches.length === 1) {
        anchorFound = true;
        line = matches[0].line;
      }
    }
    return { ...finding, id: `F${prNumber}-${position + 1}`, in_pr: Boolean(lines), anchor_found: anchorFound, line };
  }).filter((finding) => finding.in_pr);
}

// 안내서에서 ID별 상태([확정]/[초안]/[비어 있음])를 읽는다.
export function baselineStatus(markdown) {
  return new Map([...String(markdown).matchAll(/(B-[A-Z]+(?:-\d+)?) \[(확정|초안|비어 있음)\]/g)].map((match) => [match[1], match[2]]));
}

export function filterBaselineRefs(refs, statusMap) {
  return (refs ?? []).filter((ref) => statusMap.has(ref) && statusMap.get(ref) !== "비어 있음");
}

// ---------- 준비 상태 ----------
// 처음 맞는 상태를 고른다: 보완 후 검토 → 함께 논의 → 리더가 한 번 보기 → 검토 준비됨.
export function computeReadiness({ draft, checks, ci, conflict, output, findings, coverage, llmStatus, files }) {
  const pick = () => {
    const needsFix = [];
    if (checks.some((check) => check.rule === "AGENTS_5_secrets" && check.status === "fail")) needsFix.push("보안 확인 필요");
    if (ci.state === "failed") needsFix.push("자동 검사 실패");
    if (conflict.state === "conflict") needsFix.push("다른 작업과 충돌");
    if (needsFix.length) return needsFix.map((reason) => ({ state: "needs_fix", reason }));
    const discuss = [];
    if (output?.goal_fit?.rating === "misaligned") discuss.push("목표 연결 확인 필요");
    if (output?.module_fit?.contract_impact === "breaking") discuss.push("다른 부분도 함께 고쳐야 할 수 있음");
    if (discuss.length) return discuss.map((reason) => ({ state: "discuss", reason }));
    const look = [];
    const serious = (findings ?? []).filter((finding) => ["blocker", "major"].includes(finding.severity));
    if (serious.length) look.push(`AI가 꼭 고칠 점·중요 ${serious.length}건을 냄(리더 판정 전)`);
    if (ci.state !== "passed") look.push(`자동 검사 상태 확인 필요(${ci.state})`);
    if (coverage === "partial") look.push("일부만 분석");
    if (llmStatus !== "done" && llmStatus !== "reused") look.push("AI 분석 안 됨");
    if ((files ?? []).some((file) => /^(\.github\/workflows\/|scripts\/review\/|AGENTS\.md|docs\/review-baseline\.md)/.test(file.filename))) look.push("안내서·분석기·워크플로 변경");
    if (look.length) return look.map((reason) => ({ state: "leader_look", reason }));
    return [{ state: "ready", reason: "자동 검사 통과, 꼭 고칠 점 없음" }];
  };
  const reasons = pick();
  if (draft) return { state: "draft", reasons: [{ state: "draft", reason: "초안(리더 요청으로 분석함)" }], if_not_draft: reasons };
  return { state: reasons[0].state, reasons, if_not_draft: null };
}

// ---------- 입력 예산 ----------
// patch 합계가 40KB 이하면 전부, 넘으면 우선순위(src > 매핑 영역 > 자동화 > tests > docs > 기타)와 작은 파일 순으로 약 80KB까지.
export function selectPatches(files, mappings, { small = 40_000, max = 80_000 } = {}) {
  const withPatch = files.filter((file) => file.patch);
  const total = withPatch.reduce((sum, file) => sum + Buffer.byteLength(file.patch), 0);
  if (total <= small) return { included: withPatch, total };
  const rank = (path) =>
    path.startsWith("src/") ? 0 : moduleOf(path, mappings) ? 1 : path.startsWith("scripts/") || path.startsWith(".github/") ? 2 :
    path.startsWith("tests/") ? 3 : path.startsWith("docs/") ? 4 : 5;
  const included = [];
  let used = 0;
  for (const file of [...withPatch].sort((a, b) => rank(a.filename) - rank(b.filename) || a.patch.length - b.patch.length)) {
    const size = Buffer.byteLength(file.patch);
    if (used + size > max) continue;
    included.push(file);
    used += size;
  }
  return { included, total };
}
