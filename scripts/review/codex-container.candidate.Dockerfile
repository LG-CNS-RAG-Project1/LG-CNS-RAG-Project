# 오직 네트워크 없는 합성 검증용. 운영 실행에 연결하지 않는다.
FROM node:24-bookworm-slim@sha256:55fb5f5a527ea2c5c4a95f963e48ef90aa38c7b346054fdc8ee9957a2b55d205
RUN npm install -g @openai/codex@0.160.1 \
    && test "$(codex --version)" = "codex-cli 0.160.1" \
    && mkdir -p /etc/codex /opt/pr-review \
    && printf '[features]\nunified_exec = false\n' > /etc/codex/requirements.toml
COPY scripts/review/codex_policy.mjs /opt/pr-review/codex_policy.mjs
COPY scripts/review/codex-container.candidate.entry.mjs /opt/pr-review/entry.mjs
RUN mkdir -p /tmp/catalog-home \
    && HOME=/tmp/catalog-home CODEX_HOME=/tmp/catalog-home codex debug models --bundled > /tmp/models.json \
    && node --input-type=module -e 'import {readFileSync,writeFileSync} from "node:fs"; const m=JSON.parse(readFileSync("/tmp/models.json")).models.find(x=>x.slug==="gpt-6-sol"); if(!m) throw Error("model missing"); Object.assign(m,{tool_mode:"direct",shell_type:"disabled",apply_patch_tool_type:null,experimental_supported_tools:[],supports_search_tool:false,multi_agent_version:"disabled"}); writeFileSync("/opt/pr-review/model.json",JSON.stringify({models:[m]}));' \
    && rm -rf /tmp/catalog-home /tmp/models.json
ENTRYPOINT ["node", "/opt/pr-review/entry.mjs"]
