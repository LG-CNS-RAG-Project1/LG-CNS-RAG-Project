// PR에 리뷰어가 한 명도 없으면 후보 중 한 명을 무작위로 골라 리뷰를 요청한다.
// actions/github-script에서 run({ github, context, core })로 호출한다.
// 후보는 REVIEWER_POOL(쉼표·공백 구분 GitHub ID) 또는, 비어 있으면 저장소 협업자 목록에서 정한다.

// REVIEWER_POOL 문자열을 중복 없는 GitHub ID 목록으로 바꾼다.
export function parsePool(value) {
  const logins = String(value ?? "")
    .split(/[\s,]+/)
    .map((login) => login.trim().replace(/^@/, ""))
    .filter(Boolean);
  return [...new Map(logins.map((login) => [login.toLowerCase(), login])).values()];
}

// 요청된 리뷰어(사용자·팀) 또는 작성자 외 사용자의 리뷰가 하나라도 있으면 true.
export function hasReviewer({ requestedUsers = [], requestedTeams = [], reviews = [], author }) {
  const authorLogin = String(author ?? "").toLowerCase();
  return (
    requestedUsers.length > 0 ||
    requestedTeams.length > 0 ||
    reviews.some((review) => review.user && review.user.login.toLowerCase() !== authorLogin)
  );
}

// 작성자, 제외 대상(방금 리뷰 요청이 해제된 사용자 등), 봇 계정을 후보에서 뺀다.
export function eligibleCandidates(pool, author, excluded = []) {
  const blocked = new Set([author, ...excluded].filter(Boolean).map((login) => login.toLowerCase()));
  return pool.filter(
    (login) => !blocked.has(login.toLowerCase()) && !login.toLowerCase().endsWith("[bot]")
  );
}

// Fisher-Yates 방식으로 섞은 새 배열을 반환한다.
export function shuffle(items, random = Math.random) {
  const result = [...items];
  for (let index = result.length - 1; index > 0; index -= 1) {
    const target = Math.floor(random() * (index + 1));
    [result[index], result[target]] = [result[target], result[index]];
  }
  return result;
}

async function collaboratorLogins(github, owner, repo) {
  const collaborators = await github.paginate(github.rest.repos.listCollaborators, {
    owner,
    repo,
    affiliation: "all",
    per_page: 100,
  });
  return collaborators
    .filter((user) => user.type === "User" && (user.permissions?.push || user.permissions?.admin))
    .map((user) => user.login);
}

// pull_request_target 이벤트의 PR에 리뷰어가 없으면 무작위로 한 명을 요청한다.
// 후보 전원에게 요청이 실패하면 job을 실패 처리해 리뷰어 누락을 드러낸다.
export async function run({ github, context, core, pool = process.env.REVIEWER_POOL }) {
  const pullRequest = context.payload.pull_request;
  if (!pullRequest) {
    core.setFailed("pull_request 이벤트에서만 실행할 수 있습니다.");
    return;
  }
  if (pullRequest.draft) {
    core.info("초안 PR이므로 리뷰어 지정을 건너뜁니다.");
    return;
  }

  const { owner, repo } = context.repo;
  const pull_number = pullRequest.number;
  const author = pullRequest.user.login;

  const [{ data: requested }, reviews] = await Promise.all([
    github.rest.pulls.listRequestedReviewers({ owner, repo, pull_number }),
    github.paginate(github.rest.pulls.listReviews, { owner, repo, pull_number, per_page: 100 }),
  ]);

  if (hasReviewer({ requestedUsers: requested.users, requestedTeams: requested.teams, reviews, author })) {
    core.info("이미 리뷰어가 지정되어 있어 변경하지 않습니다.");
    return;
  }

  let names = parsePool(pool);
  if (!names.length) names = await collaboratorLogins(github, owner, repo);
  const removed = context.payload.requested_reviewer?.login;
  const candidates = shuffle(eligibleCandidates(names, author, removed ? [removed] : []));

  for (const login of candidates) {
    try {
      await github.rest.pulls.requestReviewers({ owner, repo, pull_number, reviewers: [login] });
      core.info(`리뷰어 지정: @${login}`);
      core.setOutput("reviewer", login);
      await core.summary
        .addHeading("리뷰어 자동 지정", 3)
        .addRaw(`PR #${pull_number} → @${login} (후보 ${candidates.length}명 중 무작위 선택)`)
        .write();
      return;
    } catch (error) {
      core.warning(`@${login}에게 리뷰를 요청하지 못했습니다: HTTP ${error.status ?? "unknown"}`);
    }
  }

  core.setFailed(
    "리뷰어를 지정하지 못했습니다. REVIEWER_POOL 값과 후보의 저장소 협업자 권한을 확인하세요."
  );
}
