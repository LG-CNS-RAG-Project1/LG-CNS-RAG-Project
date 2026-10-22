// PR 정보로 Notion 페이지 블록을 구성하는 테스트

import assert from "node:assert/strict";
import { test } from "node:test";

import { chunkBlocks } from "./blocks.mjs";
import { buildPrPage, formatCommits, formatFiles, formatKst } from "./pr_page.mjs";

const pullRequest = {
  number: 7,
  title: "Docker 개발 환경 구성",
  html_url: "https://github.com/org/repo/pull/7",
  body: "## 변경 요약\n\n- `compose.yaml` 추가\n\n```mermaid\nflowchart LR\n  A --> B\n```",
  user: { login: "author" },
  head: { ref: "feature/docker" },
  base: { ref: "develop" },
  merged_at: "2026-10-22T05:13:40Z",
  merged_by: { login: "merger" },
  merge_commit_sha: "0123456789abcdef",
  labels: [{ name: "enhancement" }],
};

const files = [
  { filename: "compose.yaml", status: "added", additions: 10, deletions: 0 },
  { filename: "docs/architecture.md", status: "modified", additions: 5, deletions: 2 },
];

const commits = [
  { sha: "abcdef1234", commit: { message: "Docker 개발 환경 구성\n\n- 본문" }, author: { login: "author" } },
];

const architectureMarkdown = [
  "```mermaid",
  "flowchart LR",
  '  runtime["compose.yaml"]',
  "  %% map compose.yaml runtime",
  "```",
].join("\n");

const plain = (richText) => richText.map((item) => item.text.content).join("");
const headings = (blocks) =>
  blocks.filter((block) => block.type === "heading_2").map((block) => plain(block.heading_2.rich_text));

test("페이지 섹션을 정해진 순서로 구성한다", () => {
  const { title, blocks } = buildPrPage({
    pullRequest,
    files,
    commits,
    repository: "org/repo",
    runUrl: "https://github.com/org/repo/actions/runs/99",
    architectureMarkdown,
  });

  assert.equal(title, "[PR #7] Docker 개발 환경 구성");
  assert.equal(blocks[0].type, "callout");
  assert.match(plain(blocks[0].callout.rich_text), /2026-10-22 14:13 KST 병합 · 파일 2개 \(\+15 \/ -2\)/);
  assert.deepEqual(headings(blocks), [
    "PR 정보",
    "PR 설명 (작성자 제공)",
    "커밋 (1개)",
    "변경 파일 (2개 · +15 / -2)",
    "변경 구조 다이어그램",
    "서비스 연결 구조",
    "문서화 검토 후보",
    "해석 범위",
  ]);
});

test("PR 본문은 변환 블록과 원문 markdown 코드 블록을 함께 넣는다", () => {
  const { blocks } = buildPrPage({ pullRequest, files, commits, repository: "org/repo" });

  const rawToggle = blocks.find((block) => block.type === "toggle");
  assert.equal(plain(rawToggle.toggle.rich_text), "PR 설명 원문 (Markdown)");
  assert.equal(rawToggle.toggle.children[0].code.language, "markdown");
  assert.equal(plain(rawToggle.toggle.children[0].code.rich_text), pullRequest.body);

  const bodyHeading = blocks.find((block) => block.type === "heading_3");
  assert.equal(plain(bodyHeading.heading_3.rich_text), "변경 요약");

  const mermaidBlocks = blocks.filter((block) => block.type === "code" && block.code.language === "mermaid");
  assert.equal(mermaidBlocks.length, 2);
});

test("아키텍처 매핑에 해당하는 변경 모듈을 강조한다", () => {
  const { blocks } = buildPrPage({ pullRequest, files, commits, repository: "org/repo", architectureMarkdown });
  const mermaid = blocks.filter((block) => block.type === "code" && block.code.language === "mermaid");
  assert.match(plain(mermaid.at(-1).code.rich_text), /class runtime changed/);
});

test("본문이 비어 있으면 안내 문단만 넣고 원문 토글은 만들지 않는다", () => {
  const { blocks } = buildPrPage({
    pullRequest: { ...pullRequest, body: null },
    files,
    commits,
    repository: "org/repo",
  });
  assert.equal(blocks.some((block) => block.type === "toggle"), false);
  assert.ok(blocks.some((block) => block.type === "paragraph" && plain(block.paragraph.rich_text) === "PR 설명이 비어 있습니다."));
});

test("변경 파일과 커밋을 고정폭 텍스트로 정리한다", () => {
  assert.equal(
    formatFiles([{ filename: "b.py", previous_filename: "a.py", status: "renamed", additions: 0, deletions: 0 }]),
    "renamed      +0    -0  a.py → b.py"
  );
  assert.equal(formatCommits(commits), "abcdef1  Docker 개발 환경 구성 (author)");
  assert.equal(formatKst(null), "확인할 수 없음");
});

test("파일이 많은 PR도 Notion 요청 제한 안에서 나뉜다", () => {
  const manyFiles = Array.from({ length: 3000 }, (_, i) => ({
    filename: `data/f${i}.json`,
    status: "added",
    additions: 1,
    deletions: 0,
  }));
  const { blocks } = buildPrPage({ pullRequest, files: manyFiles, commits, repository: "org/repo" });
  for (const batch of chunkBlocks(blocks)) {
    assert.ok(batch.length <= 100);
    assert.ok(Buffer.byteLength(JSON.stringify(batch)) < 500_000);
  }
});
