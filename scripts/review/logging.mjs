// 신뢰하지 않는 PR 값이 Actions 워크플로 명령으로 실행되지 않도록 로그를 정규화한다.
const line = (message) => String(message ?? "").replace(/[\x00-\x1f\x7f]/g, (char) => char === "\n" ? "\\n" : char === "\r" ? "\\r" : " ");
export const logLine = (message) => `PR_ANALYSIS ${line(message)}`;
export const warningLine = (message, actions) => {
  const text = line(message);
  return actions ? `::warning::${text.replace(/%/g, "%25")}` : `경고: ${text}`;
};
