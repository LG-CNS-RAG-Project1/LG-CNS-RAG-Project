// OpenAI API 키로 지정 모델(REVIEW_MODEL, 기본 gpt-6-luna)에 아주 짧은 구조화 출력 요청을 한 번 보내 접근 가능 여부를 확인한다.
// PR 내용·Notion은 쓰지 않는다(운영 기록과 분리). 출력은 상태·실제 응답 모델·사용량·오류 분류뿐이다. 실패해도 다른 모델로 바꾸지 않는다.
import { createOpenAIReviewer } from "./openai_engine.mjs";

const model = process.env.REVIEW_MODEL || "gpt-6-luna";
if (!process.env.OPENAI_API_KEY) {
  console.log("OPENAI_API_KEY가 없습니다. 키를 화면에 보이지 않게 셸 환경변수로 넣은 뒤 다시 실행하세요.");
  process.exit(1);
}
const schema = { type: "object", additionalProperties: false, required: ["ok", "note"], properties: { ok: { type: "boolean" }, note: { type: "string" } } };
const reviewer = createOpenAIReviewer({ apiKey: process.env.OPENAI_API_KEY, maxRetries: 1 });
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
  requested_model: model,
  status: result.status,
  response_model: result.response_model,
  error_class: result.error_class,
  error_code: result.error_code,
  http_status: result.http_status,
  incomplete_reason: result.incomplete_reason,
  usage: result.usage,
  duration_ms: result.duration_ms,
  retries: result.retries,
}, null, 2));
process.exit(result.status === "done" ? 0 : 1);
