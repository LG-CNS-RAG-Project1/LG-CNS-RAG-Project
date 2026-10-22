// develop에 병합된 PR 정보를 GitHub API에서 읽어 Notion 상위 페이지 아래에 기록한다.
// NOTION_DRY_RUN=1이면 Notion을 호출하지 않고 생성할 페이지 구성을 JSON으로 출력한다.
// 이때는 병합되지 않은 PR도 미리보기할 수 있고 NOTION_API_TOKEN 없이 실행된다.

import { readFile, writeFile } from "node:fs/promises";

import { chunkBlocks, text } from "./notion/blocks.mjs";
import { buildPrPage } from "./notion/pr_page.mjs";

const repository = process.env.GITHUB_REPOSITORY;
const githubToken = process.env.GITHUB_TOKEN;
const notionToken = process.env.NOTION_API_TOKEN;
const parentPageId = process.env.NOTION_PARENT_PAGE_ID;
const pullRequestNumber = Number(process.env.PR_NUMBER);
const runId = process.env.GITHUB_RUN_ID;
const architectureDoc = process.env.ARCHITECTURE_DOC ?? "docs/architecture.md";
const dryRun = process.env.NOTION_DRY_RUN === "1";
const dryRunOutput = process.env.NOTION_DRY_RUN_OUTPUT;

if (!repository || (!dryRun && (!githubToken || !notionToken || !parentPageId || !runId))) {
  throw new Error("Required GitHub Actions environment variables are missing.");
}

if (!Number.isSafeInteger(pullRequestNumber) || pullRequestNumber < 1) {
  throw new Error("PR_NUMBER must be a positive integer.");
}

const [owner, repo] = repository.split("/");
if (!owner || !repo || repository.split("/").length !== 2) {
  throw new Error("GITHUB_REPOSITORY must use owner/repository form.");
}

const githubHeaders = {
  Accept: "application/vnd.github+json",
  "X-GitHub-Api-Version": "2022-11-28",
  ...(githubToken ? { Authorization: `Bearer ${githubToken}` } : {}),
};

const notionHeaders = {
  Authorization: `Bearer ${notionToken}`,
  "Content-Type": "application/json",
  "Notion-Version": "2026-03-11",
};

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

// JSON API를 호출한다. 429·5xx 응답은 Retry-After 또는 지수 대기 후 최대 3회 재시도한다.
async function requestJson(url, headers, options = {}, attempt = 1) {
  const response = await fetch(url, {
    ...options,
    headers: { ...headers, ...options.headers },
  });

  if ((response.status === 429 || response.status >= 500) && attempt < 4) {
    const retryAfter = Number(response.headers.get("retry-after"));
    const delay = retryAfter > 0 ? retryAfter * 1000 : 1000 * 2 ** attempt;
    await sleep(Math.min(delay, 30_000));
    return requestJson(url, headers, options, attempt + 1);
  }

  if (!response.ok) {
    const service = url.startsWith("https://api.notion.com/") ? "Notion" : "GitHub";
    let detail = "";
    try {
      const body = await response.json();
      if (body?.message) detail = `: ${String(body.message).slice(0, 500)}`;
    } catch {
      detail = "";
    }
    throw new Error(`${service} API request failed with HTTP ${response.status}${detail}`);
  }

  return response.json();
}

async function fetchAllPages(path, maxPages = 30) {
  const items = [];
  for (let page = 1; page <= maxPages; page += 1) {
    const separator = path.includes("?") ? "&" : "?";
    const batch = await requestJson(
      `https://api.github.com/repos/${owner}/${repo}/${path}${separator}per_page=100&page=${page}`,
      githubHeaders
    );
    items.push(...batch);
    if (batch.length < 100) break;
  }
  return items;
}

function pageTitleText(page) {
  const titleProperty = Object.values(page.properties ?? {}).find(
    (property) => property.type === "title"
  );

  return (titleProperty?.title ?? [])
    .map((part) => part.plain_text ?? part.text?.content ?? "")
    .join("");
}

async function findExistingPage(title) {
  const result = await requestJson("https://api.notion.com/v1/search", notionHeaders, {
    method: "POST",
    body: JSON.stringify({
      query: title,
      page_size: 100,
      filter: { property: "object", value: "page" },
    }),
  });

  return (result.results ?? []).find(
    (page) =>
      pageTitleText(page) === title &&
      page.parent?.type === "page_id" &&
      page.parent.page_id.replaceAll("-", "").toLowerCase() ===
        parentPageId.replaceAll("-", "").toLowerCase()
  );
}

const pullRequest = await requestJson(
  `https://api.github.com/repos/${owner}/${repo}/pulls/${pullRequestNumber}`,
  githubHeaders
);

const isMergedIntoDevelop =
  pullRequest.base?.ref === "develop" && pullRequest.state === "closed" && pullRequest.merged_at;

if (!isMergedIntoDevelop) {
  if (!dryRun) throw new Error("Only merged pull requests targeting develop can be documented.");
  console.warn("Dry run: the pull request is not merged into develop. Previewing anyway.");
}

const [files, commits, architectureMarkdown] = await Promise.all([
  fetchAllPages(`pulls/${pullRequestNumber}/files`),
  fetchAllPages(`pulls/${pullRequestNumber}/commits`, 3),
  readFile(architectureDoc, "utf8").catch(() => ""),
]);

const runUrl = runId ? `https://github.com/${repository}/actions/runs/${runId}` : undefined;
const { title, blocks } = buildPrPage({
  pullRequest,
  files,
  commits,
  repository,
  runUrl,
  architectureMarkdown,
});
const batches = chunkBlocks(blocks);

if (dryRun) {
  const preview = JSON.stringify({ title, batches: batches.length, blocks }, null, 2);
  if (dryRunOutput) {
    await writeFile(dryRunOutput, `${preview}\n`);
    console.log(`Dry run: wrote ${blocks.length} blocks in ${batches.length} batch(es) to ${dryRunOutput}`);
  } else {
    console.log(preview);
  }
  process.exit(0);
}

const existing = await findExistingPage(title);
if (existing) {
  console.log(`Notion page already exists: ${existing.url}`);
  process.exit(0);
}

const [firstBatch, ...remainingBatches] = batches;
const created = await requestJson("https://api.notion.com/v1/pages", notionHeaders, {
  method: "POST",
  body: JSON.stringify({
    parent: { type: "page_id", page_id: parentPageId },
    properties: { title: { title: text(title) } },
    children: firstBatch,
  }),
});

if (!created.url) {
  throw new Error("Notion created the page without returning a page URL.");
}

try {
  for (const batch of remainingBatches) {
    await requestJson(`https://api.notion.com/v1/blocks/${created.id}/children`, notionHeaders, {
      method: "PATCH",
      body: JSON.stringify({ children: batch }),
    });
  }
} catch (error) {
  await requestJson(`https://api.notion.com/v1/pages/${created.id}`, notionHeaders, {
    method: "PATCH",
    body: JSON.stringify({ in_trash: true }),
  }).catch(() => undefined);
  throw new Error(`Moved the incomplete Notion page to trash. ${error.message}`);
}

console.log(`Created Notion page: ${created.url} (${blocks.length} blocks, ${batches.length} request(s))`);
