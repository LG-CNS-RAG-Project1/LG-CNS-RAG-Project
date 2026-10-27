// GitHub Actions에서 로그인 토큰을 마스킹하고, 저장할 JSON의 갱신 토큰을 검증한다.
import { readFileSync } from "node:fs";

try {
  const auth = JSON.parse(readFileSync(process.argv[2], "utf8"));
  if (!auth.tokens || typeof auth.tokens !== "object" || Array.isArray(auth.tokens)) throw new Error();
  for (const value of Object.values(auth.tokens)) {
    if (typeof value !== "string" || !value) continue;
    console.log(`::add-mask::${value.replace(/%/g, "%25").replace(/\r/g, "%0D").replace(/\n/g, "%0A")}`);
  }
  if (process.argv[3] === "validate" && (typeof auth.tokens.refresh_token !== "string" || !auth.tokens.refresh_token.trim())) throw new Error();
} catch {
  console.error("Codex 로그인 JSON 또는 갱신 토큰이 올바르지 않습니다.");
  process.exitCode = 1;
}
