// GitHub PR 본문(GFM)의 주요 문법을 Notion 블록으로 변환한다.
// 지원: 제목, 문단, 글머리·번호·체크 목록, 인용, GitHub 알림, 코드 펜스(mermaid 포함), 표,
// 구분선, 인라인 서식(굵게·기울임·취소선·코드·링크·이슈 번호). HTML 주석은 제거한다.

import {
  bulleted,
  callout,
  code,
  divider,
  enforceLimits,
  heading,
  numbered,
  paragraph,
  quote,
  table,
  toDo,
  toRichText,
  ARRAY_LIMIT,
} from "./blocks.mjs";

const FENCE_RE = /^(\s*)(`{3,}|~{3,})(.*)$/;
const HEADING_RE = /^ {0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$/;
const HR_RE = /^ {0,3}([-*_])(?:\s*\1){2,}\s*$/;
const LIST_RE = /^(\s*)([-*+]|\d{1,9}[.)])(?:(\s+)(.*))?$/;
const QUOTE_RE = /^ {0,3}>\s?(.*)$/;
const TABLE_DELIMITER_RE = /^\s*\|?\s*:?-+:?\s*(?:\|\s*:?-+:?\s*)*\|?\s*$/;
const TASK_RE = /^\[([ xX])\](?:\s+([\s\S]*))?$/;
const ALERT_RE = /^\[!(NOTE|TIP|IMPORTANT|WARNING|CAUTION)\]\s*$/i;
const ESCAPABLE_RE = /\\([\\`*_{}[\]()#+\-.!|~<>])/g;
const ESCAPE_BASE = 0xe000;

const ALERTS = {
  NOTE: ["ℹ️", "blue_background"],
  TIP: ["💡", "green_background"],
  IMPORTANT: ["❗", "purple_background"],
  WARNING: ["⚠️", "yellow_background"],
  CAUTION: ["🛑", "red_background"],
};

const INLINE_RULES = [
  { name: "code", re: /(`+)(?!`)([\s\S]*?[^`])\1(?!`)/ },
  { name: "image", re: /!\[([^\]]*)\]\(\s*<?([^)\s>]+)>?(?:\s+["'][^"']*["'])?\s*\)/ },
  {
    name: "link",
    re: /\[((?:[^[\]]|\[[^\]]*\])+)\]\(\s*<?([^)\s>]+)>?(?:\s+["'][^"']*["'])?\s*\)/,
  },
  { name: "autolink", re: /<((?:https?|mailto):[^>\s]+)>/ },
  { name: "bold", re: /\*\*(\S(?:[\s\S]*?\S)?)\*\*|(?<!\w)__(\S(?:[\s\S]*?\S)?)__(?!\w)/ },
  { name: "strike", re: /~~(\S(?:[\s\S]*?\S)?)~~/ },
  { name: "italic", re: /\*([^\s*](?:[\s\S]*?[^\s*])?)\*|(?<!\w)_(\S(?:[\s\S]*?\S)?)_(?!\w)/ },
  { name: "url", re: /https?:\/\/[^\s<>"'`]+/ },
  { name: "issue", re: /(?<![\w&#/])#(\d+)\b/ },
];

function indentOf(line) {
  return line.length - line.trimStart().length;
}

function isFenceClose(line, fence) {
  const match = /^\s*(`{3,}|~{3,})\s*$/.exec(line);
  return Boolean(match && match[1][0] === fence.char && match[1].length >= fence.length);
}

// 줄바꿈과 선행 탭을 정규화하고, 코드 펜스 밖의 HTML 주석을 제거한 줄 목록을 만든다.
function normalizeLines(markdown) {
  const lines = String(markdown ?? "")
    .replace(/\r\n?/g, "\n")
    .split("\n")
    .map((line) => line.replace(/^\t+/, (tabs) => "    ".repeat(tabs.length)));

  const result = [];
  let fence = null;
  let inComment = false;

  for (const line of lines) {
    if (fence) {
      result.push(line);
      if (isFenceClose(line, fence)) fence = null;
      continue;
    }

    let rest = line;
    let kept = "";
    let touched = inComment;
    while (rest) {
      if (inComment) {
        const end = rest.indexOf("-->");
        if (end === -1) {
          rest = "";
          break;
        }
        rest = rest.slice(end + 3);
        inComment = false;
        continue;
      }
      const start = rest.indexOf("<!--");
      if (start === -1) {
        kept += rest;
        break;
      }
      kept += rest.slice(0, start);
      rest = rest.slice(start + 4);
      inComment = true;
      touched = true;
    }

    if (touched && !kept.trim()) continue;
    result.push(kept);
    const opening = FENCE_RE.exec(kept);
    if (opening && !inComment) fence = { char: opening[2][0], length: opening[2].length };
  }
  return result;
}

function startsBlock(line) {
  return (
    FENCE_RE.test(line) ||
    HEADING_RE.test(line) ||
    HR_RE.test(line) ||
    QUOTE_RE.test(line) ||
    LIST_RE.test(line)
  );
}

function splitRow(line) {
  let row = line.trim();
  if (row.startsWith("|")) row = row.slice(1);
  if (row.endsWith("|") && !row.endsWith("\\|")) row = row.slice(0, -1);
  return row.split(/(?<!\\)\|/).map((cell) => cell.trim().replace(/\\\|/g, "|"));
}

function isTableStart(lines, index) {
  const header = lines[index];
  const delimiter = lines[index + 1];
  if (!header?.includes("|") || !delimiter?.includes("|") || !delimiter.includes("-")) {
    return false;
  }
  return (
    TABLE_DELIMITER_RE.test(delimiter) &&
    splitRow(header).length === splitRow(delimiter).length
  );
}

function protectEscapes(value) {
  return value.replace(ESCAPABLE_RE, (_, char) =>
    String.fromCharCode(ESCAPE_BASE + char.charCodeAt(0))
  );
}

function restoreEscapes(value, keepBackslash = false) {
  return value.replace(/[-]/g, (char) => {
    const original = String.fromCharCode(char.charCodeAt(0) - ESCAPE_BASE);
    return keepBackslash ? `\\${original}` : original;
  });
}

function cleanHtml(value) {
  return value
    .replace(/<br\s*\/?>/gi, "\n")
    .replace(/<\/?(?:details|summary|p|div|span|sub|sup|b|strong|i|em|kbd)\b[^>]*>/gi, "");
}

function sameStyle(a, b) {
  return (
    a.link === b.link &&
    Boolean(a.bold) === Boolean(b.bold) &&
    Boolean(a.italic) === Boolean(b.italic) &&
    Boolean(a.strikethrough) === Boolean(b.strikethrough) &&
    Boolean(a.code) === Boolean(b.code)
  );
}

function pushText(segments, value, style) {
  if (!value) return;
  const previous = segments.at(-1);
  if (previous && sameStyle(previous, style)) {
    previous.text += value;
    return;
  }
  segments.push({ ...style, text: value });
}

// 링크 주소를 Notion이 허용하는 절대 URL로 바꾼다. 저장소 상대 경로는 GitHub 파일 링크로 연결한다.
export function resolveUrl(url, context = {}) {
  const value = restoreEscapes(url);
  if (/^(?:https?:|mailto:)/i.test(value)) return value.length <= 2000 ? value : null;
  if (value.startsWith("#") || /^[a-z][a-z0-9+.-]*:/i.test(value)) return null;
  if (!context.blobBase) return null;
  return `${context.blobBase}/${value.replace(/^\.?\//, "")}`;
}

function parseSegments(value, context, style, segments = []) {
  let rest = value;
  while (rest) {
    let best = null;
    for (const rule of INLINE_RULES) {
      if ((rule.name === "url" || rule.name === "issue") && style.link) continue;
      if (rule.name === "issue" && !context.repoUrl) continue;
      const match = rule.re.exec(rest);
      if (match && (!best || match.index < best.match.index)) best = { rule, match };
    }

    if (!best) {
      pushText(segments, cleanHtml(restoreEscapes(rest)), style);
      break;
    }

    const { rule, match } = best;
    if (match.index > 0) {
      pushText(segments, cleanHtml(restoreEscapes(rest.slice(0, match.index))), style);
    }

    let consumed = match[0].length;
    switch (rule.name) {
      case "code": {
        let body = restoreEscapes(match[2], true).replace(/\n/g, " ");
        if (/^ .*[^ ].* $/.test(body)) body = body.slice(1, -1);
        pushText(segments, body, { ...style, code: true });
        break;
      }
      case "image": {
        const link = resolveUrl(match[2], context) ?? style.link;
        pushText(segments, `🖼 ${restoreEscapes(match[1]) || "이미지"}`, { ...style, link });
        break;
      }
      case "link": {
        const link = resolveUrl(match[2], context) ?? style.link;
        parseSegments(match[1], context, { ...style, link }, segments);
        break;
      }
      case "autolink":
        pushText(segments, match[1], { ...style, link: match[1] });
        break;
      case "bold":
        parseSegments(match[1] ?? match[2], context, { ...style, bold: true }, segments);
        break;
      case "strike":
        parseSegments(match[1], context, { ...style, strikethrough: true }, segments);
        break;
      case "italic":
        parseSegments(match[1] ?? match[2], context, { ...style, italic: true }, segments);
        break;
      case "url": {
        const trimmed = match[0].replace(/[.,;:!?)\]]+$/, "");
        const url = restoreEscapes(trimmed);
        consumed = trimmed.length;
        pushText(segments, url, { ...style, link: url.length <= 2000 ? url : undefined });
        break;
      }
      case "issue":
        pushText(segments, `#${match[1]}`, {
          ...style,
          link: `${context.repoUrl}/issues/${match[1]}`,
        });
        break;
    }
    rest = rest.slice(match.index + consumed);
  }
  return segments;
}

// 인라인 마크다운을 Notion rich_text 배열로 변환한다.
export function inlineRichText(value, context = {}) {
  return toRichText(parseSegments(protectEscapes(String(value ?? "")), context, {}));
}

function headingBlock(match, context) {
  const level = context.baseHeading + (match[1].length - context.minHeading);
  const richText = inlineRichText(match[2], context);
  if (level <= 3) return heading(level, richText);
  return paragraph(toRichText([{ text: match[2], bold: true }]));
}

function parseFence(lines, start, match) {
  const indent = match[1].length;
  const fence = { char: match[2][0], length: match[2].length };
  const body = [];
  let index = start + 1;
  while (index < lines.length) {
    if (isFenceClose(lines[index], fence)) {
      index += 1;
      break;
    }
    const line = lines[index];
    body.push(line.slice(Math.min(indent, indentOf(line))));
    index += 1;
  }
  return { blocks: [code(body.join("\n"), match[3])], next: index };
}

function parseTable(lines, start, context) {
  const rows = [splitRow(lines[start])];
  let index = start + 2;
  while (index < lines.length && lines[index].trim() && lines[index].includes("|")) {
    rows.push(splitRow(lines[index]));
    index += 1;
  }

  const shown = rows.slice(0, ARRAY_LIMIT);
  const blocks = [
    table(shown.map((row) => row.map((cell) => inlineRichText(cell, context)))),
  ];
  if (rows.length > shown.length) {
    blocks.push(
      paragraph(toRichText([{ text: `표의 나머지 ${rows.length - shown.length}행은 원문에서 확인하세요.` }]))
    );
  }
  return { blocks, next: index };
}

function splitLeadParagraph(blocks) {
  if (blocks[0]?.type === "paragraph" && !blocks[0].paragraph.children) {
    return { richText: blocks[0].paragraph.rich_text, children: blocks.slice(1) };
  }
  return { richText: [], children: blocks };
}

function parseQuote(lines, start, context) {
  const contents = [];
  let index = start;
  while (index < lines.length) {
    const match = QUOTE_RE.exec(lines[index]);
    if (!match) break;
    contents.push(match[1]);
    index += 1;
  }

  const alert = ALERT_RE.exec(contents[0]?.trim() ?? "");
  const inner = parseBlocks(alert ? contents.slice(1) : contents, context);
  const { richText, children } = splitLeadParagraph(inner);
  if (alert) {
    const [emoji, color] = ALERTS[alert[1].toUpperCase()];
    return { blocks: [callout(richText, emoji, color, children)], next: index };
  }
  return { blocks: [quote(richText, children)], next: index };
}

function nextNonBlank(lines, index) {
  for (let cursor = index; cursor < lines.length; cursor += 1) {
    if (lines[cursor].trim()) return cursor;
  }
  return -1;
}

function listItemBlock(marker, itemLines, context) {
  const textLines = [];
  let cursor = 0;
  while (
    cursor < itemLines.length &&
    itemLines[cursor].trim() &&
    !(cursor > 0 && startsBlock(itemLines[cursor]))
  ) {
    textLines.push(itemLines[cursor].trim());
    cursor += 1;
  }

  const children = parseBlocks(itemLines.slice(cursor), context);
  const value = textLines.join("\n");
  const task = /^[-*+]$/.test(marker) ? TASK_RE.exec(value) : null;

  if (task) {
    const label = task[2] ?? "";
    if (!label.trim() && !children.length) return null;
    return toDo(inlineRichText(label, context), task[1] !== " ", children);
  }
  if (!value.trim() && !children.length) return null;
  const richText = inlineRichText(value, context);
  return /\d/.test(marker) ? numbered(richText, children) : bulleted(richText, children);
}

function parseList(lines, start, context) {
  const blocks = [];
  const baseIndent = indentOf(lines[start]);
  let index = start;

  while (index < lines.length) {
    const line = lines[index];
    const match = LIST_RE.exec(line);
    if (!match || indentOf(line) !== baseIndent || HR_RE.test(line)) break;

    const contentIndent = baseIndent + match[2].length + (match[3]?.length ?? 1);
    const itemLines = [match[4] ?? ""];
    index += 1;

    while (index < lines.length) {
      const current = lines[index];
      if (!current.trim()) {
        const next = nextNonBlank(lines, index);
        if (next !== -1 && indentOf(lines[next]) > baseIndent) {
          itemLines.push("");
          index += 1;
          continue;
        }
        break;
      }
      const indent = indentOf(current);
      if (indent > baseIndent) {
        itemLines.push(current.slice(Math.min(indent, contentIndent)));
        index += 1;
        continue;
      }
      if (!startsBlock(current) && itemLines.at(-1).trim()) {
        itemLines.push(current.trim());
        index += 1;
        continue;
      }
      break;
    }

    const item = listItemBlock(match[2], itemLines, context);
    if (item) blocks.push(item);
  }
  return { blocks, next: index };
}

function parseParagraph(lines, start, context) {
  const parts = [lines[start].trim()];
  let index = start + 1;
  while (
    index < lines.length &&
    lines[index].trim() &&
    !startsBlock(lines[index]) &&
    !isTableStart(lines, index)
  ) {
    parts.push(lines[index].trim());
    index += 1;
  }
  return { blocks: [paragraph(inlineRichText(parts.join("\n"), context))], next: index };
}

function parseBlocks(lines, context) {
  const blocks = [];
  let index = 0;

  while (index < lines.length) {
    const line = lines[index];
    if (!line.trim()) {
      index += 1;
      continue;
    }

    let result;
    const fence = FENCE_RE.exec(line);
    const headingMatch = HEADING_RE.exec(line);
    if (fence) result = parseFence(lines, index, fence);
    else if (headingMatch) result = { blocks: [headingBlock(headingMatch, context)], next: index + 1 };
    else if (HR_RE.test(line)) result = { blocks: [divider()], next: index + 1 };
    else if (isTableStart(lines, index)) result = parseTable(lines, index, context);
    else if (QUOTE_RE.test(line)) result = parseQuote(lines, index, context);
    else if (LIST_RE.test(line)) result = parseList(lines, index, context);
    else result = parseParagraph(lines, index, context);

    blocks.push(...result.blocks);
    index = Math.max(result.next, index + 1);
  }
  return blocks;
}

function shallowestHeading(lines) {
  let fence = null;
  let minimum = 6;
  for (const line of lines) {
    if (fence) {
      if (isFenceClose(line, fence)) fence = null;
      continue;
    }
    const opening = FENCE_RE.exec(line);
    if (opening) {
      fence = { char: opening[2][0], length: opening[2].length };
      continue;
    }
    const match = HEADING_RE.exec(line);
    if (match) minimum = Math.min(minimum, match[1].length);
  }
  return minimum;
}

// 마크다운 문자열을 Notion 블록 목록으로 변환한다.
// options.baseHeading: 본문에서 가장 상위 제목이 대응할 Notion 제목 수준(1~3).
// options.repoUrl: #번호 이슈 링크의 기준 저장소 URL.
// options.blobBase: 상대 경로 링크를 연결할 GitHub 파일 URL 접두사.
export function markdownToBlocks(markdown, options = {}) {
  const lines = normalizeLines(markdown);
  const context = {
    baseHeading: options.baseHeading ?? 1,
    minHeading: shallowestHeading(lines),
    repoUrl: options.repoUrl,
    blobBase: options.blobBase,
  };
  return enforceLimits(parseBlocks(lines, context));
}
