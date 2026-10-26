// 분석 결과를 Notion PR 페이지(속성 + 본문 블록)로 바꾼다. 네트워크 호출은 하지 않는다.
// 페이지 본문은 세 구획이다. ① 보고서(분석마다 새로 씀) ② 서비스 아키텍처 그림(PR당 한 번 생성) ③ 리더 메모(자동 갱신이 건드리지 않음).
// AI 구획은 마지막으로 '성공한' GPT 분석 결과를 그 기준 버전과 함께 보여 주고, 현재 버전의 AI 실패·생략은 따로 표시한다.
import { bulleted, callout, code, countBlocks, divider, enforceLimits, heading, paragraph, table, text, toRichText, toggle } from "../notion/blocks.mjs";
import { analysisContent } from "./cards.mjs";
import { LABELS } from "./labels.mjs";
import { sha256 } from "./lib.mjs";

// 상태 JSON 형식 버전. 바뀌면 다음 수정본은 처음부터 전체 분석한다.
export const STATE_VERSION = 3;
export const DIAGRAM_HEADING = "서비스 아키텍처 (PR 최초 분석 시점)";
export const MEMO_HEADING = "리더 메모";

export const kst = (iso) => `${new Date(iso).toLocaleString("sv-SE", { timeZone: "Asia/Seoul" }).slice(0, 16)} KST`;
const short = (sha) => String(sha ?? "").slice(0, 7);
const fileLink = (analysis, path, line) =>
  `https://github.com/${analysis.repo}/pull/${analysis.pr.number}/files#diff-${sha256(path)}${line ? `R${line}` : ""}`;

// 사용량 한 줄. 캐시는 입력의 일부, 추론은 출력의 일부이므로 더하지 않고 괄호로 보여 준다.
export const usageText = (usage) =>
  usage ? `입력 ${usage.input}(캐시 ${usage.cached}) / 출력 ${usage.output}(추론 ${usage.reasoning}) 토큰` : "-";

const modeText = (analysis) =>
  `${LABELS.mode[analysis.mode] ?? analysis.mode}${analysis.mode === "incremental" ? `(바뀐 파일 ${analysis.scope.changed.length}개)` : ""}`;

// 현재 버전에 대한 AI 시도 결과 한 줄('마지막 시도' 열)
export function attemptText(attempt) {
  const head = short(attempt.head);
  if (attempt.status === "done" || attempt.status === "partial") return `${head} ${LABELS.analysis[attempt.status]} · ${attempt.response_model ?? attempt.model}`;
  if (attempt.status === "failed") return `${head} AI 분석 실패: ${LABELS.error[attempt.error_class] ?? attempt.error_class}${attempt.retry_after_at ? ` · ${kst(attempt.retry_after_at)} 이후 다시 실행 가능(자동 재실행 없음)` : ""}`;
  return `${head} AI 호출 안 함: ${LABELS.skip[attempt.skip_reason] ?? attempt.skip_reason}`;
}

