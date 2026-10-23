// PR 분석에 필요한 GitHub 정보를 읽는다. PR·파일·커밋·CI 결과는 REST API로, 충돌 파일은 git merge-tree로 계산한다.
// 이 모듈은 GitHub에 쓰지 않으며, PR 코드를 checkout하거나 실행하지 않는다(객체만 받아 비교한다).
import { spawnSync } from "node:child_process";
import { CI_JOBS } from "./lib.mjs";

const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

export function createGitHub({ repository, token, retryDelayMs = 1000 }) {
  // GET 요청이다. 429·5xx 응답과 연결 오류(오래 기다리는 사이 끊긴 연결의 EPIPE 등)는 최대 3번 다시 보낸다.
  async function get(path, attempt = 1) {
    let response;
    try {
      response = await fetch(`https://api.github.com/${path}`, {
        headers: {
          Accept: "application/vnd.github+json",
          "X-GitHub-Api-Version": "2022-11-28",
          ...(token ? { Authorization: `Bearer ${token}` } : {}),
        },
      });
    } catch (error) {
      if (attempt >= 4) throw error;
      await sleep(retryDelayMs * 2 ** attempt);
      return get(path, attempt + 1);
    }
    if ((response.status === 429 || response.status >= 500) && attempt < 4) {
      await sleep(Math.min(Number(response.headers.get("retry-after")) * 1000 || retryDelayMs * 2 ** attempt, 60_000));
      return get(path, attempt + 1);
    }
    if (!response.ok) throw new Error(`GitHub API ${response.status}: ${path.split("?")[0]}`);
    return response.json();
  }

  async function getAll(path, maxPages = 30) {
    const items = [];
    for (let page = 1; page <= maxPages; page += 1) {
      const batch = await get(`${path}${path.includes("?") ? "&" : "?"}per_page=100&page=${page}`);
      items.push(...batch);
      if (batch.length < 100) break;
    }
    return items;
  }

  const repo = `repos/${repository}`;
  return {
    pull: (number) => get(`${repo}/pulls/${number}`),
    files: (number) => getAll(`${repo}/pulls/${number}/files`),
    commits: (number) => getAll(`${repo}/pulls/${number}/commits`, 3),
    commit: (sha) => get(`${repo}/commits/${sha}`),
    branchSha: async (branch) => (await get(`${repo}/branches/${branch}`)).commit.sha,
    mergeBase: async (base, head) => (await get(`${repo}/compare/${base}...${head}`)).merge_base_commit.sha,
    ciRuns: async (headSha) =>
      (await get(`${repo}/actions/runs?head_sha=${headSha}&event=pull_request&per_page=50`)).workflow_runs
        .filter((run) => String(run.path).startsWith(".github/workflows/ci.yml"))
        .sort((a, b) => b.created_at.localeCompare(a.created_at)),
    runJobs: async (runId) => (await get(`${repo}/actions/runs/${runId}/jobs?per_page=100`)).jobs,
  };
}

// mergeable이 계산될 때까지 PR을 다시 읽는다(최대 5회, 2초 간격).
export async function fetchPull(github, number) {
  let pr = await github.pull(number);
  for (let attempt = 0; attempt < 5 && pr.mergeable === null; attempt += 1) {
    await sleep(2000);
    pr = await github.pull(number);
  }
  return pr;
}

// ci.yml의 pull_request 실행 중 현재 head의 최신 실행 결과를 읽는다. waitSeconds 동안 끝나기를 기다린다.
export async function readCi(github, pr, { waitSeconds = 0, pollSeconds = 20 } = {}) {
  if (pr.mergeable_state === "dirty") return { state: "conflict_no_ci", jobs: {}, run_url: null };
  const deadline = Date.now() + waitSeconds * 1000;
  for (;;) {
    const runs = await github.ciRuns(pr.head.sha);
    const result = { state: "none", jobs: {}, run_url: null };
    if (runs.length) {
      const jobs = await github.runJobs(runs[0].id);
      for (const name of CI_JOBS) {
        const job = jobs.find((item) => item.name === name);
        result.jobs[name] = job ? (job.status === "completed" ? job.conclusion : "in_progress") : "missing";
      }
      result.run_url = runs[0].html_url;
      const values = Object.values(result.jobs);
      if (values.some((value) => value === "in_progress")) result.state = "running";
      else if (values.every((value) => value === "success")) result.state = "passed";
      else if (values.some((value) => value === "failure")) result.state = "failed";
      else result.state = "undetermined";
    }
    const pending = result.state === "running" || (result.state === "none" && waitSeconds > 0);
    if (!pending || Date.now() >= deadline) return result;
    await sleep(pollSeconds * 1000);
  }
}

function git(repoDir, args) {
  return spawnSync("git", ["-C", repoDir, ...args], { encoding: "utf8", maxBuffer: 64 * 1024 * 1024 });
}

// 이미 얕은 저장소(Actions checkout)일 때만 --depth=1로 받는다. 전체 이력 저장소를 얕게 바꾸지 않기 위해서다.
export function fetchArgs(isShallow, refs) {
  return ["fetch", "-q", "--no-tags", ...(isShallow ? ["--depth=1"] : []), "origin", ...refs];
}

// 필요한 커밋 객체만 받아 merge-tree로 충돌 파일을 계산한다. 종료 코드 0=충돌 없음, 1=충돌, 그 외=확인 못 함.
export function computeConflict(repoDir, { prNumber, headSha, baseSha, mergeBaseSha }) {
  const isShallow = git(repoDir, ["rev-parse", "--is-shallow-repository"]).stdout.trim() === "true";
  git(repoDir, fetchArgs(isShallow, [baseSha, mergeBaseSha]));
  git(repoDir, fetchArgs(isShallow, [`refs/pull/${prNumber}/head`]));
  if (git(repoDir, ["rev-parse", "FETCH_HEAD"]).stdout.trim() !== headSha) return { state: "unknown", files: [] };
  const result = git(repoDir, ["merge-tree", "--write-tree", "--name-only", `--merge-base=${mergeBaseSha}`, baseSha, headSha]);
  if (result.status === 0) return { state: "clean", files: [] };
  if (result.status !== 1) return { state: "unknown", files: [] };
  const files = [];
  for (const line of result.stdout.split("\n").slice(1)) {
    if (!line.trim()) break;
    files.push(line.trim());
  }
  return { state: "conflict", files };
}
