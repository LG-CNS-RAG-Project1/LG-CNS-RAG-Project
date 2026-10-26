// 계층 태그별 '영역 카드'를 다루는 순수 함수다. 네트워크 호출은 하지 않는다.
// 카드는 develop에 병합된 사실만 담는다: 범위(scope), 핵심 계약(contracts, key별), 근거 파일·심볼(evidence, key별), 기준 SHA, 리비전.
// - PR 분석 때 모델은 카드 변경 후보(delta)를 내고, 병합 시점에 프로그램이 검증한 항목만 항목 단위로 반영한다.
// - 반영은 분석 당시 카드 스냅샷과 지금 카드를 비교하는 3-way 방식이라, 그사이 다른 PR·사람이 고친 항목은 덮어쓰지 않고 충돌로 남긴다.
// - 반영 기록(적용 기록)은 최근 PR 표시 목록(반영한 PR)과 따로 쌓는다.
export const CARD_LIMITS = { scope: 15, contracts: 30, line: 200 };
export const CARD_PR_LIMIT = 20;
export const CARD_KEYWORD_LIMIT = 30;
export const CARD_RECORD_LIMIT = 30;
export const CONTEXT_CARD_BYTES = 3_000;

// 카드에 남기면 안 되는 권한 주장(승인·합의 등)
const AUTHORITY = /(승인|합의|허락|결재)/;
const SEPARATOR = " — ";

const clip = (value, max) => (value.length > max ? `${value.slice(0, max - 6)}…(잘림)` : value);

// 권한 주장이 든 문장을 지우고 최대 길이로 자른다.
export function cleanCardText(value, max = CARD_LIMITS.line) {
  const lines = String(value ?? "")
    .split("\n")
    .map((line) => line.split(/(?<=[.!?])\s+/).filter((part) => part.trim() && !AUTHORITY.test(part)).join(" ").trim())
    .filter(Boolean);
  return clip(lines.join(" "), max);
}

// 카드 칸의 글을 항목 목록으로 읽는다. '- key — text' 줄은 key·text로, 형식이 다른 줄은 줄 전체를 key로 본다.
export function parseItems(value) {
  return String(value ?? "")
    .split("\n")
    .map((line) => line.replace(/^\s*[-•]\s*/, "").trim())
    .filter(Boolean)
    .map((line) => {
      const at = line.indexOf(SEPARATOR);
      return at > 0 ? { key: line.slice(0, at).trim(), text: line.slice(at + SEPARATOR.length).trim() } : { key: line, text: "" };
    });
}

export const formatItems = (items) => items.map((item) => `- ${item.text ? `${item.key}${SEPARATOR}${item.text}` : item.key}`).join("\n");

// Notion 행 값으로 카드 객체를 만든다(fields: 칸 이름 → 글).
export function cardFromFields(tag, fields) {
  const contracts = parseItems(fields.contracts);
  const evidence = Object.fromEntries(parseItems(fields.evidence).map((item) => [item.key, item.text]));
  return {
    tag,
    scope: parseItems(fields.scope).map((item) => (item.text ? `${item.key}${SEPARATOR}${item.text}` : item.key)),
    contracts: Object.fromEntries(contracts.map((item) => [item.key, item.text])),
    evidence,
    revision: Number(fields.revision) || 0,
    base_sha: fields.base_sha ?? "",
    prs: fields.prs ?? "",
    records: fields.records ?? "",
    keywords: fields.keywords ?? "",
    legacy_summary: fields.legacy_summary ?? "",
  };
}

// Notion에 쓸 칸 글로 바꾼다.
export function cardToFields(card) {
  return {
    scope: card.scope.map((line) => `- ${line}`).join("\n"),
    contracts: formatItems(Object.entries(card.contracts).map(([key, text]) => ({ key, text }))),
    evidence: formatItems(Object.entries(card.evidence).map(([key, text]) => ({ key, text }))),
    revision: card.revision,
    base_sha: card.base_sha,
    prs: card.prs,
    records: card.records,
    keywords: card.keywords,
  };
}

// 분석 당시 카드 상태(병합 때 3-way 비교의 기준)
export const cardSnapshot = (card) =>
  card ? { revision: card.revision, base_sha: card.base_sha, scope: [...card.scope], contracts: { ...card.contracts } } : { revision: 0, base_sha: "", scope: [], contracts: {} };

// 새 형식으로 한 번 이상 반영됐고 내용이 있는 카드만 충분하다고 본다.
export const cardIsSufficient = (card) => Boolean(card && card.revision >= 1 && (card.scope.length || Object.keys(card.contracts).length));

// 분석에 넘길 카드 태그: 바뀐 파일의 태그 + 카드 근거에 바뀐 파일이 들어 있는 태그(직접 연결된 계약 영역).
export function relevantTags(paths, tagOfPath, cards) {
  const tags = new Set(paths.map(tagOfPath).filter(Boolean));
  const changed = new Set(paths);
  for (const card of Object.values(cards)) {
    if (Object.values(card.evidence ?? {}).some((value) => changed.has(String(value).split("#")[0]))) tags.add(card.tag);
  }
  return [...tags];
}

