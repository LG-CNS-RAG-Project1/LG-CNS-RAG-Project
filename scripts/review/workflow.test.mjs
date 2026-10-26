// 운영 경로 점검: 워크플로 구조(신뢰된 develop 스크립트만 실행·초안 제외·키 전달 범위·카드 직렬화)와 Claude 호출 경로가 없는지 확인한다.
import assert from "node:assert/strict";
import { readdirSync, readFileSync } from "node:fs";
import { test } from "node:test";

const ROOT = new URL("../../", import.meta.url);
const read = (path) => readFileSync(new URL(path, ROOT), "utf8");
const workflow = read(".github/workflows/pr-analysis.yml");
const jobs = Object.fromEntries(workflow.split(/\n  (?=[a-z-]+:\n)/).slice(1).map((chunk) => [chunk.split(":")[0], chunk]));

test("운영 경로(워크플로·자동화 스크립트·Makefile)에 Claude CLI·Anthropic 호출·Claude 인증 참조가 없다", () => {
  const operational = [
    ...readdirSync(new URL(".github/workflows/", ROOT)).map((name) => `.github/workflows/${name}`),
    ...readdirSync(new URL("scripts/review/", ROOT)).filter((name) => name.endsWith(".mjs") && !name.endsWith(".test.mjs") && name !== "fakes.mjs").map((name) => `scripts/review/${name}`),
    ...readdirSync(new URL("scripts/review/prompts/", ROOT)).map((name) => `scripts/review/prompts/${name}`),
    ...readdirSync(new URL("scripts/notion/", ROOT)).filter((name) => !name.endsWith(".test.mjs")).map((name) => `scripts/notion/${name}`),
    "Makefile",
  ];
  for (const path of operational) {
    const text = read(path);
    for (const pattern of [/claude/i, /anthropic/i, /CLAUDE_CODE/]) assert.ok(!pattern.test(text), `${path}: ${pattern}`);
  }
  assert.ok(!/npm install -g/.test(workflow), "CLI 설치 단계 없음");
});

test("pull_request_target 잡은 모두 develop 스크립트만 받고 자격 증명을 남기지 않는다", () => {
  assert.match(workflow, /pull_request_target:/);
  for (const name of ["analyze", "cards", "notion-check"]) {
    assert.match(jobs[name], /ref: develop/, name);
    assert.match(jobs[name], /persist-credentials: false/, name);
    assert.match(jobs[name], /name: pr-analysis\n\s+deployment: false/, name);
  }
  assert.ok(!/github\.event\.pull_request\.head\.(sha|ref)/.test(workflow.replace(/head\.repo\.full_name/g, "")), "PR head를 checkout하지 않음");
});

test("초안 PR은 잡 단계에서 제외하고(초안 전환·닫힘만 실행), API 키는 분석 단계에만·닫힘·초안 전환에는 넘기지 않는다", () => {
  assert.match(jobs.analyze, /github\.event\.pull_request\.draft != true \|\| github\.event\.action == 'closed' \|\| github\.event\.action == 'converted_to_draft'/);
  assert.equal(workflow.split("\n").filter((line) => line.includes("OPENAI_API_KEY")).length, 1);
  assert.match(jobs.analyze, /OPENAI_API_KEY: \$\{\{ github\.event\.action != 'closed' && github\.event\.action != 'converted_to_draft' && secrets\.OPENAI_API_KEY \|\| '' \}\}/);
  assert.ok(!/OPENAI_API_KEY/.test(jobs.cards) && !/OPENAI_API_KEY/.test(jobs["notion-check"]));
  assert.match(jobs.analyze, /NOTION_REVIEW_TOKEN: \$\{\{ inputs\.task != 'verify-model' && secrets\.NOTION_REVIEW_TOKEN \|\| '' \}\}/);
  assert.match(jobs.analyze, /DRY_RUN: \$\{\{ inputs\.task == 'verify-model' && '1' \|\| '' \}\}/);
});

test("같은 PR 실행은 차례로, 카드 반영은 저장소 전체에서 한 줄로 세워 처리한다", () => {
  assert.ok(workflow.includes("group: pr-analysis-${{ inputs.task == 'verify-model' && 'verify-' || '' }}${{ github.event.pull_request.number || inputs.pr_number || 'notion-check' }}\n  cancel-in-progress: false"));
  assert.match(jobs.cards, /group: pr-analysis-cards\n\s+cancel-in-progress: false\n\s+queue: max/);
  assert.match(jobs.cards, /needs: analyze/);
  assert.match(jobs.cards, /REVIEW_STEP: cards/);
});
