// 분석 결과를 Notion PR 행(속성 + 본문 블록)과 분석 상태 JSON으로 바꾼다. 네트워크 호출은 하지 않는다.
import { bulleted, callout, countBlocks, divider, enforceLimits, heading, paragraph, table, text, toRichText, toggle } from "../notion/blocks.mjs";
import { analysisContent } from "./cards.mjs";
import { LABELS } from "./labels.mjs";
import { sha256 } from "./lib.mjs";

// 상태 JSON 형식 버전. 바뀌면 다음 수정본은 처음부터 전체 분석한다.
export const STATE_VERSION = 2;

const modeText = (analysis) =>
  `${LABELS.mode[analysis.mode]}${analysis.mode === "incremental" ? `(바뀐 파일 ${analysis.changed_files.length}개)` : ""}`;

const kst = (iso) => `${new Date(iso).toLocaleString("sv-SE", { timeZone: "Asia/Seoul" }).slice(0, 16)} KST`;
const fileLink = (analysis, path, line) =>
  `https://github.com/${analysis.repo}/pull/${analysis.pr.number}/files#diff-${sha256(path)}${line ? `R${line}` : ""}`;

// '다음에 할 일': 보안 → 검사 → 충돌 → 꼭 고칠 점 → 팀 규칙 → AI 제안 순으로 최대 3개.
export function nextActions(analysis) {
  const lines = [];
  const { readiness, ci, conflict, prechecks, findings, output } = analysis;
  if (readiness.state === "draft") {
    lines.push("초안(리더 요청으로 분석함). 준비되면 PR 화면 맨 아래 'Ready for review'를 눌러 주세요. 누르면 검토 담당이 자동으로 지정됩니다.");
  }
  if (prechecks.some((check) => check.rule === "AGENTS_5_secrets" && check.status === "fail")) {
    lines.push("비밀번호나 API 키처럼 보이는 값이 있습니다(값은 가림). 진짜라면 리더에게 바로 알려 주세요. 예시 값이면 PR 댓글에 '예시 값'이라고 남겨 주세요.");
  }
  if (ci.state === "failed") lines.push("자동 검사가 실패했습니다. [결과 보기]에서 원인을 확인해 주세요. 어려우면 리더에게 링크를 공유해 주세요.");
  if (conflict.state === "conflict") lines.push(`다른 작업과 같은 곳을 고쳤습니다(파일: ${conflict.files.join(", ")}). PR 화면의 'Resolve conflicts'로 정리하거나 리더에게 요청해 주세요.`);
  for (const finding of findings.filter((item) => ["blocker", "major"].includes(item.severity))) {
    lines.push(`[${LABELS.severity[finding.severity]}] ${finding.title} — ${finding.file}${finding.line ? ` ${finding.line}번째 줄` : ""}`);
  }
  for (const check of prechecks.filter((item) => item.status === "warn" && item.rule !== "AGENTS_5_secrets")) {
    lines.push(`${LABELS.rule[check.rule]}: ${check.detail}`);
  }
  for (const action of output?.next_actions ?? []) lines.push(`(${LABELS.owner[action.owner]}) ${action.action}`);
  const unique = [...new Set(lines)].slice(0, 3);
  if (!unique.length) unique.push("지금 할 일 없음. 검토를 기다려 주세요.");
  return unique;
}

function claimBlocks(claims = []) {
  return claims.map((claim) => bulleted(toRichText([
    { text: `${LABELS.basis[claim.basis]} `, bold: true },
    { text: claim.text },
    ...(claim.evidence?.length ? [{ text: `  (근거: ${claim.evidence.join(", ")})`, italic: true }] : []),
  ])));
}

function findingBlock(analysis, finding) {
  const location = finding.line ? `${finding.file} ${finding.line}번째 줄` : finding.file;
  const meta = `${LABELS.category[finding.category]} · ${LABELS.basis[finding.basis]} · AI 확신도 ${LABELS.confidence[finding.confidence]} · ${finding.anchor_found ? "위치 확인됨" : "위치 미확인(참고용)"}`;
  return bulleted(
    toRichText([
      { text: `[${finding.id}] `, bold: true },
      { text: `[${LABELS.severity[finding.severity]}] ${finding.title} — ` },
      { text: location, link: fileLink(analysis, finding.file, finding.line) },
    ]),
    [paragraph(text(meta)), paragraph(text(`근거: ${finding.evidence}`)), paragraph(text(`제안: ${finding.suggestion}`))]
  );
}

const tokens = (usage) => usage ? `입력 ${(usage.input ?? 0) + (usage.cache_read ?? 0) + (usage.cache_write ?? 0)}토큰 / 출력 ${usage.output ?? 0}토큰` : "-";