// 카드 하나를 분석 입력용 글로 만든다(최대 maxBytes).
export function formatCard(tag, card, stale, maxBytes = CONTEXT_CARD_BYTES) {
  const lines = [];
  if (!card) lines.push(`## ${tag}: 카드 없음`);
  else {
    const state = cardIsSufficient(card) ? (stale ? "오래됨(기준 SHA 뒤 develop에서 이 계층이 바뀜)" : "최신") : "새 형식 내용 없음";
    lines.push(`## ${tag} (리비전 ${card.revision}, 기준 SHA ${String(card.base_sha).slice(0, 7) || "-"}, ${state})`);
    lines.push("범위:", ...(card.scope.length ? card.scope.map((line) => `- ${line}`) : ["- (없음)"]));
    lines.push("핵심 계약:", ...(Object.keys(card.contracts).length
      ? Object.entries(card.contracts).map(([key, text]) => `- ${key}${SEPARATOR}${text}${card.evidence[key] ? ` (근거 ${card.evidence[key]})` : ""}`)
      : ["- (없음)"]));
    if (!cardIsSufficient(card) && card.legacy_summary) lines.push(`이전 형식 요약(검증 안 됨): ${clip(card.legacy_summary, 600)}`);
  }
  let text = lines.join("\n");
  while (Buffer.byteLength(text) > maxBytes) text = `${text.slice(0, Math.floor(text.length * 0.9))}\n…(카드 일부 생략)`;
  return text;
}

// 계약 key 정리: 공백을 하나로 줄이고, 카드 칸 구분자(' — ')를 '-'로 바꿔 다시 읽어도 같은 key가 되게 한다.
export const cleanKey = (value) => String(value ?? "").replace(/\s+/g, " ").replaceAll(SEPARATOR, " - ").trim().slice(0, 80);

// 모델이 낸 카드 변경 후보에 분석 당시 카드 값(base)을 항목마다 붙인다. 병합 때 이 값과 지금 카드를 비교한다(3-way).
export function annotateDelta(item, snapshot) {
  const base = snapshot ?? cardSnapshot(null);
  return {
    tag: item.tag,
    scope_add: [...(item.scope_add ?? [])],
    scope_remove: [...(item.scope_remove ?? [])],
    scope_base: [...base.scope],
    contracts_upsert: (item.contracts_upsert ?? []).map((entry) => ({ ...entry, key: cleanKey(entry.key), base_text: base.contracts[cleanKey(entry.key)] ?? null })),
    contracts_remove: (item.contracts_remove ?? []).map((key) => ({ key: cleanKey(key), base_text: base.contracts[cleanKey(key)] ?? null })),
  };
}

// 수정본 분석 결과의 카드 후보를 지난 후보와 합친다.
// 이번에 다시 본 파일(reviewedPaths)을 근거로 한 지난 계약 항목은 새 응답으로 바꾸고, 바뀌지 않은 파일 근거의 항목은 그대로 이어받는다.
// 같은 key는 새 응답이 이긴다. 범위 항목은 새 응답이 반대로 지정하지 않으면 이어받는다.
export function mergeDeltas(previousItems = [], freshItems = [], reviewedPaths = []) {
  const reviewed = new Set(reviewedPaths);
  const byTag = new Map(freshItems.map((item) => [item.tag, { ...item }]));
  for (const old of previousItems) {
    const fresh = byTag.get(old.tag);
    const keptUpserts = (old.contracts_upsert ?? []).filter((entry) => !reviewed.has(entry.evidence_file));
    if (!fresh) {
      byTag.set(old.tag, { ...old, contracts_upsert: keptUpserts });
      continue;
    }
    const freshKeys = new Set([...fresh.contracts_upsert.map((entry) => entry.key), ...fresh.contracts_remove.map((entry) => entry.key)]);
    fresh.contracts_upsert = [...keptUpserts.filter((entry) => !freshKeys.has(entry.key)), ...fresh.contracts_upsert];
    fresh.contracts_remove = [...(old.contracts_remove ?? []).filter((entry) => !freshKeys.has(entry.key)), ...fresh.contracts_remove];
    fresh.scope_add = [...new Set([...(old.scope_add ?? []).filter((line) => !fresh.scope_remove.includes(line)), ...fresh.scope_add])];
    fresh.scope_remove = [...new Set([...(old.scope_remove ?? []).filter((line) => !fresh.scope_add.includes(line)), ...fresh.scope_remove])];
    fresh.scope_base = [...new Set([...(old.scope_base ?? []), ...(fresh.scope_base ?? [])])];
  }
  return [...byTag.values()].filter((item) => item.scope_add.length || item.scope_remove.length || item.contracts_upsert.length || item.contracts_remove.length);
}

