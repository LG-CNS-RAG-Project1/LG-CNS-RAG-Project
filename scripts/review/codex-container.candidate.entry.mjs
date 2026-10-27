// 합성 인증과 네트워크 차단만 허용하는 후보 검증 진입점이다.
import { spawn, spawnSync } from "node:child_process";
import { createServer } from "node:http";
import { closeSync, fsyncSync, openSync, writeSync } from "node:fs";
import { inspectFeatures, POLICY_ARGS } from "./codex_policy.mjs";

if (process.env.CODEX_SYNTHETIC_ONLY !== "1") throw new Error("Synthetic-only gate is required");
const forbidden = Object.keys(process.env).filter((key) => /^(?:GITHUB_|GH_TOKEN$|NOTION_|OPENAI_|CODEX_AUTH_|CODEX_API_KEY$)/.test(key));
if (forbidden.length) throw new Error("External credentials are forbidden");
const env = { PATH: process.env.PATH, HOME: "/work/home", CODEX_HOME: "/work/runner-home", LANG: "C.UTF-8" };
const options = { env, cwd: "/work", encoding: "utf8", timeout: 20_000 };
const flags = [...POLICY_ARGS, "-c", "agents.enabled=false", "-c", "tools.experimental_request_user_input.enabled=false", "-c", "tools.update_plan.enabled=false", "-c", "features.goals=false", "-c", "features.sleep_tool=false", "-c", "features.token_budget=false", "-c", 'model_catalog_json="/opt/pr-review/model.json"'];
const features = spawnSync("codex", ["features", "list", ...flags], options);
if (features.status !== 0) throw new Error("Feature check unavailable");
inspectFeatures(features.stdout);
const mcp = spawnSync("codex", ["mcp", "list", "--json", ...flags], options);
let servers;
try { servers = JSON.parse(mcp.stdout); } catch { throw new Error("MCP list invalid"); }
if (mcp.status !== 0 || !Array.isArray(servers) || servers.length !== 0) throw new Error("MCP servers detected or unavailable");
const models = spawnSync("codex", ["debug", "models", ...flags], options);
let model;
try { model = JSON.parse(models.stdout).models?.find((item) => item.slug === "gpt-6-sol"); } catch { throw new Error("Model catalog invalid"); }
if (models.status !== 0 || !model || model.shell_type !== "disabled" || model.apply_patch_tool_type !== null || model.tool_mode !== "direct" || model.multi_agent_version !== "disabled" || model.supports_search_tool !== false || model.experimental_supported_tools?.length !== 0) throw new Error("Model catalog check failed");
// Responses Lite는 tools를 input.additional_tools에 넣으므로 최상위 필드만 확인해서는 안 된다.
let calls = 0, invalid = false, child;
const hasTools = (value) => {
  if (!value || typeof value !== "object") return false;
  if (Object.hasOwn(value, "tools") && (!Array.isArray(value.tools) || value.tools.length !== 0)) return true;
  return Object.values(value).some(hasTools);
};
const server = createServer((req, res) => {
  const chunks = [];
  req.on("data", (chunk) => chunks.push(chunk));
  req.on("end", () => {
    try {
      const payload = JSON.parse(Buffer.concat(chunks));
      const embedded = Array.isArray(payload.input) ? payload.input.filter((item) => item.type === "additional_tools") : [];
      calls += 1;
      if (req.url !== "/v1/responses" || payload.model !== "gpt-6-sol" || embedded.length !== 1 || !Array.isArray(embedded[0].tools) || hasTools(payload)) invalid = true;
    } catch { invalid = true; }
    res.writeHead(400, { "content-type": "application/json" });
    res.end('{"error":{"message":"synthetic test"}}');
    setTimeout(() => child?.kill("SIGTERM"), 100);
  });
});
await new Promise((resolve) => server.listen(0, "127.0.0.1", resolve));
const fakeFlags = ["-c", 'model_provider="synthetic"', "-c", 'model_providers.synthetic.name="synthetic"', "-c", `model_providers.synthetic.base_url="http://127.0.0.1:${server.address().port}/v1"`, "-c", 'model_providers.synthetic.env_key="SYNTHETIC_KEY"', "-c", 'model_providers.synthetic.wire_api="responses"'];
child = spawn("codex", ["exec", "--ignore-user-config", "--ignore-rules", "--ephemeral", "--skip-git-repo-check", "-s", "read-only", "-m", "gpt-6-sol", ...flags, ...fakeFlags, "synthetic test"], { cwd: "/work", env: { ...env, SYNTHETIC_KEY: "synthetic-only" }, stdio: "ignore" });
const timer = setTimeout(() => child.kill("SIGKILL"), 20_000);
await new Promise((resolve, reject) => { child.on("close", resolve); child.on("error", reject); });
clearTimeout(timer);
await new Promise((resolve) => server.close(resolve));
if (calls !== 1 || invalid) throw new Error("Synthetic request contains tools or was unavailable");
const file = openSync("/work/runner-home/auth.json", "w");
try { writeSync(file, '{"synthetic_updated":true}'); fsyncSync(file); } finally { closeSync(file); }
console.log("Synthetic candidate checks passed");
