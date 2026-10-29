// develop → main 배포 승격 PR 자동화 테스트

import assert from "node:assert/strict";
import { test } from "node:test";

import {
  BOT,
  TITLE,
  buildBody,
  mergedPulls,
  needsReviewer,
  reviewerOrder,
  run,
  safeTitle,
} from "./promote_main.mjs";

function fakeCore() {
  const logs = { info: [], warning: [], notice: [], failed: null };
  const summary = {
    addHeading: () => summary,
    addRaw: () => summary,
    write: async () => undefined,
  };
  return {
    logs,
    summary,
    info: (message) => logs.info.push(message),
    warning: (message) => logs.warning.push(message),
    notice: (message) => logs.notice.push(message),
    setFailed: (message) => {
      logs.failed = message;
    },
  };
}

function fakeGithub({
  aheadBy = 2,
  commits = ["c1", "c2"],
  pullsBySha = {},
  open = [],
  createError = null,
  requested = { users: [], teams: [] },
  reviews = [],
} = {}) {
  const calls = { created: [], updated: [], reviewers: [] };
  const rest = {
    repos: {
      getBranch: async () => ({ data: { commit: { sha: "abcdef1234567890" } } }),
      compareCommitsWithBasehead: async ({ basehead }) => {
        calls.basehead = basehead;
        return {
          data: {
            ahead_by: aheadBy,
            total_commits: commits.length,
            commits: commits.map((sha) => ({ sha })),
          },
        };
      },
      listPullRequestsAssociatedWithCommit: async ({ commit_sha }) => ({
        data: pullsBySha[commit_sha] ?? [],
      }),
    },
    pulls: {
      list: async () => ({ data: open }),
      create: async (params) => {
        if (createError) throw createError;
        calls.created.push(params);
        return { data: { number: 77, user: { login: BOT } } };
      },
      update: async (params) => {
        calls.updated.push(params);
      },
      listRequestedReviewers: async () => ({ data: requested }),
      listReviews: "listReviews",
      requestReviewers: async ({ reviewers }) => {
        calls.reviewers.push(reviewers[0]);
      },
    },
  };
  return { calls, rest, paginate: async () => reviews };
}

const context = { repo: { owner: "org", repo: "repo" } };
const merged = (number, title, ref = "develop") => ({
  number,
  title,
  merged_at: "2026-10-29T00:00:00Z",
  base: { ref },
});

test("PR 제목의 줄바꿈과 @멘션을 무력화한다", () => {
  assert.equal(safeTitle("  고침\n@someone 확인 "), "고침 @​someone 확인");
  assert.equal(safeTitle(undefined), "");
});

test("develop에 병합된 PR만 번호순으로 중복 없이 모은다", () => {
  const pulls = mergedPulls([
    [merged(5, "B")],
    [merged(3, "A"), merged(5, "B")],
    [{ number: 9, title: "열린 PR", merged_at: null, base: { ref: "develop" } }],
    [merged(8, "main 대상", "main")],
  ]);
  assert.deepEqual(
    pulls.map((pull) => pull.number),
    [3, 5]
  );
});

test("본문에 병합 방식·배포 경고·포함 PR을 적는다", () => {
  const body = buildBody({
    pulls: [{ number: 3, title: "@a 기능" }],
    headSha: "abcdef1234",
    aheadBy: 4,
    runUrl: "https://ci",
  });
  assert.match(body, /Create a merge commit/);
  assert.match(body, /Streamlit Community Cloud/);
  assert.match(body, /`abcdef1` \(main보다 커밋 4개 앞섬\)/);
  assert.match(body, /- #3 @​a 기능/);
  assert.match(body, /https:\/\/ci/);
});

test("무효화된 승인은 승인으로 보지 않는다", () => {
  assert.equal(needsReviewer({ reviews: [{ state: "DISMISSED" }] }), true);
  assert.equal(needsReviewer({ reviews: [{ state: "APPROVED" }] }), false);
  assert.equal(needsReviewer({ requestedUsers: [{ login: "a" }] }), false);
});

test("승인이 무효화된 직전 리뷰어를 먼저 요청 후보로 둔다", () => {
  const order = reviewerOrder(
    ["a", "b", "c"],
    [
      { state: "DISMISSED", user: { login: "c" } },
      { state: "COMMENTED", user: { login: "b" } },
    ],
    BOT,
    () => 0
  );
  assert.equal(order[0], "c");
  assert.deepEqual([...order].sort(), ["a", "b", "c"]);
});

test("develop에 새 커밋이 없으면 PR을 만들지 않는다", async () => {
  const github = fakeGithub({ aheadBy: 0, commits: [] });
  const core = fakeCore();
  await run({ github, context, core, pool: "a" });
  assert.equal(github.calls.created.length, 0);
  assert.equal(github.calls.updated.length, 0);
});

test("승격 PR이 없으면 develop 커밋 기준으로 만들고 리뷰어를 요청한다", async () => {
  const github = fakeGithub({ pullsBySha: { c1: [merged(3, "기능")] } });
  const core = fakeCore();
  await run({ github, context, core, pool: "a, b" });
  assert.equal(github.calls.basehead, "main...abcdef1234567890");
  assert.equal(github.calls.created.length, 1);
  assert.equal(github.calls.created[0].title, TITLE);
  assert.equal(github.calls.created[0].head, "develop");
  assert.equal(github.calls.created[0].base, "main");
  assert.match(github.calls.created[0].body, /#3 기능/);
  assert.equal(github.calls.reviewers.length, 1);
  assert.equal(core.logs.failed, null);
});

test("봇이 연 승격 PR은 본문만 갱신한다", async () => {
  const github = fakeGithub({
    open: [{ number: 12, user: { login: BOT } }],
    requested: { users: [{ login: "a" }], teams: [] },
  });
  const core = fakeCore();
  await run({ github, context, core, pool: "a, b" });
  assert.equal(github.calls.created.length, 0);
  assert.equal(github.calls.updated[0].pull_number, 12);
  assert.equal(github.calls.reviewers.length, 0);
});

test("사람이 연 develop→main PR은 건드리지 않는다", async () => {
  const github = fakeGithub({ open: [{ number: 48, user: { login: "Ryu-Jemu" } }] });
  const core = fakeCore();
  await run({ github, context, core, pool: "a" });
  assert.equal(github.calls.created.length, 0);
  assert.equal(github.calls.updated.length, 0);
  assert.equal(github.calls.reviewers.length, 0);
  assert.match(core.logs.notice[0], /#48/);
});

test("Actions의 PR 생성 권한이 꺼져 있으면 설정 경로를 안내하며 실패한다", async () => {
  const error = Object.assign(
    new Error("GitHub Actions is not permitted to create or approve pull requests."),
    { status: 403 }
  );
  const github = fakeGithub({ createError: error });
  const core = fakeCore();
  await run({ github, context, core, pool: "a" });
  assert.match(core.logs.failed, /Allow GitHub Actions to create and approve pull requests/);
});
