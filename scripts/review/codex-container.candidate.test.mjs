import assert from "node:assert/strict";
import { EventEmitter } from "node:events";
import { existsSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { test } from "node:test";
import { candidateCreateArgs, prepareCandidateBuildContext, runSyntheticLifecycle, stopAndVerify } from "./codex-container.candidate.mjs";

const IMAGE = `sha256:${"b".repeat(64)}`;
const NAME = `codex-synthetic-${"a".repeat(24)}`;

function fakeDocker({ hanging = false, stopFails = false, createFailsAfterCreating = false } = {}) {
  let exists = false, running = false, auth;
  const commands = [];
  const sync = (bin, args, options) => {
    assert.equal(bin, "docker");
    assert.ok(!Object.keys(options.env).some((key) => /TOKEN|SECRET|API_KEY/.test(key)));
    commands.push(args[0]);
    if (args[0] === "create") {
      exists = true;
      const mount = args.find((item) => item.includes("dst=/work/runner-home/auth.json"));
      auth = mount.match(/^type=bind,src=(.*),dst=/)[1];
      assert.equal(readFileSync(auth, "utf8"), "{}");
      return createFailsAfterCreating ? { status: 1, stdout: "" } : { status: 0, stdout: `${"c".repeat(64)}\n` };
    }
    if (args[0] === "ps") return { status: 0, stdout: exists ? `${args[3].slice("name=^/".length, -1)}\n` : "" };
    if (args[0] === "inspect") return { status: 0, stdout: `${running}\n` };
    if (args[0] === "stop") { if (stopFails) return { status: 1, stdout: "" }; running = false; return { status: 0, stdout: "" }; }
    if (args[0] === "rm") { exists = false; return { status: 0, stdout: "" }; }
    throw new Error("Unexpected Docker command");
  };
  const asyncSpawn = (bin, args) => {
    assert.equal(bin, "docker"); assert.equal(args[0], "start");
    commands.push("start"); running = true;
    const child = new EventEmitter();
    child.kill = () => { commands.push("kill-client"); };
    if (!hanging) setImmediate(() => { writeFileSync(auth, '{"synthetic_updated":true}'); running = false; child.emit("close", 0); });
    return child;
  };
  return { sync, asyncSpawn, commands, get exists() { return exists; } };
}

test("후보 컨테이너는 불변 이미지와 단일 auth 바인드, 네트워크 차단을 강제한다", () => {
  const args = candidateCreateArgs({ image: IMAGE, name: NAME, workDir: "/tmp/w", authFile: "/tmp/a", uid: 501, gid: 20 });
  for (const value of ["create", "--name", "--network", "none", "--read-only", "--cap-drop", "ALL", "--restart", "no", "CODEX_SYNTHETIC_ONLY=1"]) assert.ok(args.includes(value));
  assert.equal(args.filter((value) => value.includes("dst=/work/runner-home/auth.json")).length, 1);
  assert.ok(!args.some((value) => /docker\.sock|GITHUB_TOKEN|NOTION_REVIEW_TOKEN|CODEX_AUTH_WRITE_TOKEN/.test(value)));
  assert.throws(() => candidateCreateArgs({ image: "latest", name: NAME, workDir: "/tmp/w", authFile: "/tmp/a", uid: 1, gid: 1 }));
  assert.throws(() => candidateCreateArgs({ image: IMAGE, name: NAME, workDir: "/tmp/w,evil", authFile: "/tmp/a", uid: 1, gid: 1 }));
});

test("성공한 합성 실행은 종료 상태와 제거를 확인한 뒤 정리한다", async () => {
  const f = fakeDocker();
  const result = await runSyntheticLifecycle({ image: IMAGE, spawnImpl: f.asyncSpawn, spawnSyncImpl: f.sync });
  assert.equal(result.status, 0); assert.equal(result.cleanupVerified, true); assert.equal(f.exists, false);
  assert.deepEqual(f.commands, ["create", "start", "ps", "inspect", "rm", "ps"]);
});

test("시간 초과는 Docker 클라이언트뿐 아니라 컨테이너를 중지·확인·제거한다", async () => {
  const f = fakeDocker({ hanging: true });
  const result = await runSyntheticLifecycle({ image: IMAGE, timeoutMs: 10, spawnImpl: f.asyncSpawn, spawnSyncImpl: f.sync });
  assert.equal(result.timedOut, true); assert.equal(result.cleanupVerified, true); assert.equal(f.exists, false);
  assert.deepEqual(f.commands, ["create", "start", "kill-client", "ps", "inspect", "stop", "inspect", "rm", "ps"]);
});

test("중지 실패는 정리 완료로 표시하지 않고 합성 파일을 보존한다", async () => {
  const f = fakeDocker({ hanging: true, stopFails: true });
  const result = await runSyntheticLifecycle({ image: IMAGE, timeoutMs: 10, spawnImpl: f.asyncSpawn, spawnSyncImpl: f.sync });
  assert.equal(result.cleanupVerified, false); assert.equal(f.exists, true);
  assert.equal(existsSync(result.syntheticRetainedDirectory), true);
  rmSync(result.syntheticRetainedDirectory, { recursive: true, force: true });
});

test("create 응답 유실 시에도 미리 정한 이름으로 컨테이너를 찾아 제거한다", async () => {
  const f = fakeDocker({ createFailsAfterCreating: true });
  const result = await runSyntheticLifecycle({ image: IMAGE, spawnImpl: f.asyncSpawn, spawnSyncImpl: f.sync });
  assert.equal(result.createError, true); assert.equal(result.cleanupVerified, true); assert.equal(f.exists, false);
});

test("이미 취소된 실행은 컨테이너를 만들지 않는다", async () => {
  const controller = new AbortController(); controller.abort();
  const f = fakeDocker();
  const result = await runSyntheticLifecycle({ image: IMAGE, signal: controller.signal, spawnImpl: f.asyncSpawn, spawnSyncImpl: f.sync });
  assert.equal(result.aborted, true); assert.equal(result.cleanupVerified, true);
  assert.deepEqual(f.commands, ["ps"]);
});

test("불명확한 Docker 상태는 안전하지 않은 것으로 처리한다", () => {
  assert.equal(stopAndVerify({ name: NAME, spawnSyncImpl: () => ({ status: 1, stdout: "" }) }), false);
});

test("후보 빌드 문맥은 지정한 코드만 포함한다", () => {
  const root = mkdtempSync(join(tmpdir(), "candidate-context-"));
  try {
    prepareCandidateBuildContext(root);
    assert.match(readFileSync(join(root, "scripts/review/codex-container.candidate.Dockerfile"), "utf8"), /@openai\/codex@0\.160\.1/);
    assert.match(readFileSync(join(root, "scripts/review/codex-container.candidate.entry.mjs"), "utf8"), /mcp.*list.*--json/);
  } finally { rmSync(root, { recursive: true, force: true }); }
});