// '다음에 할 일': 보안 → 검사 → 충돌 → 꼭 고칠 점 → 팀 규칙 → AI 제안 순으로 최대 3개.
export function nextActions(analysis) {
  const lines = [];
  const { ci, conflict, prechecks, findings, output } = analysis;
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

// '병합 판단' 열과 맨 위 상자에 쓰는 한 줄. 자동 점검으로 낮춘 경우 이유에 '(AI 원래 판단: …)'이 들어 있다.
export function judgmentLine(judgment) {
  if (!judgment) return "AI 판단 없음";
  return `${LABELS.verdict[judgment.verdict]} — ${judgment.reason || "이유 없음"}`;
}

// 판단 근거 세 문장을 블릿 줄로 만든다.
export const rationaleText = (judgment) => (judgment?.rationale ?? []).map((line) => `• ${line}`).join("\n");

function judgmentCallout(judgment, aiNote) {
  const title = toRichText([{ text: "병합 판단(AI 참고): ", bold: true }, { text: judgmentLine(judgment) }, ...(aiNote ? [{ text: `\n${aiNote}`, italic: true }] : [])]);
  const children = (judgment?.rationale ?? []).map((line) => bulleted(text(line)));
  return callout(title, "⚖️", "yellow_background", children.length ? children : undefined);
}

// AI 결과 안내 한 줄. 성공·실패·호출 안 함을 앞 표시로 구분하고, AI 내용이 현재 버전의 것이 아니면 기준 버전을 밝힌다.
export function aiNote(analysis) {
  const { ai, pr } = analysis;
  const errorText = LABELS.error[ai.error_class] ?? ai.error_class;
  const skipText = LABELS.skip[ai.skip_reason] ?? ai.skip_reason;
  if (!analysis.output) return ai.status === "failed" ? `❌ AI 분석 실패: ${errorText}. 규칙 점검 결과만 보입니다.` : `➖ AI 분석 안 함: ${skipText}. 규칙 점검 결과만 보입니다.`;
  const basis = `AI 내용 기준 버전 ${short(ai.head)} · ${ai.provider} ${ai.response_model ?? ai.model} · ${ai.at ? kst(ai.at) : "-"}`;
  if (ai.head === pr.head_sha) return `✅ ${LABELS.analysis[ai.status] ?? ai.status} · ${basis}`;
  if (ai.status === "reused") return `✅ ${LABELS.analysis.reused} · ${basis}`;
  const why = ai.status === "failed" ? `❌ 이번 버전 ${short(pr.head_sha)} AI 분석 실패: ${errorText}` : `➖ 이번 버전 ${short(pr.head_sha)}은 AI를 부르지 않음: ${skipText}`;
  return `${why}. 아래 AI 내용은 ${basis}의 결과입니다.`;
}

// 분석 결과로 PR 페이지 제목·속성·보고서 블록을 만든다. history는 이번 실행까지의 분석 기록(최근 것이 끝)이다.
export function renderReport(analysis, history = []) {
  const { pr, readiness, output, findings, ci, conflict, prechecks, coverage, ai } = analysis;
  const readinessLabel = LABELS.readiness[readiness.state];
  const reasonText = readiness.reasons.map((item) => item.reason).join(", ");
  const goal = output
    ? `${LABELS.goal[output.goal_fit.rating]}${output.goal_fit.primary_ref ? ` (${output.goal_fit.primary_ref}${analysis.baseline_draft ? ", 초안 기준" : ""})` : ""}`
    : "AI 분석 없음";
  const note = aiNote(analysis);
  const scopeText = coverage.state === "full" ? "전체" : `일부(AI가 보지 못한 파일 ${coverage.excluded.length}개)`;
  const blocks = [];

  blocks.push(callout(text(
    "이 페이지 읽는 법: AI가 작업물을 안내서와 비교한 참고 메모입니다(사람 평가 아님). 맨 위 '준비 상태'와 '다음에 할 일'만 먼저 보세요. " +
    "[확인됨] PR에서 직접 확인 · [AI 판단] AI 의견 · [추정] 근거가 약한 짐작 · [확인 못 함] 정보 없음. AI는 틀릴 수 있으니 이상하면 PR 댓글이나 리더에게 알려 주세요. " +
    "메모는 맨 아래 '리더 메모'에 적어 주세요(자동 갱신이 지우지 않습니다)."
  ), "📖", "gray_background"));
  blocks.push(callout(toRichText([
    { text: `${output?.summary?.one_line ?? pr.title}\n`, bold: true },
    { text: `준비 상태: ${readinessLabel} — ${reasonText}\n` },
    { text: `목표 연결: ${goal}\n` },
    { text: `현재 버전 ${short(pr.head_sha)} · 이번 실행: ${modeText(analysis)} · AI가 본 범위: ${scopeText}\n`, italic: true },
    { text: note, italic: true },
  ]), "🧭", "blue_background"));
  blocks.push(judgmentCallout(analysis.judgment, analysis.judgment && ai.head !== pr.head_sha ? `기준 버전 ${short(ai.head)}의 판단` : ""));

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
  const last = history.at(-2);
  if (!last) blocks.push(paragraph(text(`첫 분석입니다. 확인할 점 ${findings.length}건.`)));
  else {
    const before = LABELS.readiness[last.readiness] ?? last.readiness;
    const change = analysis.mode === "none"
      ? "PR 변경 내용이 지난 성공 분석과 같아 AI를 다시 부르지 않았습니다."
      : analysis.mode === "incremental"
        ? `바뀐 파일 ${analysis.scope.changed.length}개만 다시 분석했습니다. 새 지적 ${analysis.scope.added ?? 0}건, 닫힌 지적 ${analysis.scope.closed ?? 0}건.`
        : `확인할 점 ${findings.length}건(지난번 ${last.findings ?? "-"}건).`;
    blocks.push(paragraph(text(`지난 실행 ${last.head}(${last.at ? kst(last.at) : "-"}) → 이번 ${short(pr.head_sha)}. ${change} 준비 상태: ${before} → ${readinessLabel}`)));
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
  if (!findings.length) blocks.push(paragraph(text(output ? "AI가 찾은 확인할 점이 없습니다." : "AI 분석 결과가 없습니다.")));
  for (const finding of major) blocks.push(findingBlock(analysis, finding));
  if (minor.length) blocks.push(toggle(text(`작은 개선·참고 ${minor.length}건 (펼치기)`), minor.slice(0, 6).map((finding) => findingBlock(analysis, finding))));

  if (output?.author_questions?.length) {
    blocks.push(heading(2, text("작성자에게 확인하고 싶은 점")));
    for (const question of output.author_questions.slice(0, 5)) blocks.push(bulleted(text(question)));
  }

  if (analysis.scope.excluded?.length || analysis.scope.no_patch?.length || analysis.scope.truncated?.length) {
    blocks.push(heading(2, text("이번 분석에서 보지 못한 범위")));
    if (analysis.scope.excluded?.length) blocks.push(bulleted(text(`입력 예산으로 patch를 넣지 못한 파일: ${analysis.scope.excluded.join(", ")}`)));
    if (analysis.scope.no_patch?.length) blocks.push(bulleted(text(`GitHub가 patch를 주지 않은 파일(바이너리·대용량 등): ${analysis.scope.no_patch.join(", ")}`)));
    if (analysis.scope.truncated?.length) blocks.push(bulleted(text(`일부만 넣은 참고 자료: ${analysis.scope.truncated.join(", ")}`)));
  }

  blocks.push(heading(2, text("분석 기록")));
  blocks.push(table([
    [text("시각"), text("버전"), text("방식"), text("AI 결과"), text("준비 상태"), text("모델·토큰")],
    ...history.slice(-8).map((item) => [
      text(item.at ? kst(item.at) : "-"), text(item.head), text(LABELS.mode[item.mode] ?? item.mode),
      text(item.result ?? "-"), text(LABELS.readiness[item.readiness] ?? item.readiness), text(`${item.model ?? "-"} · ${usageText(item.usage)}`),
    ]),
  ]));

  blocks.push(heading(2, text("이 분석의 한계")));
  blocks.push(paragraph(text(
    "PR 제목·설명·변경 내용과 자동 검사 결과를 AI(OpenAI GPT, API)가 읽고 안내서(docs/review-baseline.md)와 비교해 만들었습니다. " +
    "코드를 실행해 보지 않았고, 안내서에 없는 내용은 판단하지 않았습니다. AI는 틀릴 수 있으므로 참고용이며 최종 판단은 리더가 합니다."
  )));

  const limited = enforceLimits(blocks);
  const properties = {
    "PR 번호": pr.number,
    "PR 링크": pr.url,
    "저장소": analysis.repo,
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
    "분석 상태": LABELS.analysis[ai.status] ?? ai.status,
    "분석한 버전": output ? short(ai.head) : "",
    "현재 버전": short(pr.head_sha),
    "마지막 시도": attemptText(analysis.attempt),
    "AI 모델": output ? `${ai.provider} · ${ai.response_model ?? ai.model}` : "",
    "마지막 분석": analysis.generated_at,
    "한 줄 요약": output?.summary?.one_line ?? pr.title,
    "병합 판단": analysis.judgment ? LABELS.verdict[analysis.judgment.verdict] : null,
    "판단 근거": analysis.judgment ? `${judgmentLine(analysis.judgment)}\n${rationaleText(analysis.judgment)}`.trim() : "AI 판단 없음",
  };
  return {
    title: `[PR #${pr.number}] ${pr.title}`,
    properties,
    blocks: limited,
    block_count: limited.reduce((sum, item) => sum + countBlocks(item), 0),
  };
}

// 그림 아래 상태 줄. 첫 줄(최초 생성 버전·시각)은 바꾸지 않고, 이후 수정본이 생기면 둘째 줄을 붙인다.
export function diagramStatusText({ firstLine, latestHead, firstHead }) {
  if (!latestHead || short(latestHead) === short(firstHead)) return firstLine;
  return `${firstLine}\n이후 수정본(${short(latestHead)})이 있어 이 그림은 PR 최초 분석 시점의 구조입니다. 그림은 PR당 한 번만 그립니다.`;
}

export const diagramFirstLine = ({ head, at, note }) => `최초 생성: 버전 ${short(head)} · ${kst(at)}${note ? ` · ${note}` : ""}`;

// 그림 구획: 구분선, 제목, mermaid 코드(캡션), 상태 줄
export function diagramBlocks({ mermaid, caption, statusText }) {
  return [divider(), heading(2, text(DIAGRAM_HEADING)), code(mermaid, "mermaid", caption), paragraph(text(statusText, { italic: true }))];
}

// 리더 메모 구획(처음 만들 때 한 번만 넣는다)
export const memoBlocks = () => [divider(), heading(2, text(MEMO_HEADING)), paragraph(text(""))];
