// 모델 입력(input)을 만든다. 지시문·스키마를 포함한 전체 입력 예산(UTF-8 바이트) 안에서 구획을 우선순위대로 채운다.
// 우선순위: 프로그램이 확인한 사실 → PR 글(제목·본문·커밋) → 지난 분석 요약·열린 확인할 점 → 영역 카드 → patch → 카드가 없거나 오래된 계층의 원본.
// patch가 예산을 넘으면 우선순위가 낮은 파일부터 빼고 제외 목록을 사실 구획에 적는다(일부 범위 분석으로 기록된다).
// 사람이 쓴 글·지난 AI 출력·카드는 모두 nonce 구획 안에 넣고, 구획 표기를 흉내 낸 글은 바꾼다.
import { maskPatch, selectPatches } from "./lib.mjs";

export const DEFAULT_INPUT_BUDGET = 160_000;
const LIMITS = { body: 6_000, commits: 3_000, fileList: 20_000, prior: 8_000, cards: 12_000, sourceFile: 12_000, patchMax: 80_000 };

const bytes = (value) => Buffer.byteLength(String(value ?? ""));
const MARKERS = ["untrusted_pr_", "prior_analysis_", "area_cards_", "area_source_"];
export const escapeMarkers = (value) => MARKERS.reduce((text, marker) => text.replaceAll(marker, marker.replaceAll("_", "-")), String(value ?? ""));

// 사실 구획에 넣는 PR 유래 글(파일 이름·브랜치 이름 등)을 한 줄 따옴표 문자열로 바꾼다. 줄바꿈으로 사실 줄을 흉내 내지 못한다.
// 목록은 앞의 limit개만 넣고 나머지는 개수로 적는다(사실 구획이 입력 예산을 넘지 않게).
export const quoted = (value, max = 300) => escapeMarkers(JSON.stringify(String(value ?? "").slice(0, max)));
export const quotedList = (values, limit = 30) =>
  [...values.slice(0, limit).map((value) => quoted(value)), ...(values.length > limit ? [`…외 ${values.length - limit}개`] : [])].join(", ");

// 글을 최대 바이트로 자른다. 잘렸으면 표시를 붙인다.
export function clipBytes(value, max) {
  const text = String(value ?? "");
  if (bytes(text) <= max) return { text, clipped: false };
  let cut = text.slice(0, Math.max(0, Math.floor(max / 3)));
  while (bytes(cut) < max - 40 && cut.length < text.length) cut = text.slice(0, cut.length + 200);
  while (bytes(cut) > max - 40) cut = cut.slice(0, -50);
  return { text: `${cut}\n…(입력 예산으로 일부 생략)`, clipped: true };
}

// 지난 성공 분석에서 다음 분석에 넘길 짧은 요약과 열린 확인할 점(전체 JSON 대신)
export function priorSummary(success) {
  if (!success?.output) return null;
  const output = success.output;
  return {
    head: success.head,
    one_line: output.summary?.one_line ?? "",
    what_changed: output.summary?.what_changed ?? [],
    why: output.summary?.why ?? "",
    digest: output.digest ?? "",
    open_findings: (success.findings ?? []).map(({ id, severity, file, title, anchor }) => ({ id, severity, file, title, anchor })),
  };
}

