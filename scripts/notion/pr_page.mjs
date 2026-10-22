// 병합된 PR의 GitHub 정보로 Notion 페이지 제목과 블록 목록을 구성한다. 네트워크 호출은 하지 않는다.

import {
  bulleted,
  callout,
  code,
  enforceLimits,
  heading,
  paragraph,
  text,
  toggle,
  toRichText,
} from "./blocks.mjs";
import { architectureDiagram, changedFilesDiagram } from "./diagrams.mjs";
import { markdownToBlocks } from "./markdown.mjs";

const COMMIT_API_LIMIT = 250;

export function pageTitle(pullRequest) {
  return `[PR #${pullRequest.number}] ${pullRequest.title}`.slice(0, 2000);
}

// ISO 시각을 한국 표준시 "YYYY-MM-DD HH:mm KST" 형식으로 바꾼다.
export function formatKst(iso) {
  if (!iso) return "확인할 수 없음";
  const local = new Date(iso).toLocaleString("sv-SE", { timeZone: "Asia/Seoul" });
  return `${local.slice(0, 16)} KST`;
}

function sumChanges(files) {
  return files.reduce(
    (sum, file) => ({
      additions: sum.additions + (file.additions ?? 0),
      deletions: sum.deletions + (file.deletions ?? 0),
    }),
    { additions: 0, deletions: 0 }
  );
}

function labeled(label, value, link) {
  return bulleted(toRichText([{ text: `${label}: `, bold: true }, { text: value, link }]));
}

// 변경 파일을 "상태  +추가  -삭제  경로" 형식의 고정폭 텍스트로 만든다.
export function formatFiles(files) {
  return files
    .map((file) => {
      const path =
        file.status === "renamed" && file.previous_filename
          ? `${file.previous_filename} → ${file.filename}`
          : file.filename;
      const additions = `+${file.additions ?? 0}`.padStart(6);
      const deletions = `-${file.deletions ?? 0}`.padStart(6);
      return `${String(file.status).padEnd(9)}${additions}${deletions}  ${path}`;
    })
    .join("\n");
}

// 커밋을 "짧은 SHA  제목 (작성자)" 형식의 텍스트로 만든다.
export function formatCommits(commits) {
  return commits
    .map((commit) => {
      const subject = String(commit.commit?.message ?? "").split("\n")[0];
      const author = commit.author?.login ?? commit.commit?.author?.name ?? "unknown";
      return `${String(commit.sha).slice(0, 7)}  ${subject} (${author})`;
    })
    .join("\n");
}

function documentationCandidates(files) {
  return files.filter((file) => {
    const name = file.filename.toLowerCase();
    return name === "readme.md" || name.startsWith("docs/");
  });
}

