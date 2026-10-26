// Notion 블록 생성과 요청 제한 처리 테스트

import assert from "node:assert/strict";
import { test } from "node:test";

import { bulleted, chunkBlocks, code, codeLanguage, enforceLimits, splitText, table, text, toRichText } from "./blocks.mjs";

const plain = (richText) => richText.map((item) => item.text.content).join("");
const types = (blocks) => blocks.map((block) => block.type);

test("rich text는 2000자 단위로 나누고 서로게이트 쌍을 끊지 않는다", () => {
  const value = `${"a".repeat(1999)}😀b`;
  const parts = splitText(value);
  assert.deepEqual(
    parts.map((part) => part.length),
    [1999, 3]
  );
  assert.equal(toRichText([{ text: "x".repeat(4500) }]).length, 3);
});

test("긴 코드 블록은 rich text 배열 100개 이내로 유지하고 캡션을 붙인다", () => {
  const block = code("가".repeat(250_000), "text", "캡션");
  assert.equal(block.code.language, "plain text");
  assert.ok(block.code.rich_text.length <= 100);
  assert.match(plain(block.code.rich_text), /이하 150000자 생략/);
  assert.equal(plain(block.code.caption), "캡션");
});

test("코드 언어 별칭을 Notion 언어로 바꾼다", () => {
  assert.equal(codeLanguage("py"), "python");
  assert.equal(codeLanguage("Dockerfile"), "docker");
  assert.equal(codeLanguage("mermaid"), "mermaid");
  assert.equal(codeLanguage("toml"), "plain text");
});

test("중첩 깊이를 넘는 표는 코드 블록으로 바꾼다", () => {
  const grid = table([[text("a"), text("b")], [text("1"), text("2")]]);
  const blocks = enforceLimits([bulleted(text("1단계"), [bulleted(text("2단계"), [bulleted(text("3단계")), grid])])]);
  const third = blocks[0].bulleted_list_item.children[0].bulleted_list_item.children;
  assert.deepEqual(types(third), ["bulleted_list_item", "code"]);
  assert.equal(plain(third[1].code.rich_text), "a | b\n1 | 2");
});

test("블록 묶음을 최상위 100개 단위로 나눈다", () => {
  const blocks = Array.from({ length: 250 }, (_, index) => bulleted(text(`항목 ${index}`)));
  const batches = chunkBlocks(blocks);
  assert.deepEqual(
    batches.map((batch) => batch.length),
    [100, 100, 50]
  );
});
