// 코드 파일 목록으로 '서비스 아키텍처' 모델을 만들고, 이전 모델과 비교해 추가·변경·삭제를 색칠한 mermaid로 렌더한다.
// 파일 목록과 내용(문자열)만 받는 순수 함수다. 코드는 실행하지 않고 글자로만 해석한다.
// - 노드: 비어 있지 않은 서비스 파일이 있는 계층(docs/architecture.md의 `%% map`), 공통 데이터 계약(src/schemas.py), map에 없는 서비스 경로
// - 연결선: Python import(내부 계층·공통 계약), `%% ext` 규칙에 맞는 외부 모듈 import·호출 주소
// - 저장: 그림 코드의 `%% arch v1 sha=… pr=…` 한 줄에 그림을 그린 head와 PR 번호를 남기고, 노드·연결선 줄로 모델을 다시 읽을 수 있다.

export const CONTRACT_PATH = "src/schemas.py";
const CONTRACT_NODE = { id: "c_contract", label: "src/schemas.py<br/>공통 데이터 계약", kind: "contract" };
const RESERVED_IDS = new Set(["end", "graph", "flowchart", "subgraph", "style", "class", "classdef", "click", "linkstyle", "default", "direction"]);
const ID_RE = /^[a-z][a-z0-9_]*$/;
const META_RE = /^\s*%% arch v1 sha=([0-9a-f]{7,40}) pr=(\d+)\s*$/m;
const REMOVED_MARK = "%% removed";
export const MAX_NODES = 40;
const KIND_ORDER = { layer: 0, path: 1, contract: 2, external: 3 };
const STYLES = [
  "classDef added fill:#dcfce7,stroke:#16a34a,color:#14532d",
  "classDef changed fill:#fef9c3,stroke:#ca8a04,color:#713f12",
  "classDef removed fill:#fee2e2,stroke:#dc2626,color:#7f1d1d,stroke-dasharray:4 3",
];