// PR, 변경 파일, 커밋 정보로 Notion 페이지 블록을 만든다.
// architectureMarkdown이 있으면 서비스 연결 다이어그램에 변경 모듈을 강조해 넣는다.
export function buildPrPage({ pullRequest, files, commits, repository, runUrl, architectureMarkdown }) {
  const repoUrl = `https://github.com/${repository}`;
  const ref = pullRequest.merge_commit_sha ?? pullRequest.base?.ref ?? "develop";
  const context = { repoUrl, blobBase: `${repoUrl}/blob/${ref}`, baseHeading: 3 };
  const { additions, deletions } = sumChanges(files);
  const author = pullRequest.user?.login ?? "unknown";
  const head = pullRequest.head?.ref ?? "?";
  const base = pullRequest.base?.ref ?? "?";
  const body = pullRequest.body?.trim() ?? "";
  const labels = (pullRequest.labels ?? []).map((label) => label.name).filter(Boolean);
  const mergeSha = pullRequest.merge_commit_sha;

  const blocks = [
    callout(
      text(
        `PR #${pullRequest.number} · @${author} · ${head} → ${base} · ` +
          `${formatKst(pullRequest.merged_at)} 병합 · 파일 ${files.length}개 ` +
          `(+${additions} / -${deletions}) · 커밋 ${commits.length}개`
      ),
      "🔀",
      "gray_background"
    ),
    heading(2, text("PR 정보")),
    labeled("PR", `#${pullRequest.number} ${pullRequest.title}`, pullRequest.html_url),
    labeled("작성자", `@${author}`, `https://github.com/${author}`),
    labeled("브랜치", `${head} → ${base}`),
    labeled(
      "병합",
      `${formatKst(pullRequest.merged_at)} · @${pullRequest.merged_by?.login ?? "unknown"}`
    ),
    labeled(
      "병합 커밋",
      mergeSha ? mergeSha.slice(0, 7) : "확인할 수 없음",
      mergeSha ? `${repoUrl}/commit/${mergeSha}` : undefined
    ),
  ];

  if (labels.length) blocks.push(labeled("라벨", labels.join(", ")));
  if (runUrl) blocks.push(labeled("자동화 실행", runUrl.split("/").at(-1), runUrl));

  blocks.push(heading(2, text("PR 설명 (작성자 제공)")));
  if (body) {
    const converted = markdownToBlocks(body, context);
    blocks.push(...(converted.length ? converted : [paragraph(text("표시할 내용이 없습니다."))]));
    blocks.push(toggle(text("PR 설명 원문 (Markdown)"), [code(body, "markdown")]));
  } else {
    blocks.push(paragraph(text("PR 설명이 비어 있습니다.")));
  }

  blocks.push(heading(2, text(`커밋 (${commits.length}개)`)));
  blocks.push(code(formatCommits(commits) || "커밋 정보가 없습니다.", "plain text"));
  if (commits.length >= COMMIT_API_LIMIT) {
    blocks.push(
      paragraph(text(`GitHub API는 PR 커밋을 최대 ${COMMIT_API_LIMIT}개까지 제공합니다.`))
    );
  }

  blocks.push(heading(2, text(`변경 파일 (${files.length}개 · +${additions} / -${deletions})`)));
  blocks.push(code(formatFiles(files) || "변경 파일이 없습니다.", "plain text"));

  const filesDiagram = changedFilesDiagram(files, { rootLabel: repository.split("/").at(-1) });
  if (filesDiagram) {
    blocks.push(
      heading(2, text("변경 구조 다이어그램")),
      paragraph(
        text("변경 파일 경로와 상태(추가·수정·삭제·이름 변경)만으로 자동 생성했습니다.")
      ),
      code(filesDiagram, "mermaid")
    );
  }

  blocks.push(heading(2, text("서비스 연결 구조")));
  const architecture = architectureMarkdown
    ? architectureDiagram(architectureMarkdown, files)
    : null;
  if (architecture) {
    const summary = architecture.changed.length
      ? `docs/architecture.md의 서비스 연결 다이어그램에서 이번 PR이 변경한 모듈을 강조했습니다: ` +
        architecture.changed
          .map(({ node, prefixes }) => `${node} (${prefixes.join(", ")})`)
          .join(", ")
      : "docs/architecture.md의 서비스 연결 다이어그램입니다. 이번 PR은 매핑된 모듈을 변경하지 않았습니다.";
    blocks.push(paragraph(text(summary)), code(architecture.mermaid, "mermaid"));
  } else {
    blocks.push(
      paragraph(
        text("docs/architecture.md에서 `%% map` 매핑이 있는 mermaid 다이어그램을 찾지 못했습니다.")
      )
    );
  }

  blocks.push(heading(2, text("문서화 검토 후보")));
  const candidates = documentationCandidates(files);
  if (candidates.length) {
    for (const file of candidates.slice(0, 25)) {
      blocks.push(bulleted(text(`${file.filename} 변경됨 — 최신 설명과 코드의 일치 여부 검토`)));
    }
    if (candidates.length > 25) {
      blocks.push(
        paragraph(
          text(`문서 후보 경로 ${candidates.length - 25}개는 위 변경 파일 목록에서 확인하세요.`)
        )
      );
    }
  } else {
    blocks.push(paragraph(text("README.md 또는 docs/ 변경은 확인되지 않았습니다.")));
  }

  blocks.push(
    heading(2, text("해석 범위")),
    paragraph(
      text(
        "이 페이지는 PR 설명과 GitHub 변경 파일·커밋 정보로 생성했습니다. 다이어그램은 파일 경로 기준으로만 " +
          "만들었으며, 설계 영향·코드 동작의 의미·미확인 사항은 자동 추론하지 않았으므로 팀 검토가 필요합니다."
      )
    )
  );

  return { title: pageTitle(pullRequest), blocks: enforceLimits(blocks) };
}