// 분석 결과로 PR 행 제목·속성·본문 블록과 다음 실행에 쓸 상태 JSON을 만든다. previousSeq는 지난 상태의 기록 차수다.
export function renderReport(analysis, previousHistory = [], previousSeq = previousHistory.length) {
  const { pr, readiness, output, findings, ci, conflict, prechecks, llm, coverage } = analysis;
  const readinessLabel = LABELS.readiness[readiness.state];
  const reasonText = readiness.reasons.map((item) => item.reason).join(", ");
  const goal = output
    ? `${LABELS.goal[output.goal_fit.rating]}${output.goal_fit.primary_ref ? ` (${output.goal_fit.primary_ref}${analysis.baseline_draft ? ", 초안 기준" : ""})` : ""}`
    : "AI 분석 없음";
  const blocks = [];

  blocks.push(callout(text(
    "이 페이지 읽는 법: AI가 작업물을 안내서와 비교한 참고 메모입니다(사람 평가 아님). 맨 위 '준비 상태'와 '다음에 할 일'만 먼저 보세요. " +
    "[확인됨] PR에서 직접 확인 · [AI 판단] AI 의견 · [추정] 근거가 약한 짐작 · [확인 못 함] 정보 없음. AI는 틀릴 수 있으니 이상하면 PR 댓글이나 리더에게 알려 주세요."
  ), "📖", "gray_background"));
  blocks.push(callout(toRichText([
    { text: `${output?.summary?.one_line ?? pr.title}\n`, bold: true },
    { text: `준비 상태: ${readinessLabel} — ${reasonText}\n` },
    ...(readiness.if_not_draft ? [{ text: `초안이 아니었다면: ${LABELS.readiness[readiness.if_not_draft[0].state]} — ${readiness.if_not_draft.map((item) => item.reason).join(", ")}\n` }] : []),
    { text: `목표 연결: ${goal}\n` },
    { text: `분석한 버전 ${pr.head_sha.slice(0, 7)} · ${modeText(analysis)} · 범위 ${coverage.state === "full" ? "전체" : `일부(제외 ${coverage.excluded.length}개)`}`, italic: true },
  ]), "🧭", "blue_background"));

  blocks.push(heading(2, text("다음에 할 일")));
  for (const line of nextActions(analysis)) blocks.push(bulleted(text(line)));
  blocks.push(paragraph(text("질문은 PR 댓글이나 리더에게. 수정본을 올리면 몇 분 뒤 자동 갱신됩니다.", { italic: true })));

  if (output?.reviewer_focus?.length) {
    blocks.push(heading(2, text("검토할 때 먼저 볼 곳")));
    for (const focus of output.reviewer_focus.slice(0, 3)) {
      blocks.push(bulleted(toRichText([{ text: focus.file, link: fileLink(analysis, focus.file) }, { text: ` — ${focus.why}` }])));
    }
  }

  blocks.push(heading(2, text("지난 분석 이후 달라진 점")));
  const last = previousHistory.at(-1);
  if (!last) blocks.push(paragraph(text(`첫 분석입니다. 🆕 새로 발견 ${findings.length}건.`)));
  else {
    const before = LABELS.readiness[last.readiness] ?? last.readiness;
    const change = analysis.mode === "none"
      ? "코드 변경 없음(공용본 반영 등) — 지난 AI 결과를 유지했습니다."
      : `${analysis.mode === "incremental" ? `바뀐 파일 ${analysis.changed_files.length}개만 다시 분석했습니다. ` : ""}🆕 이번 분석 확인할 점 ${findings.length}건(지난번 ${last.findings ?? "-"}건).`;
    blocks.push(paragraph(text(`지난 분석 ${last.head}(${last.at ? kst(last.at) : "-"}) → 이번 ${pr.head_sha.slice(0, 7)}. ${change} 준비 상태: ${before} → ${readinessLabel}`)));
  }

  if (output) {
    blocks.push(heading(2, text("무엇을 왜 바꿨나")));
    for (const item of output.summary.what_changed ?? []) blocks.push(bulleted(text(item)));
    blocks.push(paragraph(text(`이유: ${output.summary.why}`)));

    blocks.push(heading(2, text("목표·역할과의 연결")));
    blocks.push(paragraph(text(`목표 연결: ${goal}`)));
    blocks.push(...claimBlocks(output.goal_fit.claims));

    blocks.push(heading(2, text("다른 부분에 주는 영향")));
    blocks.push(paragraph(text(`${LABELS.module[output.module_fit.rating]} · ${LABELS.impact[output.module_fit.contract_impact]} · 태그: ${analysis.tags.join(", ") || "없음"}`)));
    blocks.push(...claimBlocks(output.module_fit.claims));
  }

  blocks.push(heading(2, text("팀 규칙 점검")));
  const rows = [[text("항목"), text("결과"), text("내용")]];
  rows.push([
    text("자동 검사"),
    text(LABELS.ci[ci.state] ?? ci.state),
    text(Object.entries(ci.jobs).map(([name, value]) => `${LABELS.job[name] ?? name}: ${LABELS.conclusion[value] ?? value}`).join(", ") || "실행 기록 없음"),
  ]);
  rows.push([
    text("충돌"),
    text(conflict.state === "conflict" ? "❌ 보완 필요" : conflict.state === "clean" ? "✅ 문제 없음" : "⏳ 충돌 확인 중"),
    text(conflict.files.join(", ") || "충돌 파일 없음"),
  ]);
  for (const check of prechecks) rows.push([text(LABELS.check[check.rule]), text(LABELS.status[check.status]), text(check.detail)]);
  blocks.push(table(rows));

  blocks.push(heading(2, text("AI가 찾은 확인할 점")));
  const major = findings.filter((item) => ["blocker", "major"].includes(item.severity));
  const minor = findings.filter((item) => ["minor", "info"].includes(item.severity));
  if (!findings.length) blocks.push(paragraph(text(output ? "AI가 찾은 확인할 점이 없습니다." : "AI 분석이 실행되지 않았습니다.")));
  for (const finding of major) blocks.push(findingBlock(analysis, finding));
  if (minor.length) blocks.push(toggle(text(`작은 개선·참고 ${minor.length}건 (펼치기)`), minor.slice(0, 6).map((finding) => findingBlock(analysis, finding))));

  if (output?.author_questions?.length) {
    blocks.push(heading(2, text("작성자에게 확인하고 싶은 점")));
    for (const question of output.author_questions.slice(0, 5)) blocks.push(bulleted(text(question)));
  }

  const entry = { at: analysis.generated_at, head: pr.head_sha.slice(0, 7), mode: analysis.mode, readiness: readiness.state, findings: findings.length, models: llm.models ?? [], usage: llm.usage ?? null };
  const history = [...previousHistory, entry].slice(-8);
  blocks.push(heading(2, text("분석 기록")));
  blocks.push(table([
    [text("시각"), text("버전"), text("방식"), text("준비 상태"), text("모델·토큰")],
    ...history.map((item) => [
      text(item.at ? kst(item.at) : "-"), text(item.head), text(LABELS.mode[item.mode] ?? item.mode),
      text(LABELS.readiness[item.readiness] ?? item.readiness), text(`${(item.models ?? []).join(", ") || "-"} · ${tokens(item.usage)}`),
    ]),
  ]));

  blocks.push(heading(2, text("이 분석의 한계")));
  blocks.push(paragraph(text(
    "PR 제목·설명·변경 내용과 자동 검사 결과를 AI(Claude)가 읽고 안내서(docs/review-baseline.md)와 비교해 만들었습니다. " +
    "코드를 실행해 보지 않았고, 안내서에 없는 내용은 판단하지 않았습니다. AI는 틀릴 수 있으므로 참고용이며 최종 판단은 리더가 합니다."
  )));
  blocks.push(divider());
  blocks.push(heading(2, text("리더 메모")));
  blocks.push(paragraph(text("")));

  const limited = enforceLimits(blocks);
  const properties = {
    "PR 번호": pr.number,
    "PR 링크": pr.url,
    "담당": pr.author,
    "브랜치": pr.branch,
    "상태": pr.draft ? LABELS.prState.draft : LABELS.prState.open,
    "준비 상태": readinessLabel,
    "준비 상태 사유": reasonText,
    "목표 연결": output ? LABELS.goal[output.goal_fit.rating] : "AI 분석 없음",
    "태그": analysis.tags,
    "키워드": analysis.keywords.join(", "),
    "분석 내용": analysisContent(output),
    "꼭 고칠 점": findings.filter((item) => item.severity === "blocker").length,
    "남은 확인": findings.length,
    "자동 검사": LABELS.ci[ci.state] ?? ci.state,
    "분석 방식": LABELS.mode[analysis.mode],
    "분석 상태": LABELS.analysis[llm.status] ?? llm.status,
    "분석한 버전": pr.head_sha.slice(0, 7),
    "마지막 분석": analysis.generated_at,
    "한 줄 요약": output?.summary?.one_line ?? pr.title,
  };
  const state = {
    v: STATE_VERSION,
    analyzer: analysis.analyzer,
    head: pr.head_sha,
    merge_base: analysis.merge_base,
    mode: analysis.mode,
    coverage: coverage.state,
    excluded: coverage.excluded,
    tags: analysis.tags,
    keywords: analysis.keywords,
    context_used: analysis.context_used ?? null,
    llm: { status: llm.status, models: llm.models, usage: llm.usage },
    files: Object.fromEntries(analysis.files.map((file) => [file.path, { sig: file.sig }])),
    output,
    findings: findings.map(({ id, severity, category, file, line, title, kind, anchor_found }) => ({ id, severity, category, file, line, title, kind, anchor_found, status: "open" })),
    history,
    seq: (previousSeq || 0) + 1,
  };
  return {
    title: `[PR #${pr.number}] ${pr.title}`,
    properties,
    blocks: limited,
    block_count: limited.reduce((sum, item) => sum + countBlocks(item), 0),
    state,
  };
}
