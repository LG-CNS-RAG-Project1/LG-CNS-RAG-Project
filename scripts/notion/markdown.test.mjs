// GFM → Notion 블록 변환과 요청 제한 처리 테스트

import assert from "node:assert/strict";
import { test } from "node:test";

import { chunkBlocks, code, codeLanguage, enforceLimits, splitText, toRichText } from "./blocks.mjs";
import { inlineRichText, markdownToBlocks } from "./markdown.mjs";

const plain = (richText) => richText.map((item) => item.text.content).join("");
const types = (blocks) => blocks.map((block) => block.type);

test("PR 본문의 제목·목록·인라인 서식을 Notion 블록으로 변환한다", () => {
  const body = [
    "## GitHub PR 문서화 자동화",
    "",
    "`develop`을 대상으로 병합된 PR을 **Notion**에 기록한다.",
    "",
    "### 설정",
    "",
    "1. Notion 연결을 공유한다.",
    "2. **Settings → Secrets**에서 `NOTION_API_TOKEN`을 저장한다.",
  ].join("\n");

  const blocks = markdownToBlocks(body, { baseHeading: 3 });
  assert.deepEqual(types(blocks), [
    "heading_3",
    "paragraph",
    "paragraph",
    "numbered_list_item",
    "numbered_list_item",
  ]);
  assert.equal(plain(blocks[0].heading_3.rich_text), "GitHub PR 문서화 자동화");

  const intro = blocks[1].paragraph.rich_text;
  assert.equal(plain(intro), "develop을 대상으로 병합된 PR을 Notion에 기록한다.");
  assert.deepEqual(intro[0].annotations, { code: true });
  assert.deepEqual(intro.find((item) => item.text.content === "Notion").annotations, {
    bold: true,
  });

  assert.equal(plain(blocks[2].paragraph.rich_text), "설정");
  assert.deepEqual(blocks[2].paragraph.rich_text[0].annotations, { bold: true });
  assert.equal(
    plain(blocks[4].numbered_list_item.rich_text),
    "Settings → Secrets에서 NOTION_API_TOKEN을 저장한다."
  );
});

test("체크박스·중첩 목록·HTML 주석을 처리한다", () => {
  const body = [
    "<!-- 작성 안내: 이 주석은 표시되지 않는다 -->",
    "- [x] 완료 항목",
    "- [ ] 남은 항목",
    "- [ ]",
    "- 상위",
    "  - 하위",
    "    - 하위의 하위",
    "      - 네 번째 단계",
  ].join("\n");

  const blocks = markdownToBlocks(body);
  assert.deepEqual(types(blocks), ["to_do", "to_do", "bulleted_list_item"]);
  assert.equal(blocks[0].to_do.checked, true);
  assert.equal(blocks[1].to_do.checked, false);

  const child = blocks[2].bulleted_list_item.children[0];
  const grandChildren = child.bulleted_list_item.children;
  assert.equal(plain(grandChildren[0].bulleted_list_item.rich_text), "하위의 하위");
  assert.equal(grandChildren[0].bulleted_list_item.children, undefined);
  assert.equal(plain(grandChildren[1].bulleted_list_item.rich_text), "네 번째 단계");
});

test("코드 펜스 안의 주석과 마크다운은 그대로 보존하고 mermaid 언어를 유지한다", () => {
  const body = [
    "```mermaid",
    "flowchart LR",
    "  A[**입력**] --> B",
    "```",
    "",
    "```yml",
    "# <!-- 코드 안 주석 -->",
    "key: value",
    "```",
  ].join("\n");

  const blocks = markdownToBlocks(body);
  assert.deepEqual(types(blocks), ["code", "code"]);
  assert.equal(blocks[0].code.language, "mermaid");
  assert.equal(plain(blocks[0].code.rich_text), "flowchart LR\n  A[**입력**] --> B");
  assert.equal(blocks[1].code.language, "yaml");
  assert.equal(plain(blocks[1].code.rich_text), "# <!-- 코드 안 주석 -->\nkey: value");
});

