// 지정한 분석기(REVIEW_PROVIDER, 기본 codex)로 REVIEW_MODEL(기본 gpt-6-luna)에 아주 짧은 구조화 출력 요청을 한 번 보내 접근 가능 여부를 확인한다.
// PR 내용·Notion은 쓰지 않는다(운영 기록과 분리). 출력은 상태·모델·사용량·오류 분류뿐이다. 실패해도 다른 모델이나 분석기로 바꾸지 않는다.
// codex는 CODEX_HOME(기본 ~/.codex)의 ChatGPT 로그인을, openai는 OPENAI_API_KEY를 쓴다.
import { homedir } from "node:os";
import { join } from "node:path";

import { createCodexReviewer } from "./codex_engine.mjs";
import { createOpenAIReviewer } from "./openai_engine.mjs";

const provider = process.env.REVIEW_PROVIDER || "codex";
const model = process.env.REVIEW_MODEL || "gpt-6-luna";
if (!["codex", "openai"].includes(provider) || model !== "gpt-6-luna") {
  console.error("지원하지 않는 분석기 또는 모델 설정입니다.");
  process.exit(1);
}
let reviewer;
try {
  reviewer = provider === "openai"
    ? createOpenAIReviewer({ apiKey: process.env.OPENAI_API_KEY, maxRetries: 1 })
    : createCodexReviewer({ codexHome: process.env.CODEX_HOME || join(homedir(), ".codex") });
} catch (error) {
  console.log(`인증 정보를 찾지 못했습니다: ${error.message}`);
  process.exit(1);
}
const schema = { type: "object", additionalProperties: false, required: ["ok", "note"], properties: { ok: { type: "boolean" }, note: { type: "string" } } };
const result = await reviewer.review({
  model,
  instructions: "연결 확인용 요청이다. ok는 true, note는 '확인'으로 답한다.",
  input: "연결 확인",
  schema,
  schemaName: "model_check",
  effort: "low",
  maxOutputTokens: 2_000,
});
console.log(JSON.stringify({
  provider,
  requested_model: model,
  status: result.status,
  response_model: result.response_model,
  error_class: result.error_class,
  http_status: result.http_status,
  usage: result.usage,
  duration_ms: result.duration_ms,
  problems: result.problems,
}, null, 2));
process.exit(result.status === "done" ? 0 : 1);
