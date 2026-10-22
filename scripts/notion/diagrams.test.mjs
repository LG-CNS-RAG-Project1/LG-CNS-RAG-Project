// 변경 파일 다이어그램과 아키텍처 강조 다이어그램 생성 테스트

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  architectureDiagram,
  changedFilesDiagram,
  extractMermaidBlocks,
  mermaidLabel,
} from "./diagrams.mjs";

const file = (filename, status = "modified", extra = {}) => ({
  filename,
  status,
  additions: 3,
  deletions: 1,
  ...extra,
});

test("변경 파일을 디렉터리별 노드와 상태 클래스로 표현한다", () => {
  const diagram = changedFilesDiagram(
    [
      file("README.md"),
      file("src/ingestion/kipris_client.py", "added"),
      file("src/ingestion/old.py", "removed"),
      file("docs/new.md", "renamed", { previous_filename: "docs/old.md" }),
    ],
    { rootLabel: "repo" }
  );

  assert.match(diagram, /^flowchart LR\n {2}root\["repo"\]/);
  assert.match(diagram, /d0\["\(루트\)"\]/);
  assert.match(diagram, /\["kipris_client\.py \+3\/-1"\]:::added/);
  assert.match(diagram, /\["old\.py \+3\/-1"\]:::removed/);
  assert.match(diagram, /\["new\.md \(이름 변경\) \+3\/-1"\]:::renamed/);
  assert.match(diagram, /classDef added /);
});

test("파일이 많으면 디렉터리 단위로 집계한다", () => {
  const files = Array.from({ length: 40 }, (_, i) => file(`src/m${i % 2}/f${i}.py`, "added"));
  const diagram = changedFilesDiagram(files);
  assert.match(diagram, /src\/m0\/ · 20개 · \+60\/-20"\]:::added/);
  assert.doesNotMatch(diagram, /f0\.py/);
});

test("변경 파일이 없으면 다이어그램을 만들지 않는다", () => {
  assert.equal(changedFilesDiagram([]), null);
});

test("mermaid 라벨의 따옴표·꺾쇠·백틱을 엔티티로 바꾼다", () => {
  assert.equal(mermaidLabel('a"b<c>`d'), "a#quot;b#lt;c#gt;#96;d");
});

const architecture = [
  "# 설계",
  "",
  "```mermaid",
  "sequenceDiagram",
  "  A->>B: 매핑 없는 다이어그램",
  "```",
  "",
  "```mermaid",
  "flowchart LR",
  '  ingestion["수집"] --> retrieval["검색"]',
  "  %% map src/ingestion/ ingestion",
  "  %% map src/retrieval/ retrieval",
  "  %% map Dockerfile retrieval",
  "```",
].join("\n");

test("문서에서 mermaid 코드 펜스를 추출한다", () => {
  assert.equal(extractMermaidBlocks(architecture).length, 2);
});

test("매핑된 경로가 바뀐 노드만 강조한다", () => {
  const result = architectureDiagram(architecture, [
    file("src/ingestion/dart_client.py"),
    file("tests/test_api.py"),
  ]);

  assert.deepEqual(result.changed, [{ node: "ingestion", prefixes: ["src/ingestion/"] }]);
  assert.match(result.mermaid, /classDef changed /);
  assert.match(result.mermaid, /class ingestion changed$/);
  assert.doesNotMatch(result.mermaid, /sequenceDiagram/);
});

test("슬래시로 끝나지 않는 매핑은 정확한 파일 또는 하위 경로만 일치시킨다", () => {
  const result = architectureDiagram(architecture, [file("Dockerfile.dev")]);
  assert.deepEqual(result.changed, []);
  assert.doesNotMatch(result.mermaid, /classDef changed/);
});

test("이름이 바뀐 파일은 이전 경로도 매핑에 사용한다", () => {
  const result = architectureDiagram(architecture, [
    file("archive/kipris.py", "renamed", { previous_filename: "src/ingestion/kipris.py" }),
  ]);
  assert.deepEqual(result.changed.map(({ node }) => node), ["ingestion"]);
});

test("매핑이 있는 mermaid 다이어그램이 없으면 null을 반환한다", () => {
  assert.equal(architectureDiagram("```mermaid\nflowchart LR\n  A-->B\n```", []), null);
});
