// PR 변경 파일 목록과 아키텍처 문서의 mermaid 원본으로 Notion에 넣을 다이어그램을 만든다.
// 다이어그램은 파일 경로와 변경 상태만 사용하며 코드 의미나 설계 영향은 추론하지 않는다.

const STATUS_CLASS = {
  added: "added",
  copied: "added",
  removed: "removed",
  renamed: "renamed",
  modified: "modified",
  changed: "modified",
  unchanged: "modified",
};

const STATUS_STYLES = [
  "classDef added fill:#dcfce7,stroke:#16a34a,color:#14532d",
  "classDef modified fill:#fef9c3,stroke:#ca8a04,color:#713f12",
  "classDef removed fill:#fee2e2,stroke:#dc2626,color:#7f1d1d",
  "classDef renamed fill:#dbeafe,stroke:#2563eb,color:#1e3a8a",
];

const CHANGED_STYLE = "classDef changed fill:#fde68a,stroke:#d97706,stroke-width:3px,color:#78350f";
const MAP_RE = /^\s*%%\s*map\s+(\S+)\s+([A-Za-z][\w-]*)\s*$/;

// mermaid 따옴표 라벨 안에서 문법으로 해석될 수 있는 문자를 엔티티 코드로 바꾼다.
export function mermaidLabel(value) {
  return String(value)
    .replace(/"/g, "#quot;")
    .replace(/</g, "#lt;")
    .replace(/>/g, "#gt;")
    .replace(/`/g, "#96;");
}

function statusClass(file) {
  return STATUS_CLASS[file.status] ?? "modified";
}

function directoryOf(filename, depth) {
  const parts = filename.split("/").slice(0, -1);
  return parts.slice(0, depth).join("/");
}

function groupFiles(files, depth = Infinity) {
  const groups = new Map();
  for (const file of files) {
    const directory = directoryOf(file.filename, depth);
    if (!groups.has(directory)) groups.set(directory, []);
    groups.get(directory).push(file);
  }
  return [...groups.entries()].sort(([a], [b]) => a.localeCompare(b));
}

function totals(files) {
  return files.reduce(
    (sum, file) => ({
      additions: sum.additions + (file.additions ?? 0),
      deletions: sum.deletions + (file.deletions ?? 0),
    }),
    { additions: 0, deletions: 0 }
  );
}

function groupClass(files) {
  const classes = new Set(files.map(statusClass));
  return classes.size === 1 ? [...classes][0] : "modified";
}

// 변경 파일을 디렉터리별로 묶은 mermaid flowchart를 만든다.
// 파일이 maxFiles개 이하면 파일 단위로, 많으면 디렉터리 단위 집계로 표시한다.
export function changedFilesDiagram(files, { rootLabel = "repository", maxFiles = 30, maxGroups = 25 } = {}) {
  if (!files?.length) return null;

  const lines = ["flowchart LR", `  root["${mermaidLabel(rootLabel)}"]`];
  const detailed = files.length <= maxFiles;
  let groups = groupFiles(files);
  if (!detailed && groups.length > maxGroups) groups = groupFiles(files, 1);

  const shownGroups = groups.slice(0, maxGroups);
  shownGroups.forEach(([directory, groupFilesList], groupIndex) => {
    const id = `d${groupIndex}`;
    const name = directory ? `${directory}/` : "(루트)";

    if (detailed) {
      lines.push(`  ${id}["${mermaidLabel(name)}"]`, `  root --> ${id}`);
      groupFilesList.forEach((file, fileIndex) => {
        const fileId = `${id}f${fileIndex}`;
        const base = directory ? file.filename.slice(directory.length + 1) : file.filename;
        const renamed = file.status === "renamed" && file.previous_filename ? " (이름 변경)" : "";
        const label = `${base}${renamed} +${file.additions ?? 0}/-${file.deletions ?? 0}`;
        lines.push(
          `  ${fileId}["${mermaidLabel(label)}"]:::${statusClass(file)}`,
          `  ${id} --> ${fileId}`
        );
      });
      return;
    }

    const { additions, deletions } = totals(groupFilesList);
    const label = `${name} · ${groupFilesList.length}개 · +${additions}/-${deletions}`;
    lines.push(`  ${id}["${mermaidLabel(label)}"]:::${groupClass(groupFilesList)}`, `  root --> ${id}`);
  });

  if (groups.length > shownGroups.length) {
    const rest = groups.slice(shownGroups.length).flatMap(([, list]) => list);
    lines.push(`  more["${mermaidLabel(`그 외 ${rest.length}개 파일`)}"]`, "  root --> more");
  }

  lines.push(...STATUS_STYLES.map((style) => `  ${style}`));
  return lines.join("\n");
}

// 마크다운에서 ```mermaid 코드 펜스의 본문을 순서대로 추출한다.
export function extractMermaidBlocks(markdown) {
  const blocks = [];
  const pattern = /^([ \t]*)(`{3,}|~{3,})[ \t]*mermaid\b[^\n]*\n([\s\S]*?)^\1\2[`~]*[ \t]*$/gm;
  for (const match of String(markdown ?? "").matchAll(pattern)) blocks.push(match[3].trimEnd());
  return blocks;
}

function matchesPrefix(path, prefix) {
  if (prefix.endsWith("/")) return path.startsWith(prefix);
  return path === prefix || path.startsWith(`${prefix}/`);
}

// 아키텍처 문서에서 `%% map <경로> <노드ID>` 주석이 있는 mermaid 다이어그램을 찾아,
// 이번 PR이 변경한 경로에 대응하는 노드를 강조한 다이어그램을 반환한다.
export function architectureDiagram(markdown, files) {
  const source = extractMermaidBlocks(markdown).find((block) =>
    block.split("\n").some((line) => MAP_RE.test(line))
  );
  if (!source) return null;

  const mappings = source
    .split("\n")
    .map((line) => MAP_RE.exec(line))
    .filter(Boolean)
    .map((match) => ({ prefix: match[1], node: match[2] }));

  const matched = new Map();
  for (const file of files ?? []) {
    for (const path of [file.filename, file.previous_filename].filter(Boolean)) {
      for (const { prefix, node } of mappings) {
        if (!matchesPrefix(path, prefix)) continue;
        if (!matched.has(node)) matched.set(node, new Set());
        matched.get(node).add(prefix);
      }
    }
  }

  const nodes = [...matched.keys()];
  const mermaid = nodes.length
    ? [source, `  ${CHANGED_STYLE}`, `  class ${nodes.join(",")} changed`].join("\n")
    : source;
  const changed = nodes.map((node) => ({ node, prefixes: [...matched.get(node)] }));
  return { mermaid, changed };
}