// 병합 시점에 카드 변경 후보를 항목 단위로 반영한다.
// 항목의 base_text(분석 당시 값)와 지금 카드 값이 다르고 후보와도 다르면 충돌로 남기고 고치지 않는다.
// base_text가 없는 후보(이전 형식)는 snapshot(분석 당시 카드)을 기준으로 쓴다.
export function applyCardDelta(card, delta, snapshot) {
  const next = {
    scope: [...(card?.scope ?? [])],
    contracts: { ...(card?.contracts ?? {}) },
    evidence: { ...(card?.evidence ?? {}) },
  };
  const base = snapshot ?? cardSnapshot(null);
  const scopeBase = delta.scope_base ?? base.scope;
  const baseOf = (entry, key) => ("base_text" in entry ? entry.base_text ?? undefined : base.contracts[key]);
  const applied = [];
  const conflicts = [];
  const unchanged = [];

  for (const raw of delta.scope_add ?? []) {
    const line = cleanCardText(raw);
    if (!line) continue;
    if (next.scope.includes(line)) unchanged.push(`범위+ ${line}`);
    else if (next.scope.length >= CARD_LIMITS.scope) conflicts.push(`범위+ ${line} (용량 초과)`);
    else {
      next.scope.push(line);
      applied.push(`범위+ ${line}`);
    }
  }
  for (const raw of delta.scope_remove ?? []) {
    const line = cleanCardText(raw);
    if (!next.scope.includes(line)) unchanged.push(`범위- ${line}`);
    else if (!scopeBase.includes(line)) conflicts.push(`범위- ${line} (분석 뒤 추가된 항목)`);
    else {
      next.scope = next.scope.filter((item) => item !== line);
      applied.push(`범위- ${line}`);
    }
  }
  for (const item of delta.contracts_upsert ?? []) {
    const key = cleanKey(item.key);
    const text = cleanCardText(item.text).replaceAll(SEPARATOR, " - ");
    if (!key || !text) continue;
    const current = next.contracts[key];
    const before = baseOf(item, key);
    if (current === text) unchanged.push(`계약 ${key}`);
    else if (current !== before) conflicts.push(`계약 ${key} (분석 뒤 다른 변경 있음)`);
    else if (current === undefined && Object.keys(next.contracts).length >= CARD_LIMITS.contracts) conflicts.push(`계약 ${key} (용량 초과)`);
    else {
      next.contracts[key] = text;
      next.evidence[key] = `${item.evidence_file}#${item.evidence_symbol}`;
      applied.push(`계약 ${key}`);
    }
  }
  for (const raw of delta.contracts_remove ?? []) {
    const entry = typeof raw === "string" ? { key: raw } : raw;
    const key = cleanKey(entry.key);
    const current = next.contracts[key];
    if (current === undefined) unchanged.push(`계약- ${key}`);
    else if (current !== baseOf(entry, key)) conflicts.push(`계약- ${key} (분석 뒤 다른 변경 있음)`);
    else {
      delete next.contracts[key];
      delete next.evidence[key];
      applied.push(`계약- ${key}`);
    }
  }
  return { next, applied, conflicts, unchanged };
}

// 쉼표로 구분한 목록에 새 항목을 더해 최근 것부터 limit개를 남긴다.
// 같은 항목(PR 항목 '#번호…'는 번호가 같은 것)이 있으면 지우고 새 항목을 맨 뒤에 둔다.
export function mergeList(existing, additions, limit) {
  const key = (item) => /^#\d+/.exec(item)?.[0] ?? item;
  let items = String(existing ?? "").split(",").map((value) => value.trim()).filter(Boolean);
  for (const item of additions.filter(Boolean)) {
    items = items.filter((kept) => key(kept) !== key(item));
    items.push(item);
  }
  return items.slice(-limit).join(", ");
}

// 적용 기록(줄 단위)에 한 줄을 더한다. 같은 PR 줄이 이미 있으면 그대로 둔다.
export function appendRecord(records, prNumber, line, limit = CARD_RECORD_LIMIT) {
  const lines = String(records ?? "").split("\n").map((item) => item.trim()).filter(Boolean);
  if (lines.some((item) => item.startsWith(`#${prNumber} `))) return lines.join("\n");
  return [...lines, `#${prNumber} ${line}`].slice(-limit).join("\n");
}

// 이 PR의 카드 반영 기록이 이미 있는지(같은 병합을 두 번 반영하지 않기 위해)
export const cardHasRecord = (card, prNumber) =>
  String(card?.records ?? "").split("\n").some((line) => line.trim().startsWith(`#${prNumber} `));

// 'PR 분석' 표의 '분석 내용' 열에 쓸 글(무엇을 왜 바꿨나 + 다음 분석용 메모)
export function analysisContent(output, max = 1900) {
  if (!output) return "AI 분석 없음(규칙 점검만).";
  const parts = [
    ...(output.summary?.what_changed ?? []).map((item) => `- ${item}`),
    output.summary?.why ? `이유: ${output.summary.why}` : "",
    output.digest ? `메모: ${output.digest}` : "",
  ].filter(Boolean);
  return clip(parts.join("\n"), max);
}
