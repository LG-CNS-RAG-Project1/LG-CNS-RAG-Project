// Notion 블록 객체를 만들고 API 요청 크기 제한에 맞게 블록을 정리·분할한다.
// 제한 기준: rich text 2000자, 배열 100개, 중첩 2단계, 요청당 1000블록·500KB.

export const RICH_TEXT_LIMIT = 2000;
export const ARRAY_LIMIT = 100;
export const MAX_NESTING_DEPTH = 2;
export const MAX_CODE_CHARS = 100_000;

const NOTION_CODE_LANGUAGES = new Set([
  "abap", "arduino", "bash", "basic", "c", "clojure", "coffeescript", "c++", "c#",
  "css", "dart", "diff", "docker", "elixir", "elm", "erlang", "flow", "fortran",
  "f#", "gherkin", "glsl", "go", "graphql", "groovy", "haskell", "html", "java",
  "javascript", "json", "julia", "kotlin", "latex", "less", "lisp", "livescript",
  "lua", "makefile", "markdown", "markup", "matlab", "mermaid", "nix",
  "objective-c", "ocaml", "pascal", "perl", "php", "plain text", "powershell",
  "prolog", "protobuf", "python", "r", "reason", "ruby", "rust", "sass", "scala",
  "scheme", "scss", "shell", "sql", "swift", "typescript", "vb.net", "verilog",
  "vhdl", "visual basic", "webassembly", "xml", "yaml", "java/c/c++/c#",
]);

const LANGUAGE_ALIASES = {
  py: "python",
  js: "javascript",
  mjs: "javascript",
  cjs: "javascript",
  jsx: "javascript",
  ts: "typescript",
  tsx: "typescript",
  sh: "shell",
  zsh: "shell",
  console: "shell",
  shellsession: "shell",
  yml: "yaml",
  md: "markdown",
  dockerfile: "docker",
  cpp: "c++",
  cs: "c#",
  csharp: "c#",
  rb: "ruby",
  ps1: "powershell",
  kt: "kotlin",
  text: "plain text",
  txt: "plain text",
  plaintext: "plain text",
};

const ANNOTATION_KEYS = ["bold", "italic", "strikethrough", "code"];

// 코드 펜스의 언어 표기를 Notion이 허용하는 언어 이름으로 바꾼다. 모르는 언어는 plain text.
export function codeLanguage(info) {
  const name = String(info ?? "").trim().split(/\s+/)[0].toLowerCase();
  const language = LANGUAGE_ALIASES[name] ?? name;
  return NOTION_CODE_LANGUAGES.has(language) ? language : "plain text";
}

// 서로게이트 쌍이 끊기지 않도록 문자열을 size 이하 길이로 나눈다.
export function splitText(text, size = RICH_TEXT_LIMIT) {
  const parts = [];
  let start = 0;
  while (start < text.length) {
    let end = Math.min(start + size, text.length);
    const last = text.charCodeAt(end - 1);
    if (end < text.length && last >= 0xd800 && last <= 0xdbff) end -= 1;
    parts.push(text.slice(start, end));
    start = end;
  }
  return parts;
}

// { text, link, bold, italic, strikethrough, code } 조각 목록을 Notion rich_text 배열로 바꾼다.
// 배열이 100개를 넘으면 뒤쪽을 생략 표시로 대체한다.
export function toRichText(segments) {
  const items = [];
  for (const segment of segments) {
    for (const content of splitText(String(segment.text ?? ""))) {
      const item = { type: "text", text: { content } };
      if (segment.link) item.text.link = { url: segment.link };
      const annotations = Object.fromEntries(
        ANNOTATION_KEYS.filter((key) => segment[key]).map((key) => [key, true])
      );
      if (Object.keys(annotations).length) item.annotations = annotations;
      items.push(item);
    }
  }

  if (items.length <= ARRAY_LIMIT) return items;
  const omitted = items.length - (ARRAY_LIMIT - 1);
  return [
    ...items.slice(0, ARRAY_LIMIT - 1),
    { type: "text", text: { content: ` … (텍스트 조각 ${omitted}개 생략)` } },
  ];
}

export function text(content, options = {}) {
  return toRichText([{ text: content, ...options }]);
}

function block(type, value, children) {
  const body = children?.length ? { ...value, children } : value;
  return { object: "block", type, [type]: body };
}

export const paragraph = (richText, children) =>
  block("paragraph", { rich_text: richText }, children);