export function buildContext({
  nonce, budget = DEFAULT_INPUT_BUDGET, fixedBytes = 0, facts, pr, commits, files, targetFiles, mode, prior, cardsText, sources = [], mappings, comments = [],
}) {
  const sections = {};
  const truncated = [];
  let remaining = budget - fixedBytes;
  const take = (name, text) => {
    sections[name] = bytes(text);
    remaining -= sections[name];
    return text;
  };

  const prText = [
    escapeMarkers(`제목: ${pr.title}`),
    escapeMarkers(`작성자: ${pr.user?.login} / 브랜치: ${pr.head?.ref} → ${pr.base?.ref}`),
    "본문:",
  ];
  const body = clipBytes(escapeMarkers(maskPatch(pr.body || "(비어 있음)")), LIMITS.body);
  if (body.clipped) truncated.push("PR 본문");
  const commitLines = clipBytes(commits.map((commit) => escapeMarkers(maskPatch(`- ${String(commit.commit?.message ?? "").split("\n")[0]}`))).join("\n"), LIMITS.commits);
  if (commitLines.clipped) truncated.push("커밋 메시지");
  const changedNote = (path) => (mode === "incremental" && !targetFiles.some((file) => file.filename === path) ? " — 지난 성공 분석 뒤 변경 없음, patch 생략" : "");
  const fileLines = [];
  let listBytes = 0;
  for (const file of files) {
    const line = escapeMarkers(`- ${file.filename} (${file.status} +${file.additions} -${file.deletions})${changedNote(file.filename)}`);
    if (listBytes + bytes(line) > LIMITS.fileList) break;
    fileLines.push(line);
    listBytes += bytes(line) + 1;
  }
  if (fileLines.length < files.length) {
    fileLines.push(`- …외 ${files.length - fileLines.length}개 파일(입력 예산으로 목록 생략)`);
    truncated.push("변경 파일 목록");
  }
  const fileList = fileLines.join("\n");
  const commentLines = comments.map((item) => escapeMarkers(maskPatch(`- ${item.path}:${item.line} ${item.text}`))).join("\n");
  const prHead = take("pr_text", [...prText, body.text, "커밋 메시지:", commitLines.text, "변경 파일:", fileList, ...(comments.length ? ["주석 규칙 후보(프로그램이 고른 추가 주석 줄):", commentLines] : [])].join("\n"));

  let priorText = "";
  if (prior) {
    const clipped = clipBytes(escapeMarkers(JSON.stringify(prior, null, 1)), LIMITS.prior);
    if (clipped.clipped) truncated.push("지난 분석 요약");
    priorText = take("prior", `# 이 PR의 지난 성공 분석(버전 ${String(prior.head).slice(0, 7)}, 요약과 열린 확인할 점만, 검증 안 됨)\n${clipped.text}`);
  }

  const cards = clipBytes(escapeMarkers(cardsText || "없음."), LIMITS.cards);
  if (cards.clipped) truncated.push("영역 카드");
  const cardSection = take("cards", cards.text);

  // 사실 구획은 patch 선택 결과(제외 목록)를 담아야 하므로 크기를 미리 잡아 두고 마지막에 채운다.
  const factsReserve = bytes(facts) + 4_000;
  remaining -= factsReserve;
  const patchBudget = Math.max(0, Math.min(LIMITS.patchMax, remaining - 2_000));
  const { included } = selectPatches(targetFiles, mappings, { small: Math.min(40_000, patchBudget), max: patchBudget });
  const excluded = targetFiles.filter((file) => file.patch && !included.includes(file)).map((file) => file.filename);
  const noPatch = targetFiles.filter((file) => !file.patch && file.status !== "removed").map((file) => file.filename);
  const patchText = take("patches", included.map((file) => escapeMarkers(`### ${file.filename}\n${maskPatch(file.patch)}`)).join("\n"));

  const sourceParts = [];
  const usedSources = [];
  for (const source of sources) {
    const clipped = clipBytes(escapeMarkers(maskPatch(source.content)), LIMITS.sourceFile);
    const part = `### ${source.path} (develop ${String(source.sha).slice(0, 7)}, ${source.tag})\n${clipped.text}`;
    if (bytes(part) + 200 > remaining) {
      truncated.push(`원본 ${source.path}`);
      continue;
    }
    if (clipped.clipped) truncated.push(`원본 ${source.path}(일부)`);
    sourceParts.push(part);
    usedSources.push(source.path);
    remaining -= bytes(part);
  }
  sections.sources = bytes(sourceParts.join("\n"));

  const scopeLines = [
    excluded.length ? `- 입력 예산으로 patch를 넣지 못한 파일(이번 분석 범위 밖): ${quotedList(excluded)}` : "",
    noPatch.length ? `- GitHub가 patch를 주지 않은 파일(이번 분석 범위 밖): ${quotedList(noPatch)}` : "",
    truncated.length ? `- 일부만 넣은 참고 자료: ${quotedList(truncated)}` : "",
  ].filter(Boolean);
  const factText = [facts, ...scopeLines].join("\n");
  sections.facts = bytes(factText);

  const input = maskPatch([
    factText,
    "",
    ...(priorText ? [`<prior_analysis_${nonce}>`, priorText, `</prior_analysis_${nonce}>`, ""] : []),
    `<area_cards_${nonce}>`, cardSection, `</area_cards_${nonce}>`,
    "",
    `<untrusted_pr_${nonce}>`, prHead, "patch:", patchText, `</untrusted_pr_${nonce}>`,
    ...(sourceParts.length ? ["", `<area_source_${nonce}>`, ...sourceParts, `</area_source_${nonce}>`] : []),
  ].join("\n"));
  return {
    input,
    sections,
    total_bytes: fixedBytes + bytes(input),
    included: included.map((file) => file.filename),
    excluded,
    no_patch: noPatch,
    truncated,
    sources: usedSources,
  };
}
