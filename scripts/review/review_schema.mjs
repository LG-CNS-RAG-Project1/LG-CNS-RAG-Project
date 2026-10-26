// PR 분석 응답의 JSON 스키마(OpenAI Structured Outputs strict 형식)를 만든다.
// 영역 카드 변경 후보(candidate_card_delta)의 태그는 이번 분석에 넘긴 카드 태그로만 제한하므로 요청마다 스키마를 만든다.
import { sha256 } from "./lib.mjs";

const string = { type: "string" };
const strings = (maxItems) => ({ type: "array", items: string, ...(maxItems === undefined ? {} : { maxItems }) });
const object = (properties) => ({ type: "object", additionalProperties: false, required: Object.keys(properties), properties });
const oneOf = (values) => ({ type: "string", enum: values });
const BASIS = oneOf(["fact", "interpretation", "assumption", "unverified"]);
const claims = { type: "array", maxItems: 6, items: object({ text: string, basis: BASIS, evidence: strings(5) }) };

export const SCHEMA_NAME = "pr_review";

export function buildReviewSchema(cardTags = []) {
  const tags = cardTags.length ? cardTags : ["-"];
  return object({
    head_sha: string,
    summary: object({ one_line: string, what_changed: strings(6), why: string }),
    goal_fit: object({
      rating: oneOf(["aligned", "partial", "unclear", "misaligned", "no_baseline"]),
      primary_ref: string,
      baseline_refs: strings(6),
      claims,
    }),
    module_fit: object({
      rating: oneOf(["within_role", "cross_boundary_ok", "cross_boundary_unagreed", "unclear", "no_role_data"]),
      touched_modules: strings(10),
      contract_impact: oneOf(["none", "additive", "breaking", "unclear"]),
      claims,
    }),
    findings: {
      type: "array",
      maxItems: 8,
      items: object({
        kind: oneOf(["presence", "absence"]),
        severity: oneOf(["blocker", "major", "minor", "info"]),
        category: oneOf(["bug", "data_contract", "security", "test_gap", "performance", "docs", "other"]),
        file: string,
        anchor: string,
        side: oneOf(["new", "old"]),
        title: string,
        evidence: string,
        suggestion: string,
        basis: BASIS,
        confidence: oneOf(["high", "medium", "low"]),
      }),
    },
    prior_findings: {
      type: "array",
      maxItems: 30,
      items: object({ id: string, status: oneOf(["still_open", "resolved", "obsolete", "uncertain"]), note: string }),
    },
    process_judgements: {
      type: "array",
      maxItems: 6,
      items: object({
        rule: oneOf(["AGENTS_2_scope", "AGENTS_4_docs", "AGENTS_5_secrets", "AGENTS_6_comments", "AGENTS_8_commits", "template"]),
        status: oneOf(["ok", "warn", "fail", "n/a"]),
        evidence: string,
      }),
    },
    next_actions: { type: "array", maxItems: 3, items: object({ owner: oneOf(["author", "leader", "team"]), action: string }) },
    reviewer_focus: { type: "array", maxItems: 3, items: object({ file: string, why: string }) },
    author_questions: strings(5),
    readiness_proposal: object({ level: oneOf(["ready", "leader_look", "discuss", "needs_fix"]), reason: string }),
    digest: string,
    rationale: object({ result: string, causality: string, basis: string }),
    judgment: object({ verdict: oneOf(["merge_ok", "fix_then_merge", "discuss", "hold"]), reason: string }),
    candidate_card_delta: {
      type: "array",
      // 카드 태그가 없으면 '-' 한 값만 허용하고, 그런 항목은 검증 단계에서 버린다.
      maxItems: Math.max(1, Math.min(cardTags.length, 5)),
      items: object({
        tag: oneOf(tags),
        scope_add: strings(5),
        contracts_upsert: {
          type: "array",
          maxItems: 8,
          items: object({ key: string, text: string, evidence_file: string, evidence_symbol: string }),
        },
        contracts_remove: strings(8),
      }),
    },
  });
}

// 스키마 버전: 태그 목록과 무관한 틀의 해시
export const SCHEMA_VERSION = sha256(JSON.stringify(buildReviewSchema(["__tag__"]))).slice(0, 12);