export const heading = (level, richText) => block(`heading_${level}`, { rich_text: richText });

export const bulleted = (richText, children) =>
  block("bulleted_list_item", { rich_text: richText }, children);

export const numbered = (richText, children) =>
  block("numbered_list_item", { rich_text: richText }, children);

export const toDo = (richText, checked, children) =>
  block("to_do", { rich_text: richText, checked: Boolean(checked) }, children);

export const quote = (richText, children) => block("quote", { rich_text: richText }, children);

export const toggle = (richText, children) => block("toggle", { rich_text: richText }, children);

export const divider = () => block("divider", {});

export const callout = (richText, emoji, color = "default", children) =>
  block("callout", { rich_text: richText, icon: { type: "emoji", emoji }, color }, children);

// 코드 블록을 만든다. 본문이 너무 길면 MAX_CODE_CHARS에서 자르고 생략 표시를 붙인다.
export function code(content, language = "plain text", caption) {
  let body = String(content ?? "");
  if (body.length > MAX_CODE_CHARS) {
    const omitted = body.length - MAX_CODE_CHARS;
    body = `${body.slice(0, MAX_CODE_CHARS)}\n… (이하 ${omitted}자 생략)`;
  }
  const value = { rich_text: text(body), language: codeLanguage(language) };
  if (caption) value.caption = text(caption);
  return block("code", value);
}

// 셀 rich_text 배열의 2차원 목록으로 표를 만든다. 행 길이는 가장 긴 행에 맞춘다.
export function table(rows, hasColumnHeader = true) {
  const width = Math.max(1, ...rows.map((row) => row.length));
  const children = rows.map((row) =>
    block("table_row", {
      cells: Array.from({ length: width }, (_, index) => row[index] ?? []),
    })
  );
  return block("table", {
    table_width: width,
    has_column_header: hasColumnHeader,
    has_row_header: false,
    children,
  });
}

function plainText(richText) {
  return (richText ?? []).map((item) => item.text?.content ?? "").join("");
}

function tableAsCode(tableBlock) {
  const rows = tableBlock.table.children.map((row) =>
    row.table_row.cells.map(plainText).join(" | ")
  );
  return code(rows.join("\n"), "plain text");
}

// 요청 한 번에 허용되는 중첩 깊이를 넘는 하위 블록은 같은 수준으로 올리고,
// 하위 블록을 가질 수 없는 깊이의 표는 코드 블록으로 바꾼다.
export function enforceLimits(blocks, depth = 0) {
  const result = [];
  for (const item of blocks) {
    const value = item[item.type];
    const children = value?.children;
    if (!children?.length) {
      result.push(item);
      continue;
    }

    if (depth >= MAX_NESTING_DEPTH) {
      if (item.type === "table") {
        result.push(tableAsCode(item));
        continue;
      }
      const { children: _, ...rest } = value;
      result.push({ ...item, [item.type]: rest }, ...enforceLimits(children, depth));
      continue;
    }

    let limited = enforceLimits(children, depth + 1);
    if (limited.length > ARRAY_LIMIT && item.type !== "table") {
      const omitted = limited.length - (ARRAY_LIMIT - 1);
      limited = [
        ...limited.slice(0, ARRAY_LIMIT - 1),
        paragraph(text(`… 하위 블록 ${omitted}개 생략`)),
      ];
    }
    result.push({ ...item, [item.type]: { ...value, children: limited } });
  }
  return result;
}

export function countBlocks(item) {
  const children = item[item.type]?.children ?? [];
  return 1 + children.reduce((total, child) => total + countBlocks(child), 0);
}

// 최상위 블록을 Notion 요청 제한(최상위 100개, 전체 1000개, 약 450KB)에 맞는 묶음으로 나눈다.
export function chunkBlocks(blocks, { maxBlocks = 100, maxTotal = 1000, maxBytes = 450_000 } = {}) {
  const batches = [];
  let current = [];
  let total = 0;
  let bytes = 0;

  for (const item of blocks) {
    const count = countBlocks(item);
    const size = Buffer.byteLength(JSON.stringify(item));
    const full =
      current.length >= maxBlocks || total + count > maxTotal || bytes + size > maxBytes;
    if (current.length && full) {
      batches.push(current);
      current = [];
      total = 0;
      bytes = 0;
    }
    current.push(item);
    total += count;
    bytes += size;
  }

  if (current.length) batches.push(current);
  return batches;
}