test("코드 펜스 밖에서 시작한 여러 줄 주석은 안의 코드 펜스까지 제거한다", () => {
  const body = ["<!--", "```mermaid", "flowchart LR", "```", "-->", "본문"].join("\n");
  const blocks = markdownToBlocks(body);
  assert.deepEqual(types(blocks), ["paragraph"]);
  assert.equal(plain(blocks[0].paragraph.rich_text), "본문");
});

test("표·인용·GitHub 알림·구분선을 변환한다", () => {
  const body = [
    "| 항목 | 값 |",
    "| --- | :-: |",
    "| `a` | 1 |",
    "",
    "> 인용문",
    "",
    "> [!WARNING]",
    "> 토큰을 커밋하지 않는다.",
    "",
    "---",
  ].join("\n");

  const blocks = markdownToBlocks(body);
  assert.deepEqual(types(blocks), ["table", "quote", "callout", "divider"]);
  assert.equal(blocks[0].table.table_width, 2);
  assert.equal(blocks[0].table.children.length, 2);
  assert.equal(blocks[2].callout.icon.emoji, "⚠️");
  assert.equal(plain(blocks[2].callout.rich_text), "토큰을 커밋하지 않는다.");
});

test("링크·이슈 번호·상대 경로·이스케이프를 처리한다", () => {
  const context = {
    repoUrl: "https://github.com/org/repo",
    blobBase: "https://github.com/org/repo/blob/abc",
  };
  const richText = inlineRichText(
    "[문서](docs/a.md) #12 https://example.com/x. \\*별표\\* snake_case_name",
    context
  );

  assert.equal(plain(richText), "문서 #12 https://example.com/x. *별표* snake_case_name");
  assert.equal(richText[0].text.link.url, "https://github.com/org/repo/blob/abc/docs/a.md");
  assert.equal(
    richText.find((item) => item.text.content === "#12").text.link.url,
    "https://github.com/org/repo/issues/12"
  );
  assert.equal(
    richText.find((item) => item.text.content === "https://example.com/x").text.link.url,
    "https://example.com/x"
  );
  assert.ok(richText.every((item) => !item.annotations?.italic));
});

test("앵커 링크처럼 Notion이 받을 수 없는 주소는 링크 없이 텍스트로 남긴다", () => {
  const richText = inlineRichText("[위로](#top)");
  assert.equal(plain(richText), "위로");
  assert.equal(richText[0].text.link, undefined);
});

test("rich text는 2000자 단위로 나누고 서로게이트 쌍을 끊지 않는다", () => {
  const value = `${"a".repeat(1999)}😀b`;
  const parts = splitText(value);
  assert.deepEqual(
    parts.map((part) => part.length),
    [1999, 3]
  );
  assert.equal(toRichText([{ text: "x".repeat(4500) }]).length, 3);
});

test("긴 코드 블록은 rich text 배열 100개 이내로 유지한다", () => {
  const block = code("가".repeat(250_000), "text");
  assert.equal(block.code.language, "plain text");
  assert.ok(block.code.rich_text.length <= 100);
  assert.match(plain(block.code.rich_text), /이하 150000자 생략/);
});

test("코드 언어 별칭을 Notion 언어로 바꾼다", () => {
  assert.equal(codeLanguage("py"), "python");
  assert.equal(codeLanguage("Dockerfile"), "docker");
  assert.equal(codeLanguage("mermaid"), "mermaid");
  assert.equal(codeLanguage("toml"), "plain text");
});

test("중첩 깊이를 넘는 표는 코드 블록으로 바꾼다", () => {
  const body = ["- 1단계", "  - 2단계", "    - 3단계", "", "      | a | b |", "      | - | - |", "      | 1 | 2 |"].join("\n");
  const blocks = enforceLimits(markdownToBlocks(body));
  const third = blocks[0].bulleted_list_item.children[0].bulleted_list_item.children;
  assert.deepEqual(types(third), ["bulleted_list_item", "code"]);
  assert.equal(plain(third[1].code.rich_text), "a | b\n1 | 2");
});

test("블록 묶음을 최상위 100개 단위로 나눈다", () => {
  const blocks = markdownToBlocks(Array.from({ length: 250 }, (_, i) => `- 항목 ${i}`).join("\n"));
  const batches = chunkBlocks(blocks);
  assert.deepEqual(
    batches.map((batch) => batch.length),
    [100, 100, 50]
  );
});
