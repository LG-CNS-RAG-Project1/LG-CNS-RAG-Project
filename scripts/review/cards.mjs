// 계층 태그별 '영역 요약 카드'와 관련 PR 기록을 다루는 순수 함수다.
// 카드 갱신용 AI 입력·출력 형식, 분석 입력에 넣을 문단, 카드 글 정리를 맡는다. 네트워크 호출은 하지 않는다.
export const CARD_LIMITS = { summary: 1200, interfaces: 600, risks: 600 };
export const CARD_PR_LIMIT = 20;
export const CARD_KEYWORD_LIMIT = 30;
export const MAX_CARD_TAGS = 5;

// 카드에 남기면 안 되는 권한 주장(승인·합의 등)
const AUTHORITY = /(승인|합의|허락|결재)/;

// 권한 주장이 든 문장을 지우고 최대 길이로 자른다.
export function cleanCardText(value, max) {
  const lines = String(value ?? "")
    .split("\n")
    .map((line) => line.split(/(?<=[.!?])\s+/).filter((part) => part.trim() && !AUTHORITY.test(part)).join(" ").trim())
    .filter(Boolean);
  const text = lines.join("\n");
  return text.length > max ? `${text.slice(0, max - 6)}…(잘림)` : text;
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

// 카드 내용에 이미 반영된 PR인지 확인한다. '#번호(내용 미반영)'은 반영 전으로 본다.
export const cardHasPr = (card, prNumber) =>
  String(card?.prs ?? "").split(",").some((item) => item.trim() === `#${prNumber}`);

// 변경 줄 수가 많은 순으로 카드를 갱신할 태그를 고른다.
export function pickCardTags(files, tagOfPath, limit = MAX_CARD_TAGS) {
  const lines = new Map();
  for (const file of files) {
    const tag = tagOfPath(file.filename);
    if (tag) lines.set(tag, (lines.get(tag) ?? 0) + (file.additions ?? 0) + (file.deletions ?? 0));
  }
  return [...lines.entries()].sort((a, b) => b[1] - a[1]).slice(0, limit).map(([tag]) => tag);
}

// 카드 갱신 AI의 출력 형식. 태그는 이번에 갱신할 것만 허용한다.
export function cardSchema(tags) {
  return JSON.stringify({
    type: "object",
    additionalProperties: false,
    required: ["cards"],
    properties: {
      cards: {
        type: "array",
        items: {
          type: "object",
          additionalProperties: false,
          required: ["tag", "summary", "interfaces", "risks"],
          properties: {
            tag: { type: "string", enum: tags },
            summary: { type: "string" },
            interfaces: { type: "string" },
            risks: { type: "string" },
          },
        },
      },
    },
  });
}

// 병합된 PR의 분석 결과로 카드 갱신 입력을 만든다. PR 원문과 diff는 넣지 않는다.
// 현재 카드 글·파일 이름·분석 결과는 모두 사람이나 AI가 쓴 데이터이므로 nonce 구획 안에 넣는다.
export function cardContext({ prNumber, tags, cards, output, filesByTag, nonce }) {
  const lines = [];
  for (const tag of tags) {
    const card = cards[tag];
    lines.push(`## 현재 카드: ${tag}`);
    if (card) {
      lines.push(`요약: ${card.summary || "(비어 있음)"}`, `인터페이스·계약: ${card.interfaces || "(비어 있음)"}`, `알려진 위험: ${card.risks || "(비어 있음)"}`);
    } else {
      lines.push("없음(새 카드)");
    }
    lines.push(`이번 PR에서 이 태그로 바뀐 파일: ${(filesByTag[tag] ?? []).join(", ") || "없음"}`, "");
  }
  const analysis = {
    one_line: output.summary?.one_line,
    what_changed: output.summary?.what_changed,
    why: output.summary?.why,
    contract_impact: output.module_fit?.contract_impact,
    module_claims: (output.module_fit?.claims ?? []).map((claim) => claim.text),
    findings: (output.findings ?? []).map(({ severity, title, file }) => ({ severity, title, file })),
    digest: output.digest,
  };
  lines.push(`## 병합된 PR #${prNumber}의 분석 결과(자동 생성, 검증 안 됨)`, JSON.stringify(analysis, null, 1));
  const data = lines.join("\n").replaceAll("pr_analysis_", "pr-analysis-");
  return [`# 갱신할 태그: ${tags.join(", ")}`, `<pr_analysis_${nonce}>`, data, `</pr_analysis_${nonce}>`].join("\n");
}

// 분석 입력에 넣을 '영역 요약 카드' 문단
export function formatCards(tags, cards) {
  const lines = ["# 영역 요약 카드(병합된 PR로 자동 갱신, 검증 안 됨, 안내서와 다르면 안내서 우선)"];
  const found = tags.filter((tag) => cards[tag]);
  if (!found.length) {
    lines.push(tags.length ? `없음(태그 ${tags.join(", ")}의 카드가 아직 없음).` : "없음(태그 없음).");
    return lines.join("\n");
  }
  for (const tag of found) {
    const card = cards[tag];
    lines.push(`## ${tag} (반영한 PR: ${card.prs || "-"})`, `요약: ${card.summary || "-"}`, `인터페이스·계약: ${card.interfaces || "-"}`, `알려진 위험: ${card.risks || "-"}`);
  }
  return lines.join("\n");
}

// 분석 입력에 넣을 '같은 키워드의 지난 PR 기록' 문단
export function formatRelated(rows) {
  const lines = ["# 같은 키워드의 지난 PR 기록(자동 생성, 검증 안 됨)"];
  if (!rows.length) return [...lines, "없음."].join("\n");
  for (const row of rows) {
    lines.push(`- PR #${row.number} [${row.state || "-"}] 태그 ${row.tags.join(", ") || "-"} · 키워드 ${row.keywords || "-"}: ${row.summary}`);
    if (row.content) lines.push(`  ${row.content.slice(0, 400)}`);
  }
  return lines.join("\n");
}

// 'PR 분석' 표의 '분석 내용' 열에 쓸 글(무엇을 왜 바꿨나 + 다음 분석용 메모)
export function analysisContent(output, max = 1900) {
  if (!output) return "AI 분석 없음(규칙 점검만).";
  const parts = [
    ...(output.summary?.what_changed ?? []).map((item) => `- ${item}`),
    output.summary?.why ? `이유: ${output.summary.why}` : "",
    output.digest ? `메모: ${output.digest}` : "",
  ].filter(Boolean);
  const text = parts.join("\n");
  return text.length > max ? `${text.slice(0, max - 6)}…(잘림)` : text;
}
