// 리뷰어 무작위 지정 로직 테스트

import assert from "node:assert/strict";
import { test } from "node:test";

import { eligibleCandidates, hasReviewer, parsePool, run, shuffle } from "./assign_reviewer.mjs";

function fakeCore() {
  const logs = { info: [], warning: [], failed: null, output: {} };
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
    setFailed: (message) => {
      logs.failed = message;
    },
    setOutput: (key, value) => {
      logs.output[key] = value;
    },
  };
}

function fakeGithub({ requested = { users: [], teams: [] }, reviews = [], collaborators = [], rejects = [] } = {}) {
  const calls = [];
  const rest = {
    pulls: {
      listRequestedReviewers: async () => ({ data: requested }),
      listReviews: "listReviews",
      requestReviewers: async ({ reviewers }) => {
        calls.push(reviewers[0]);
        if (rejects.includes(reviewers[0])) throw Object.assign(new Error("rejected"), { status: 422 });
      },
    },
    repos: { listCollaborators: "listCollaborators" },
  };
  return {
    calls,
    rest,
    paginate: async (endpoint) => (endpoint === "listReviews" ? reviews : collaborators),
  };
}

const context = (overrides = {}) => ({
  repo: { owner: "org", repo: "repo" },
  payload: { pull_request: { number: 3, draft: false, user: { login: "Author" }, ...overrides } },
});

test("REVIEWER_POOL 문자열을 중복 없이 파싱한다", () => {
  assert.deepEqual(parsePool(" @a, b\nc  A "), ["A", "b", "c"]);
  assert.deepEqual(parsePool(undefined), []);
});

test("요청된 리뷰어나 작성자 외 리뷰가 있으면 리뷰어가 있는 것으로 본다", () => {
  assert.equal(hasReviewer({ author: "x" }), false);
  assert.equal(hasReviewer({ requestedTeams: [{ slug: "t" }], author: "x" }), true);
  assert.equal(hasReviewer({ reviews: [{ user: { login: "X" } }], author: "x" }), false);
  assert.equal(hasReviewer({ reviews: [{ user: { login: "y" } }], author: "x" }), true);
});

test("작성자와 봇을 후보에서 제외한다", () => {
  assert.deepEqual(eligibleCandidates(["author", "b", "dependabot[bot]"], "AUTHOR"), ["b"]);
  assert.deepEqual(eligibleCandidates(["author", "b", "c"], "author", ["B"]), ["c"]);
});

test("리뷰 요청이 해제되어 0명이 되면 해제된 사용자를 제외하고 다시 지정한다", async () => {
  const github = fakeGithub();
  const core = fakeCore();
  const event = context();
  event.payload.requested_reviewer = { login: "b" };
  await run({ github, context: event, core, pool: "Author, b, c" });
  assert.deepEqual(github.calls, ["c"]);
});

test("shuffle은 원본을 바꾸지 않고 모든 원소를 유지한다", () => {
  const items = ["a", "b", "c", "d"];
  const result = shuffle(items, () => 0);
  assert.deepEqual(items, ["a", "b", "c", "d"]);
  assert.deepEqual([...result].sort(), items);
  assert.deepEqual(result, ["b", "c", "d", "a"]);
});

test("리뷰어가 없으면 작성자를 제외한 후보 한 명에게만 요청한다", async () => {
  const github = fakeGithub();
  const core = fakeCore();
  await run({ github, context: context(), core, pool: "Author, b, c" });
  assert.equal(github.calls.length, 1);
  assert.ok(["b", "c"].includes(github.calls[0]));
  assert.equal(core.logs.output.reviewer, github.calls[0]);
  assert.equal(core.logs.failed, null);
});

test("이미 리뷰어가 있으면 요청하지 않는다", async () => {
  const github = fakeGithub({ requested: { users: [{ login: "b" }], teams: [] } });
  const core = fakeCore();
  await run({ github, context: context(), core, pool: "b, c" });
  assert.deepEqual(github.calls, []);
});

test("초안 PR은 건너뛴다", async () => {
  const github = fakeGithub();
  const core = fakeCore();
  await run({ github, context: context({ draft: true }), core, pool: "b" });
  assert.deepEqual(github.calls, []);
});

test("요청이 거절되면 다음 후보로 넘어가고, 모두 실패하면 job을 실패 처리한다", async () => {
  const github = fakeGithub({ rejects: ["b", "c"] });
  const core = fakeCore();
  await run({ github, context: context(), core, pool: "b, c" });
  assert.deepEqual([...github.calls].sort(), ["b", "c"]);
  assert.equal(core.logs.warning.length, 2);
  assert.match(core.logs.failed, /리뷰어를 지정하지 못했습니다/);
});

test("후보 목록이 비어 있으면 쓰기 권한이 있는 협업자 중에서 고른다", async () => {
  const github = fakeGithub({
    collaborators: [
      { login: "Author", type: "User", permissions: { push: true } },
      { login: "reader", type: "User", permissions: { push: false } },
      { login: "writer", type: "User", permissions: { push: true } },
      { login: "app[bot]", type: "Bot", permissions: { push: true } },
    ],
  });
  const core = fakeCore();
  await run({ github, context: context(), core, pool: "" });
  assert.deepEqual(github.calls, ["writer"]);
});
