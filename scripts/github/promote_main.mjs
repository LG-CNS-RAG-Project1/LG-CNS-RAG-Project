// develop이 main보다 앞서 있으면 develop → main 배포 승격 PR을 열거나 본문을 갱신하고,
// 리뷰어가 없으면 한 명을 요청한다. 병합(= Streamlit Community Cloud 배포)은 사람이 승인한다.
// actions/github-script에서 run({ github, context, core })로 호출한다.

import { eligibleCandidates, parsePool, shuffle } from "./assign_reviewer.mjs";

export const BASE = "main";
export const HEAD = "develop";
export const TITLE = "develop → main 배포 승격";
export const BOT = "github-actions[bot]";
const PAGE_SIZE = 100;
const MAX_PAGES = 10;
const LOOKUP_BATCH = 10;

// PR 제목을 본문 한 줄에 넣을 수 있게 정리한다. 줄바꿈·앞뒤 공백을 없애고 @멘션 알림을 막는다.
export function safeTitle(title) {
  return String(title ?? "")
    .replace(/\s+/g, " ")
    .trim()
    .replace(/@/g, "@​");
}

// 커밋별 연결 PR 목록에서 develop에 병합된 PR만 번호순으로 중복 없이 모은다(스쿼시 병합 포함).
export function mergedPulls(pullsPerCommit) {
  const byNumber = new Map();
  for (const pulls of pullsPerCommit) {
    for (const pull of pulls ?? []) {
      if (pull.merged_at && pull.base?.ref === HEAD) {
        byNumber.set(pull.number, { number: pull.number, title: pull.title });
      }
    }
  }
  return [...byNumber.values()].sort((a, b) => a.number - b.number);
}

// 승격 PR 본문. 병합 방식과 배포 영향, 포함된 PR을 적는다.
export function buildBody({ pulls, headSha, aheadBy, runUrl }) {
  const lines = [
    "develop에서 검증을 마친 변경을 main에 반영하는 자동 승격 PR입니다.",
    "",
    "> **병합하면 바로 Streamlit Community Cloud 앱에 배포됩니다.**",
    "> 병합 버튼 옆 ▼ → **Create a merge commit**으로 병합하세요. Squash·Rebase는 develop과 main 이력을 어긋나게 합니다.",
    "",
    `- develop 커밋: \`${String(headSha).slice(0, 7)}\` (main보다 커밋 ${aheadBy}개 앞섬)`,
  ];
  if (runUrl) lines.push(`- 통과한 develop CI: ${runUrl}`);
  lines.push("", "### 포함된 PR");
  if (pulls.length) {
    for (const pull of pulls) lines.push(`- #${pull.number} ${safeTitle(pull.title)}`);
  } else {
    lines.push("- 연결된 PR을 찾지 못했습니다. Commits 탭을 확인하세요.");
  }
  lines.push(
    "",
    "### 병합 뒤 확인",
    "- [ ] Actions의 **SCC Smoke** 실행이 성공했다(앱 비밀번호 화면과 버전 확인)",
    "",
    "_이 본문은 Promote 워크플로가 develop이 바뀔 때마다 다시 씁니다._"
  );
  return lines.join("\n");
}

// 요청 중인 리뷰어가 없고 유효한 승인도 없으면 리뷰어가 필요하다.
// develop이 바뀌어 무효화된 승인(DISMISSED)은 유효한 승인으로 보지 않는다.
export function needsReviewer({ requestedUsers = [], requestedTeams = [], reviews = [] }) {
  if (requestedUsers.length || requestedTeams.length) return false;
  return !reviews.some((review) => review.state === "APPROVED");
}

// 승인이 무효화된 직전 리뷰어를 먼저, 나머지 후보는 무작위 순서로 돌려준다.
export function reviewerOrder(pool, reviews, author, random = Math.random) {
  const previous = eligibleCandidates(
    parsePool(
      reviews
        .filter((review) => review.state === "DISMISSED" && review.user)
        .map((review) => review.user.login)
        .join(",")
    ),
    author
  );
  const taken = new Set(previous.map((login) => login.toLowerCase()));
  const rest = eligibleCandidates(pool, author).filter((login) => !taken.has(login.toLowerCase()));
  return [...previous, ...shuffle(rest, random)];
}

async function compareFromMain(github, owner, repo, headSha) {
  const commits = [];
  let aheadBy = 0;
  for (let page = 1; page <= MAX_PAGES; page += 1) {
    const { data } = await github.rest.repos.compareCommitsWithBasehead({
      owner,
      repo,
      basehead: `${BASE}...${headSha}`,
      per_page: PAGE_SIZE,
      page,
    });
    aheadBy = data.ahead_by;
    commits.push(...data.commits);
    if (data.commits.length < PAGE_SIZE || commits.length >= data.total_commits) break;
  }
  return { aheadBy, shas: commits.map((commit) => commit.sha) };
}