// mermaid 따옴표 라벨 안에서 문법으로 해석될 수 있는 문자를 엔티티 코드로 바꾼다.
export function mermaidLabel(value) {
  return String(value).replace(/"/g, "#quot;").replace(/</g, "#lt;").replace(/>/g, "#gt;").replace(/`/g, "#96;");
}

// 캡션 등 일반 글에 쓰도록 라벨의 줄바꿈 태그와 엔티티를 풀어 쓴다.
export function plainLabel(label) {
  return String(label).replace(/<br\s*\/?>/g, " ").replace(/#quot;/g, '"').replace(/#lt;/g, "<").replace(/#gt;/g, ">").replace(/#96;/g, "`");
}

// 서비스 범위: 개발 자동화·테스트·문서 경로는 그림에서 뺀다.
export function isServicePath(path) {
  if (/^(src|frontend|configs|prompts|evaluation)\//.test(path)) return true;
  if (/^scripts\/[^/]+\.py$/.test(path)) return true;
  return path === "Dockerfile" || path === "compose.yaml" || /^requirements[^/]*\.txt$/.test(path);
}

// ---------- docs/architecture.md 규칙 ----------
function mermaidBlocks(markdown) {
  const pattern = /^([ \t]*)(`{3,}|~{3,})[ \t]*mermaid\b[^\n]*\n([\s\S]*?)^\1\2[`~]*[ \t]*$/gm;
  return [...String(markdown ?? "").matchAll(pattern)].map((match) => match[3]);
}

// `%% map 경로 노드`(파일→계층), 노드 라벨, `%% ext import|host:패턴 노드 라벨`(외부 서비스)을 읽는다. 줄 맨 앞 규칙만 인정한다.
export function parseArchitectureRules(markdown) {
  const source = mermaidBlocks(markdown).find((block) => /^\s*%%\s*map\s/m.test(block)) ?? "";
  const maps = [...source.matchAll(/^\s*%%\s*map\s+(\S+)\s+([A-Za-z][\w-]*)\s*$/gm)].map((m) => ({ prefix: m[1], node: m[2] }));
  const ext = [...source.matchAll(/^\s*%%\s*ext\s+(import|host):(\S+)\s+([A-Za-z][\w-]*)\s+(.+?)\s*$/gm)]
    .map((m) => ({ kind: m[1], pattern: m[2].toLowerCase(), node: m[3], label: m[4] }));
  const labels = {};
  for (const m of source.matchAll(/^\s*([A-Za-z][\w-]*)\s*(?:\[\(|\(\[|\[\[|\[|\(\(|\()"([^"]*)"/gm)) labels[m[1]] ??= m[2];
  return { maps, ext, labels };
}

// ---------- 노드 ----------
function slug(value) {
  return String(value).toLowerCase().replace(/[^a-z0-9]+/g, "_").replace(/^_+|_+$/g, "") || "x";
}

// 경로에서 만든 ID가 서로 겹치지 않도록 원래 문자열의 짧은 해시를 붙인다.
function shortHash(value) {
  let hash = 5381;
  for (const char of String(value)) hash = ((hash * 33) ^ char.codePointAt(0)) >>> 0;
  return hash.toString(36).slice(0, 4);
}

function longestPrefix(path, maps) {
  let best = null;
  for (const { prefix, node } of maps) {
    const hit = prefix.endsWith("/") ? path.startsWith(prefix) : path === prefix || path.startsWith(`${prefix}/`);
    if (hit && (!best || prefix.length > best.prefix.length)) best = { prefix, node };
  }
  return best;
}

// 파일이 속한 노드. 공통 계약 → map 계층(가장 긴 접두사) → map에 없는 경로(src/<디렉터리>/ 또는 파일) 순으로 정한다.
export function nodeFor(path, rules) {
  if (path === CONTRACT_PATH) return CONTRACT_NODE;
  const mapped = longestPrefix(path, rules.maps);
  if (mapped) return { id: `l_${slug(mapped.node)}`, label: rules.labels[mapped.node] ?? mermaidLabel(mapped.node), kind: "layer" };
  const key = /^src\/[^/]+\//.exec(path)?.[0] ?? path;
  return { id: `p_${slug(key)}_${shortHash(key)}`, label: mermaidLabel(key), kind: "path" };
}

const externalNode = (rule) => ({ id: `x_${slug(rule.node)}`, label: mermaidLabel(rule.label), kind: "external" });

// ---------- Python 해석(실행 없음) ----------
// 주석을 지우고 문자열을 빈 따옴표로 바꾼 코드와, 한 줄 문자열 리터럴의 내용 목록을 돌려준다. 삼중 따옴표 문자열(docstring)은 내용을 버린다.
export function scanPython(source) {
  const text = String(source ?? "");
  let code = "";
  const strings = [];
  let index = 0;
  while (index < text.length) {
    const char = text[index];
    if (char === "#") {
      while (index < text.length && text[index] !== "\n") index += 1;
      continue;
    }
    const match = /^([rRbBuUfF]{0,2})('''|"""|'|")/.exec(text.slice(index, index + 5));
    const prefixOk = match && (match[1] === "" || index === 0 || !/[A-Za-z0-9_]/.test(text[index - 1]));
    if (match && prefixOk) {
      const quote = match[2];
      let cursor = index + match[0].length;
      let content = "";
      while (cursor < text.length) {
        if (text[cursor] === "\\") {
          content += text.slice(cursor, cursor + 2);
          cursor += 2;
          continue;
        }
        if (text.startsWith(quote, cursor)) {
          cursor += quote.length;
          break;
        }
        if (quote.length === 1 && text[cursor] === "\n") break;
        content += text[cursor];
        cursor += 1;
      }
      if (quote.length === 1) strings.push(content);
      code += `""${quote.length === 3 ? "\n".repeat((content.match(/\n/g) ?? []).length) : ""}`;
      index = cursor;
      continue;
    }
    code += char;
    index += 1;
  }
  return { code, strings };
}

// 문자열·주석을 지운 코드에서 import 문을 읽는다(들여쓴 import, 괄호·역슬래시 여러 줄, `as` 별칭 포함).
export function parseImports(code) {
  const lines = String(code).split("\n");
  const imports = [];
  for (let index = 0; index < lines.length; index += 1) {
    if (!/^\s*(from|import)\b/.test(lines[index])) continue;
    let statement = lines[index];
    let depth = (statement.match(/\(/g) ?? []).length - (statement.match(/\)/g) ?? []).length;
    while ((depth > 0 || /\\\s*$/.test(statement)) && index + 1 < lines.length) {
      index += 1;
      statement = `${statement.replace(/\\\s*$/, "")} ${lines[index]}`;
      depth += (lines[index].match(/\(/g) ?? []).length - (lines[index].match(/\)/g) ?? []).length;
    }
    const clean = statement.replace(/[()]/g, " ").replace(/\s+/g, " ").trim();
    const fromMatch = /^from\s+(\.*)([\w.]*)\s+import\s+(.+)$/.exec(clean);
    if (fromMatch) {
      const names = fromMatch[3].split(",").map((name) => name.trim().split(/\s+as\s+/)[0].trim()).filter((name) => name && name !== "*");
      imports.push({ level: fromMatch[1].length, module: fromMatch[2], names });
      continue;
    }
    const importMatch = /^import\s+(.+)$/.exec(clean);
    if (importMatch) {
      for (const part of importMatch[1].split(",")) {
        const module = part.trim().split(/\s+as\s+/)[0].trim();
        if (/^[\w.]+$/.test(module)) imports.push({ level: 0, module, names: [] });
      }
    }
  }
  return imports;
}

// 문자열에 들어 있는 URL의 호스트 이름.
export const hostsOf = (value) => [...String(value).matchAll(/https?:\/\/([A-Za-z0-9.-]+)/g)].map((m) => m[1].toLowerCase());

// 모듈 경로 후보(파일·패키지·디렉터리) 중 저장소에 있는 첫 경로를 찾는다.
function resolveModulePath(base, paths, dirs) {
  if (!base) return null;
  for (const candidate of [`${base}.py`, `${base}/__init__.py`]) if (paths.has(candidate)) return candidate;
  return dirs.has(base) ? `${base}/` : null;
}

// import 하나를 저장소 경로(내부) 또는 최상위 모듈 이름(외부)으로 푼다. 상대 import는 파일 위치 기준으로 푼다.
export function resolveImport(filePath, imported, paths, dirs) {
  let base;
  if (imported.level > 0) {
    const parts = filePath.split("/").slice(0, -1);
    const up = parts.slice(0, Math.max(0, parts.length - (imported.level - 1)));
    base = [...up, ...imported.module.split(".").filter(Boolean)].join("/");
  } else {
    base = imported.module.replaceAll(".", "/");
  }
  const targets = [];
  for (const name of imported.names) {
    const hit = resolveModulePath(base ? `${base}/${name}` : name, paths, dirs);
    if (hit) targets.push(hit);
  }
  if (!targets.length) {
    let module = base;
    while (module) {
      const hit = resolveModulePath(module, paths, dirs);
      if (hit) {
        targets.push(hit);
        break;
      }
      module = module.includes("/") ? module.slice(0, module.lastIndexOf("/")) : "";
    }
  }
  if (targets.length) return { internal: targets, external: null };
  return { internal: [], external: imported.level > 0 ? null : imported.module.split(".")[0].toLowerCase() };
}

// 그림에 넣을 만큼 내용이 있는 파일인지: .py는 주석·docstring 말고 실제 문장이 있어야 하고, 그 밖은 공백이 아닌 글자가 있어야 한다.
export function hasContent(file) {
  if (/(^|\/)(\.gitkeep|README[^/]*\.md)$/i.test(file.path)) return false;
  if (file.content === undefined || file.content === null) return (file.size ?? 0) > 0;
  if (file.path.endsWith(".py")) return scanPython(file.content).code.replace(/""/g, "").trim().length > 0;
  return String(file.content).trim().length > 0;
}

// ---------- 모델 ----------
const edgeKey = (edge) => `${edge.from}|${edge.to}|${edge.style}`;

// 파일 목록({path, size, content})과 규칙으로 현재 모델({nodes, edges})을 만든다. 빈 노드를 가리키는 import는 경고로 남기고 뺀다.
export function buildModel(files, rules, warnings = []) {
  const service = files.filter((file) => isServicePath(file.path) && hasContent(file));
  const paths = new Set(files.map((file) => file.path));
  const dirs = new Set(files.flatMap((file) => file.path.split("/").slice(0, -1).map((_, index, parts) => parts.slice(0, index + 1).join("/"))));
  const nodes = new Map();
  for (const file of service) {
    const node = nodeFor(file.path, rules);
    nodes.set(node.id, node);
  }
  const edges = new Map();
  const addEdge = (from, to, style) => {
    const edge = { from, to, style };
    edges.set(edgeKey(edge), edge);
  };
  const addExternal = (from, rule) => {
    const node = externalNode(rule);
    nodes.set(node.id, node);
    addEdge(from, node.id, "solid");
  };
  for (const file of service.filter((item) => item.path.endsWith(".py") && typeof item.content === "string")) {
    const from = nodeFor(file.path, rules).id;
    const { code, strings } = scanPython(file.content);
    for (const imported of parseImports(code)) {
      const resolved = resolveImport(file.path, imported, paths, dirs);
      for (const target of resolved.internal) {
        if (!isServicePath(target)) continue;
        const to = nodeFor(target.endsWith("/") ? `${target}__init__.py` : target, rules);
        if (to.id === from) continue;
        if (!nodes.has(to.id)) {
          warnings.push(`${file.path}: 내용이 없는 ${plainLabel(to.label)}를 import해 연결선에서 뺐습니다.`);
          continue;
        }
        addEdge(from, to.id, to.kind === "contract" ? "dotted" : "solid");
      }
      if (resolved.external) {
        const rule = rules.ext.find((item) => item.kind === "import" && item.pattern === resolved.external);
        if (rule) addExternal(from, rule);
      }
    }
    for (const host of strings.flatMap(hostsOf)) {
      const rule = rules.ext.find((item) => item.kind === "host" && (host === item.pattern || host.endsWith(`.${item.pattern}`)));
      if (rule) addExternal(from, rule);
    }
  }
  const byKind = (a, b) => (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9) || a.id.localeCompare(b.id);
  return {
    nodes: [...nodes.values()].sort(byKind),
    edges: [...edges.values()].sort((a, b) => a.from.localeCompare(b.from) || a.to.localeCompare(b.to) || a.style.localeCompare(b.style)),
  };
}

// 이전 그림의 노드 순서를 지키고, 새 노드는 종류·ID 순으로 뒤에 붙인다.
function ordered(items, previous, key) {
  const position = new Map((previous ?? []).map((item, index) => [key(item), index]));
  return [...items].sort((a, b) => {
    const pa = position.get(key(a));
    const pb = position.get(key(b));
    if (pa !== undefined && pb !== undefined) return pa - pb;
    if (pa !== undefined) return -1;
    if (pb !== undefined) return 1;
    return (KIND_ORDER[a.kind] ?? 9) - (KIND_ORDER[b.kind] ?? 9) || key(a).localeCompare(key(b));
  });
}

// 이전 모델 대비 추가·변경·삭제를 정한다. 변경은 이번 PR이 바꾼 파일이 속한, 이전에도 있던 노드다.
export function diffModels(after, before, changedIds = []) {
  const beforeNodes = new Set((before?.nodes ?? []).map((node) => node.id));
  const afterNodes = new Set(after.nodes.map((node) => node.id));
  const beforeEdges = new Set((before?.edges ?? []).map(edgeKey));
  const afterEdges = new Set(after.edges.map(edgeKey));
  return {
    addedNodes: before ? after.nodes.filter((node) => !beforeNodes.has(node.id)) : [],
    changedNodes: after.nodes.filter((node) => beforeNodes.has(node.id) && changedIds.includes(node.id)),
    removedNodes: (before?.nodes ?? []).filter((node) => !afterNodes.has(node.id)),
    addedEdges: before ? after.edges.filter((edge) => !beforeEdges.has(edgeKey(edge))) : [],
    removedEdges: (before?.edges ?? []).filter((edge) => !afterEdges.has(edgeKey(edge))),
  };
}

function nodeLine(node) {
  const [open, close] = node.kind === "external" ? ['(["', '"])'] : node.kind === "contract" ? ['[["', '"]]'] : ['["', '"]'];
  return `  ${node.id}${open}${node.label}${close}`;
}
const edgeLine = (edge) => `  ${edge.from} ${edge.style === "dotted" ? "-.->" : "-->"} ${edge.to}`;

// 현재 모델을 mermaid로 렌더한다. 이번 PR 기준 추가(초록)·변경(노랑)·삭제(빨간 점선, 이 그림에만)를 칠한다.
// before는 비교 기준, order는 노드·연결선 순서를 이어받을 이전 그림이다(없으면 before).
export function renderMermaid({ after, before, order = before, changedIds = [], sha, pr }) {
  const diff = diffModels(after, before, changedIds);
  const nodes = ordered(after.nodes, order?.nodes, (node) => node.id);
  const edges = ordered(after.edges.map((edge) => ({ ...edge, kind: "edge" })), order?.edges, edgeKey);
  const removedEdgesShown = diff.removedEdges;
  const lines = ["flowchart LR", `  %% arch v1 sha=${sha} pr=${pr}`, ...nodes.map(nodeLine), ...edges.map(edgeLine)];
  if (diff.removedNodes.length || removedEdgesShown.length) {
    lines.push(`  ${REMOVED_MARK}`, ...diff.removedNodes.map(nodeLine));
    for (const edge of diff.removedEdges) lines.push(edgeLine(edge));
  }
  lines.push(...STYLES.map((style) => `  ${style}`));
  const classLine = (items, name) => items.length && lines.push(`  class ${items.map((node) => node.id).join(",")} ${name}`);
  classLine(diff.addedNodes, "added");
  classLine(diff.changedNodes, "changed");
  classLine(diff.removedNodes, "removed");
  const addedKeys = new Set(diff.addedEdges.map(edgeKey));
  const addedIndexes = edges.map((edge, index) => (addedKeys.has(edgeKey(edge)) ? index : -1)).filter((index) => index >= 0);
  const removedIndexes = removedEdgesShown.map((_, index) => edges.length + index);
  if (addedIndexes.length) lines.push(`  linkStyle ${addedIndexes.join(",")} stroke:#16a34a,stroke-width:3px`);
  if (removedIndexes.length) lines.push(`  linkStyle ${removedIndexes.join(",")} stroke:#dc2626,stroke-dasharray:4 3`);
  return { mermaid: lines.join("\n"), diff };
}

// 그림 코드에서 메타 줄과 현재 노드·연결선(삭제 표시 앞까지)을 읽어 모델로 되돌린다. 메타 줄이 없으면 null.
export function parseMermaidModel(code) {
  const text = String(code ?? "");
  const meta = META_RE.exec(text);
  if (!meta) return null;
  const nodes = [];
  const edges = [];
  for (const line of text.split("\n")) {
    if (line.trim() === REMOVED_MARK) break;
    const node = /^\s*([a-z][a-z0-9_]*)(\["|\(\["|\[\[")(.*?)("\]\)|"\]\]|"\])\s*$/.exec(line);
    if (node) {
      const kind = node[2] === '(["' ? "external" : node[2] === '[["' ? "contract" : node[1].startsWith("p_") ? "path" : "layer";
      nodes.push({ id: node[1], label: node[3], kind });
      continue;
    }
    const edge = /^\s*([a-z][a-z0-9_]*) (-->|-\.->) ([a-z][a-z0-9_]*)\s*$/.exec(line);
    if (edge) edges.push({ from: edge[1], to: edge[3], style: edge[2] === "-.->" ? "dotted" : "solid" });
  }
  return { sha: meta[1], pr: Number(meta[2]), nodes, edges };
}

// 렌더한 그림의 문법을 점검한다. 문제 목록이 비어 있으면 통과.
export function validateMermaid(code) {
  const problems = [];
  const ids = [];
  const edges = [];
  let linkStyleMax = -1;
  for (const line of String(code).split("\n")) {
    const node = /^\s*([A-Za-z][\w-]*)(\["|\(\["|\[\[")/.exec(line);
    if (node) ids.push(node[1]);
    const edge = /^\s*(\S+) (-->|-\.->) (\S+)\s*$/.exec(line);
    if (edge) edges.push([edge[1], edge[3]]);
    const style = /^\s*linkStyle ([\d,]+) /.exec(line);
    if (style) linkStyleMax = Math.max(linkStyleMax, ...style[1].split(",").map(Number));
  }
  const declared = new Set(ids);
  if (declared.size !== ids.length) problems.push("중복 노드 ID");
  for (const id of ids) if (!ID_RE.test(id) || RESERVED_IDS.has(id)) problems.push(`허용되지 않는 노드 ID: ${id}`);
  for (const [from, to] of edges) if (!declared.has(from) || !declared.has(to)) problems.push(`선언되지 않은 끝점: ${from} → ${to}`);
  if (linkStyleMax >= edges.length) problems.push("linkStyle 번호가 연결선 수를 넘음");
  if (ids.length > MAX_NODES) problems.push(`노드가 ${MAX_NODES}개를 넘음`);
  if (!/^flowchart LR\n/.test(String(code)) || !META_RE.test(String(code))) problems.push("머리 줄 또는 메타 줄 없음");
  return problems;
}

// 그림 아래 캡션: 이번 PR로 추가·변경·삭제된 노드와 이전 그림 출처.
export function captionText(diff, sourceNote) {
  const names = (nodes) => nodes.map((node) => plainLabel(String(node.label).split(/<br\s*\/?>/)[0]).trim()).join(", ");
  const parts = [];
  if (diff.addedNodes.length || diff.addedEdges.length) parts.push(`🟩 추가 ${names(diff.addedNodes) || `연결선 ${diff.addedEdges.length}개`}`);
  if (diff.changedNodes.length) parts.push(`🟨 변경 ${names(diff.changedNodes)}`);
  if (diff.removedNodes.length || diff.removedEdges.length) parts.push(`🟥 삭제 ${names(diff.removedNodes) || `연결선 ${diff.removedEdges.length}개`}`);
  return `${parts.length ? parts.join(" · ") : "서비스 구성 변경 없음"} · ${sourceNote}`;
}
