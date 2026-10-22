const repository = process.env.GITHUB_REPOSITORY;
const githubToken = process.env.GITHUB_TOKEN;
const notionToken = process.env.NOTION_API_TOKEN;
const parentPageId = process.env.NOTION_PARENT_PAGE_ID;
const pullRequestNumber = Number(process.env.PR_NUMBER);
const runId = process.env.GITHUB_RUN_ID;

if (!repository || !githubToken || !notionToken || !parentPageId || !runId) {
  throw new Error("Required GitHub Actions environment variables are missing.");
}

if (!Number.isSafeInteger(pullRequestNumber) || pullRequestNumber < 1) {
  throw new Error("PR_NUMBER must be a positive integer.");
}

const githubHeaders = {
  Accept: "application/vnd.github+json",
  Authorization: `Bearer ${githubToken}`,
  "X-GitHub-Api-Version": "2022-11-28",
};

const notionHeaders = {
  Authorization: `Bearer ${notionToken}`,
  "Content-Type": "application/json",
  "Notion-Version": "2026-03-11",
};

async function requestJson(url, headers, options = {}) {
  const response = await fetch(url, {
    ...options,
    headers: { ...headers, ...options.headers },
  });

  if (!response.ok) {
    const service = url.startsWith("https://api.notion.com/") ? "Notion" : "GitHub";
    throw new Error(`${service} API request failed with HTTP ${response.status}.`);
  }

  return response.json();
}

function richText(content, link) {
  const text = { content: String(content).slice(0, 2000) };
  if (link) text.link = { url: link };
  return { type: "text", text };
}

function paragraph(content, link) {
  return {
    object: "block",
    type: "paragraph",
    paragraph: { rich_text: [richText(content, link)] },
  };
}

function bullet(content) {
  return {
    object: "block",
    type: "bulleted_list_item",
    bulleted_list_item: { rich_text: [richText(content)] },
  };
}

function heading(content) {
  return {
    object: "block",
    type: "heading_2",
    heading_2: { rich_text: [richText(content)] },
  };
}

function pageTitle(page) {
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
      pageTitle(page) === title &&
      page.parent?.type === "page_id" &&
      page.parent.page_id.replaceAll("-", "").toLowerCase() ===
        parentPageId.replaceAll("-", "").toLowerCase()
  );
}

const [owner, repo] = repository.split("/");
if (!owner || !repo || repository.split("/").length !== 2) {
  throw new Error("GITHUB_REPOSITORY must use owner/repository form.");
}

const pullRequest = await requestJson(
  `https://api.github.com/repos/${owner}/${repo}/pulls/${pullRequestNumber}`,
  githubHeaders
);

if (
  pullRequest.base?.ref !== "develop" ||
  pullRequest.state !== "closed" ||
  !pullRequest.merged_at
) {
  throw new Error("Only merged pull requests targeting develop can be documented.");
}

const files = [];

for (let page = 1; ; page += 1) {
  const batch = await requestJson(
    `https://api.github.com/repos/${owner}/${repo}/pulls/${pullRequestNumber}/files?per_page=100&page=${page}`,
    githubHeaders
  );

  files.push(...batch);
  if (batch.length < 100) break;
}

const title = `[PR #${pullRequest.number}] ${pullRequest.title}`.slice(0, 2000);
const existing = await findExistingPage(title);

if (existing) {
  console.log(`Notion page already exists: ${existing.url}`);
  process.exit(0);
}

const fileLimit = 60;
const shownFiles = files.slice(0, fileLimit);
const documentationCandidates = files.filter(
  (file) =>
    file.filename.toLowerCase() === "readme.md" ||
    file.filename.toLowerCase().startsWith("docs/")
);

const children = [
  heading("PR 정보"),
  paragraph(`PR #${pullRequest.number}: ${pullRequest.title}`, pullRequest.html_url),
  paragraph(`병합 커밋: ${pullRequest.merge_commit_sha ?? "확인할 수 없음"}`),
  paragraph(
    `자동화 실행: ${runId}`,
    `https://github.com/${repository}/actions/runs/${runId}`
  ),
  heading("PR 설명 (작성자 제공)"),
  paragraph(pullRequest.body?.trim() || "PR 설명이 비어 있습니다."),
  heading(`변경 파일 (${files.length}개)`),
];

for (const file of shownFiles) {
  children.push(
    bullet(`${file.status}: ${file.filename} (+${file.additions}/-${file.deletions})`)
  );
}

if (files.length > fileLimit) {
  children.push(
    paragraph(
      `목록이 길어 처음 ${fileLimit}개 경로만 표시했습니다. 전체 파일은 PR의 Files changed 탭에서 확인하세요.`
    )
  );
}

children.push(heading("문서화 검토 후보"));

if (documentationCandidates.length) {
  for (const file of documentationCandidates.slice(0, 25)) {
    children.push(
      bullet(`${file.filename} 변경됨 — 최신 설명과 코드의 일치 여부 검토`)
    );
  }

  if (documentationCandidates.length > 25) {
    children.push(
      paragraph(
        `문서 후보 경로 ${documentationCandidates.length - 25}개는 PR의 Files changed 탭에서 확인하세요.`
      )
    );
  }
} else {
  children.push(paragraph("README.md 또는 docs/ 변경은 확인되지 않았습니다."));
}

children.push(
  heading("해석 범위"),
  paragraph(
    "이 페이지는 PR 설명과 GitHub 변경 파일 정보로 생성했습니다. 설계 영향, 코드 동작의 의미, 미확인 사항은 자동 추론하지 않았으므로 팀 검토가 필요합니다."
  )
);

const created = await requestJson("https://api.notion.com/v1/pages", notionHeaders, {
  method: "POST",
  body: JSON.stringify({
    parent: { type: "page_id", page_id: parentPageId },
    properties: { title: { title: [richText(title)] } },
    children,
  }),
});

if (!created.url) {
  throw new Error("Notion created the page without returning a page URL.");
}

console.log(`Created Notion page: ${created.url}`);