async function pullsForCommits(github, owner, repo, shas) {
  const results = [];
  for (let index = 0; index < shas.length; index += LOOKUP_BATCH) {
    const batch = shas.slice(index, index + LOOKUP_BATCH);
    const responses = await Promise.all(
      batch.map((commit_sha) =>
        github.rest.repos.listPullRequestsAssociatedWithCommit({ owner, repo, commit_sha })
      )
    );
    results.push(...responses.map((response) => response.data));
  }
  return results;
}

async function requestReviewer(github, core, { owner, repo, pull_number, author, pool }) {
  const [{ data: requested }, reviews] = await Promise.all([
    github.rest.pulls.listRequestedReviewers({ owner, repo, pull_number }),
    github.paginate(github.rest.pulls.listReviews, { owner, repo, pull_number, per_page: 100 }),
  ]);
  if (!needsReviewer({ requestedUsers: requested.users, requestedTeams: requested.teams, reviews })) {
    core.info("리뷰어가 이미 요청되었거나 유효한 승인이 있어 리뷰어를 바꾸지 않습니다.");
    return;
  }
  for (const login of reviewerOrder(parsePool(pool), reviews, author)) {
    try {
      await github.rest.pulls.requestReviewers({ owner, repo, pull_number, reviewers: [login] });
      core.info(`리뷰어 요청: @${login}`);
      return;
    } catch (error) {
      core.warning(`@${login}에게 리뷰를 요청하지 못했습니다: HTTP ${error.status ?? "unknown"}`);
    }
  }
  core.warning("리뷰어를 요청하지 못했습니다. REVIEWER_POOL과 협업자 권한을 확인하세요.");
}

// develop의 현재 커밋 기준으로 승격 PR을 맞춘다.
export async function run({
  github,
  context,
  core,
  pool = process.env.REVIEWER_POOL,
  runUrl = process.env.CI_RUN_URL,
}) {
  const { owner, repo } = context.repo;
  const { data: branch } = await github.rest.repos.getBranch({ owner, repo, branch: HEAD });
  const headSha = branch.commit.sha;
  const { aheadBy, shas } = await compareFromMain(github, owner, repo, headSha);
  if (aheadBy === 0) {
    core.info("develop에 main으로 보낼 새 커밋이 없어 승격 PR이 필요 없습니다.");
    return;
  }

  const pulls = mergedPulls(await pullsForCommits(github, owner, repo, shas));
  const body = buildBody({ pulls, headSha, aheadBy, runUrl });
  const { data: open } = await github.rest.pulls.list({
    owner,
    repo,
    state: "open",
    base: BASE,
    head: `${owner}:${HEAD}`,
  });

  let pullRequest = open[0];
  if (pullRequest && pullRequest.user?.login !== BOT) {
    core.notice(
      `사람이 연 승격 PR #${pullRequest.number}이 있어 본문과 리뷰어를 바꾸지 않습니다.`
    );
    return;
  }
  if (pullRequest) {
    await github.rest.pulls.update({ owner, repo, pull_number: pullRequest.number, title: TITLE, body });
    core.info(`승격 PR #${pullRequest.number} 본문을 갱신했습니다.`);
  } else {
    try {
      ({ data: pullRequest } = await github.rest.pulls.create({
        owner,
        repo,
        title: TITLE,
        head: HEAD,
        base: BASE,
        body,
      }));
    } catch (error) {
      if (error.status === 403 && /not permitted to create/i.test(String(error.message))) {
        core.setFailed(
          "GitHub Actions가 PR을 만들 수 없습니다. 저장소 Settings → Actions → General → Workflow permissions에서 " +
            "'Allow GitHub Actions to create and approve pull requests'를 켜세요(회색이면 조직 설정에서 켭니다)."
        );
        return;
      }
      throw error;
    }
    core.info(`승격 PR #${pullRequest.number}을 열었습니다.`);
  }

  await requestReviewer(github, core, {
    owner,
    repo,
    pull_number: pullRequest.number,
    author: pullRequest.user?.login ?? BOT,
    pool,
  });
  await core.summary
    .addHeading("develop → main 배포 승격", 3)
    .addRaw(`PR #${pullRequest.number} · develop \`${headSha.slice(0, 7)}\` · 포함 PR ${pulls.length}개`)
    .write();
}
