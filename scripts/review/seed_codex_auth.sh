#!/usr/bin/env bash
# PR 분석 자동화 전용 ChatGPT 로그인 정보를 만들어 GitHub Environment pr-analysis의 Secret CODEX_AUTH_JSON에 저장한다.
# 리더가 신뢰된 PC에서 직접 실행한다(브라우저 로그인). 평소 Codex 로그인(~/.codex)과 다른 새 로그인 세션을 만들고,
# 값은 화면·저장소에 남기지 않으며 끝나면 임시 폴더를 지운다. 자동 갱신이 실패했을 때 다시 실행해 새로 등록한다.
set -euo pipefail

command -v codex >/dev/null || { echo "codex CLI가 필요합니다(npm install -g @openai/codex@0.160.1)." >&2; exit 1; }
command -v gh >/dev/null || { echo "gh CLI 로그인이 필요합니다." >&2; exit 1; }
REPO="${GITHUB_REPOSITORY:-LG-CNS-RAG-Project1/LG-CNS-RAG-Project}"
TMP="$(mktemp -d)"
trap 'rm -rf "$TMP"' EXIT
chmod 700 "$TMP"

echo "브라우저에서 자동화에 쓸 ChatGPT 계정으로 로그인하세요."
if [ "${REVIEW_CODEX_DEVICE_AUTH:-false}" = "true" ]; then
  CODEX_HOME="$TMP" codex login --device-auth
else
  CODEX_HOME="$TMP" codex login
fi
test -s "$TMP/auth.json" || { echo "로그인 정보가 만들어지지 않았습니다." >&2; exit 1; }
CODEX_HOME="$TMP" codex login status | head -1

gh secret set CODEX_AUTH_JSON --env pr-analysis --repo "$REPO" < "$TMP/auth.json"
echo "Environment pr-analysis의 CODEX_AUTH_JSON에 저장했습니다(값은 출력하지 않음). 임시 폴더는 지웁니다."
