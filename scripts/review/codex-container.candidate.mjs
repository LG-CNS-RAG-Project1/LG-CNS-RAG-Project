// 격리 컨테이너 생명주기 후보. 합성 인증·네트워크 없음만 지원하며 운영 엔진에서 사용하지 않는다.
import { spawn, spawnSync } from "node:child_process";
import { randomBytes } from "node:crypto";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const IMAGE_ID = /^sha256:[a-f0-9]{64}$/;
const NAME = /^codex-synthetic-[a-f0-9]{24}$/;
const safePath = (path) => typeof path === "string" && path.startsWith("/") && !/[,\r\n]/.test(path);
const dockerEnv = () => Object.fromEntries(["PATH", "HOME", "DOCKER_HOST", "DOCKER_CONFIG", "TMPDIR"].filter((key) => process.env[key] !== undefined).map((key) => [key, process.env[key]]));

export function prepareCandidateBuildContext(root) {
  const target = join(root, "scripts", "review");
  mkdirSync(target, { recursive: true });
  for (const file of ["codex_policy.mjs", "codex-container.candidate.entry.mjs", "codex-container.candidate.Dockerfile"]) copyFileSync(join(HERE, file), join(target, file));
}

export function candidateCreateArgs({ image, name, workDir, authFile, uid, gid }) {
  if (!IMAGE_ID.test(image) || !NAME.test(name) || !safePath(workDir) || !safePath(authFile)) throw new Error("Invalid candidate inputs");
  if (!Number.isInteger(uid) || !Number.isInteger(gid) || uid < 0 || gid < 0) throw new Error("Invalid UID/GID");
  return ["create", "--name", name, "--label", "org.openai.pr-review.synthetic=1", "--restart", "no", "--network", "none", "--read-only", "--cap-drop", "ALL", "--security-opt", "no-new-privileges", "--pids-limit", "128", "--tmpfs", "/tmp:rw,nosuid,nodev,size=64m", "--user", `${uid}:${gid}`, "--env", "CODEX_SYNTHETIC_ONLY=1", "--mount", `type=bind,src=${workDir},dst=/work`, "--mount", `type=bind,src=${authFile},dst=/work/runner-home/auth.json`, "--workdir", "/work", image];
}

// 비정상 종료에서도 컨테이너가 실제로 멈추고 제거됐는지 확인한다.
export function stopAndVerify({ name, docker = "docker", spawnSyncImpl = spawnSync, env = dockerEnv() }) {
  if (!NAME.test(name)) throw new Error("Invalid synthetic container name");
  const run = (args) => spawnSyncImpl(docker, args, { encoding: "utf8", timeout: 15_000, env });
  const list = () => {
    const result = run(["ps", "-a", "--filter", `name=^/${name}$`, "--format", "{{.Names}}"]);
    if (result.status !== 0) return null;
    return String(result.stdout).split("\n").map((line) => line.trim()).filter(Boolean).includes(name);
  };
  const before = list();
  if (before === false) return true;
  if (before !== true) return false;
  let inspect = run(["inspect", "--format", "{{.State.Running}}", name]);
  if (inspect.status !== 0) return false;
  let running = String(inspect.stdout).trim();
  if (running === "true") {
    if (run(["stop", "--time", "2", name]).status !== 0) return false;
    inspect = run(["inspect", "--format", "{{.State.Running}}", name]);
    if (inspect.status !== 0) return false;
    running = String(inspect.stdout).trim();
  }
  if (running !== "false") return false;
  if (run(["rm", name]).status !== 0) return false;
  return list() === false;
}

function startAttached({ docker, name, env, signal, timeoutMs, spawnImpl }) {
  return new Promise((resolve) => {
    let child;
    let timer;
    let done = false;
    const finish = (result) => {
      if (done) return;
      done = true;
      clearTimeout(timer);
      signal?.removeEventListener("abort", onAbort);
      resolve(result);
    };
    const onAbort = () => { child?.kill("SIGKILL"); finish({ status: null, aborted: true }); };
    try {
      child = spawnImpl(docker, ["start", "--attach", name], { env, stdio: "ignore" });
      child.on("error", () => finish({ status: null, spawnError: true }));
      child.on("close", (status) => finish({ status }));
      timer = setTimeout(() => { child.kill("SIGKILL"); finish({ status: null, timedOut: true }); }, timeoutMs);
      signal?.addEventListener("abort", onAbort, { once: true });
      if (signal?.aborted) onAbort();
    } catch { finish({ status: null, spawnError: true }); }
  });
}

export async function runSyntheticLifecycle({ image, docker = "docker", signal, timeoutMs = 60_000, spawnImpl = spawn, spawnSyncImpl = spawnSync } = {}) {
  if (!IMAGE_ID.test(image) || !Number.isSafeInteger(timeoutMs) || timeoutMs < 1 || timeoutMs > 120_000) throw new Error("Invalid candidate settings");
  const root = mkdtempSync(join(tmpdir(), "codex-candidate-synthetic-"));
  const name = `codex-synthetic-${randomBytes(12).toString("hex")}`;
  const env = dockerEnv();
  let created = false;
  let result = { status: null, spawnError: true };
  let stopped = false;
  try {
    const work = join(root, "work");
    mkdirSync(join(work, "home"), { recursive: true });
    mkdirSync(join(work, "runner-home"), { recursive: true });
    writeFileSync(join(work, "runner-home", "auth.json"), "", { mode: 0o600 });
    const authFile = join(root, "synthetic-auth.json");
    writeFileSync(authFile, "{}", { mode: 0o600 });
    if (!signal?.aborted) {
      const args = candidateCreateArgs({ image, name, workDir: work, authFile, uid: process.getuid(), gid: process.getgid() });
      const create = spawnSyncImpl(docker, args, { encoding: "utf8", timeout: 30_000, env });
      created = create.status === 0 && /^[a-f0-9]{12,64}$/.test(String(create.stdout).trim());
      if (created) result = await startAttached({ docker, name, env, signal, timeoutMs, spawnImpl });
      else result = { status: null, createError: true };
    } else result = { status: null, aborted: true };
    // 합성 값만 읽는다. 실제 로그인 정보에 쓸 수 있는 인터페이스는 제공하지 않는다.
    if (result.status === 0 && readFileSync(authFile, "utf8") !== '{"synthetic_updated":true}') result = { status: null, bindError: true };
  } finally {
    stopped = stopAndVerify({ name, docker, spawnSyncImpl, env });
    if (stopped) rmSync(root, { recursive: true, force: true });
  }
  return { ...result, cleanupVerified: stopped, ...(stopped ? {} : { syntheticRetainedDirectory: root }), name };
}

if (process.argv[1] && fileURLToPath(import.meta.url) === process.argv[1]) {
  const controller = new AbortController();
  process.once("SIGTERM", () => controller.abort());
  process.once("SIGINT", () => controller.abort());
  const result = await runSyntheticLifecycle({ image: process.argv[2], signal: controller.signal });
  if (result.status !== 0 || !result.cleanupVerified) { console.error("Synthetic candidate test failed; cleanup may need inspection"); process.exitCode = 1; }
  else console.log("Synthetic candidate lifecycle passed");
}
