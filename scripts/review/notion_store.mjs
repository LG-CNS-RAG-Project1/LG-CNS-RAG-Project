// PR 분석 결과를 Notion에 기록하고 이전 분석 상태를 읽는다.
// - 현황판 페이지: 처음 한 번 골격과 'PR 분석' 표를 만들고, 이후에는 같은 표를 다시 쓴다.
// - PR 행: 같은 PR 번호의 이전 행을 휴지통으로 보낸 뒤 새로 만든다(한 PR = 한 행).
// - 메모리 페이지: '분석 상태' 표에 PR별 상태 JSON을 저장한다(1900자 단위로 나눠 저장).
import { bulleted, callout, chunkBlocks, heading, paragraph, splitText, text, toRichText } from "../notion/blocks.mjs";
import { LABELS } from "./labels.mjs";

const VERSION = "2026-03-11";
const PR_DB_TITLE = "PR 분석";
const STATE_DB_TITLE = "분석 상태";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const rich = (value) => ({ rich_text: splitText(String(value ?? "")).slice(0, 100).map((content) => ({ type: "text", text: { content } })) });
const select = (name) => ({ select: name ? { name: String(name).replaceAll(",", " ") } : null });
const options = (names, colors = []) => ({ options: names.map((name, index) => ({ name, color: colors[index] ?? "default" })) });

export const PR_DB_PROPERTIES = {
  "이름": { title: {} },
  "PR 번호": { number: { format: "number" } },
  "PR 링크": { url: {} },
  "담당": { rich_text: {} },
  "브랜치": { rich_text: {} },
  "상태": { select: options(Object.values(LABELS.prState), ["green", "gray", "purple", "default"]) },
  "준비 상태": { select: options(Object.values(LABELS.readiness), ["gray", "orange", "blue", "yellow", "green"]) },
  "준비 상태 사유": { rich_text: {} },
  "목표 연결": { select: options(Object.values(LABELS.goal)) },
  "담당 영역": { multi_select: options([]) },
  "꼭 고칠 점": { number: { format: "number" } },
  "남은 확인": { number: { format: "number" } },
  "자동 검사": { select: options(Object.values(LABELS.ci)) },
  "분석 방식": { select: options(Object.values(LABELS.mode)) },
  "분석 상태": { select: options(Object.values(LABELS.analysis)) },
  "분석한 버전": { rich_text: {} },
  "마지막 분석": { date: {} },
  "한 줄 요약": { rich_text: {} },
  "리더 봄": { checkbox: {} },
  "논의 완료": { checkbox: {} },
  "보안 처리 완료": { checkbox: {} },
};

// 렌더러의 속성 값을 Notion 속성 형식으로 바꾼다.
export function toNotionProperties(title, values) {
  return {
    "이름": { title: text(title) },
    "PR 번호": { number: values["PR 번호"] },
    "PR 링크": { url: values["PR 링크"] },
    "담당": rich(values["담당"]),
    "브랜치": rich(values["브랜치"]),
    "상태": select(values["상태"]),
    "준비 상태": select(values["준비 상태"]),
    "준비 상태 사유": rich(values["준비 상태 사유"]),
    "목표 연결": select(values["목표 연결"]),
    "담당 영역": { multi_select: (values["담당 영역"] ?? []).map((name) => ({ name })) },
    "꼭 고칠 점": { number: values["꼭 고칠 점"] },
    "남은 확인": { number: values["남은 확인"] },
    "자동 검사": select(values["자동 검사"]),
    "분석 방식": select(values["분석 방식"]),
    "분석 상태": select(values["분석 상태"]),
    "분석한 버전": rich(values["분석한 버전"]),
    "마지막 분석": { date: { start: values["마지막 분석"] } },
    "한 줄 요약": rich(values["한 줄 요약"]),
  };
}

export function createNotion({ token, dashboardPageId, memoryPageId, dryRun = false, log = console.log }) {
  let requests = 0;

  async function call(method, path, body, attempt = 1) {
    requests += 1;
    if (dryRun) {
      log(`  [DRY] ${method} ${path.split("?")[0]} ${body ? `(${Buffer.byteLength(JSON.stringify(body))}바이트)` : ""}`);
      return { id: "dry", url: "dry", results: [], data_sources: [{ id: "dry" }] };
    }
    await sleep(350);
    const response = await fetch(`https://api.notion.com/v1/${path}`, {
      method,
      headers: { Authorization: `Bearer ${token}`, "Notion-Version": VERSION, "Content-Type": "application/json" },
      body: body ? JSON.stringify(body) : undefined,
    });
    const retryable = response.status === 429 || response.status === 529 || (response.status >= 500 && (method === "GET" || method === "DELETE"));
    if (retryable && attempt < 4) {
      await sleep(Math.min(Number(response.headers.get("retry-after")) * 1000 || 1000 * 2 ** attempt, 60_000));
      return call(method, path, body, attempt + 1);
    }
    const data = await response.json().catch(() => ({}));
    if (!response.ok) {
      const error = new Error(`Notion ${response.status} ${data.code ?? ""}: ${String(data.message ?? "").slice(0, 200)}`);
      error.status = response.status;
      error.code = data.code;
      throw error;
    }
    return data;
  }

  async function findChildDatabase(pageId, title) {
    if (dryRun) {
      await call("GET", `blocks/${pageId}/children?page_size=100`);
      return null;
    }
    const children = await call("GET", `blocks/${pageId}/children?page_size=100`);
    const block = (children.results ?? []).find((item) => item.type === "child_database" && item.child_database?.title === title);
    return block ? call("GET", `databases/${block.id}`) : null;
  }

  async function createRow(database, properties, children) {
    const dataSourceId = database.data_sources?.[0]?.id;
    try {
      return await call("POST", "pages", { parent: { type: "data_source_id", data_source_id: dataSourceId }, properties, children });
    } catch (error) {
      if (error.status !== 400) throw error;
      return call("POST", "pages", { parent: { type: "database_id", database_id: database.id }, properties, children });
    }
  }

  async function findRows(database, prNumber) {
    const dataSourceId = database.data_sources?.[0]?.id;
    const found = await call("POST", `data_sources/${dataSourceId}/query`, { filter: { property: "PR 번호", number: { equals: prNumber } } });
    return found.results ?? [];
  }

  async function ensurePrDatabase() {
    const existing = await findChildDatabase(dashboardPageId, PR_DB_TITLE);
    if (existing) return existing;
    for (const batch of chunkBlocks([
      callout(toRichText([
        { text: "현재 작업 상황\n", bold: true },
        { text: "PR이 열리거나 수정본이 올라오면 GitHub Actions가 자동으로 분석해 아래 표에 기록합니다. 행을 열면 PR별 보고서가 나옵니다.\n" },
        { text: "AI 분석은 참고용이며 최종 판단은 리더가 합니다. 작업물의 상태이며 사람에 대한 평가가 아닙니다.", italic: true },
      ]), "📊", "gray_background"),
      heading(2, text("진행 중인 PR")),
      bulleted(text("준비 상태: 🟢 검토 준비됨 · 🟡 리더가 한 번 보기 · 🔵 함께 논의 · 🟠 보완 후 검토 · ⚪ 초안")),
      paragraph(text("")),
    ])) {
      await call("PATCH", `blocks/${dashboardPageId}/children`, { children: batch });
    }
    return call("POST", "databases", {
      parent: { type: "page_id", page_id: dashboardPageId },
      is_inline: true,
      title: text(PR_DB_TITLE),
      initial_data_source: { properties: PR_DB_PROPERTIES },
    });
  }

  async function ensureStateDatabase() {
    const existing = await findChildDatabase(memoryPageId, STATE_DB_TITLE);
    if (existing) return existing;
    return call("POST", "databases", {
      parent: { type: "page_id", page_id: memoryPageId },
      is_inline: true,
      title: text(STATE_DB_TITLE),
      initial_data_source: {
        properties: { "이름": { title: {} }, "PR 번호": { number: { format: "number" } }, "상태 JSON": { rich_text: {} }, "seq": { number: { format: "number" } } },
      },
    });
  }

  return {
    get requests() {
      return requests;
    },

    // 이전 분석 상태를 읽는다. 없거나 해석에 실패하면 null.
    async readState(prNumber) {
      const database = await findChildDatabase(memoryPageId, STATE_DB_TITLE);
      if (!database) return null;
      const [row] = await findRows(database, prNumber);
      const parts = row?.properties?.["상태 JSON"]?.rich_text ?? [];
      try {
        return parts.length ? JSON.parse(parts.map((part) => part.plain_text ?? part.text?.content ?? "").join("")) : null;
      } catch {
        return null;
      }
    },

    // PR 보고서 행을 새로 쓰고 상태 JSON을 저장한다.
    async publish(prNumber, report) {
      const prDatabase = await ensurePrDatabase();
      for (const old of await findRows(prDatabase, prNumber)) await call("PATCH", `pages/${old.id}`, { in_trash: true });
      const [first, ...rest] = chunkBlocks(report.blocks);
      const row = await createRow(prDatabase, toNotionProperties(report.title, report.properties), first);
      for (const batch of rest) await call("PATCH", `blocks/${row.id}/children`, { children: batch });

      const stateDatabase = await ensureStateDatabase();
      for (const old of await findRows(stateDatabase, prNumber)) await call("PATCH", `pages/${old.id}`, { in_trash: true });
      let stateJson = JSON.stringify(report.state);
      if (stateJson.length > 1900 * 90) stateJson = JSON.stringify({ ...report.state, output: null });
      await createRow(stateDatabase, {
        "이름": { title: text(`PR #${prNumber} 상태`) },
        "PR 번호": { number: prNumber },
        "상태 JSON": { rich_text: splitText(stateJson, 1900).slice(0, 100).map((content) => ({ type: "text", text: { content } })) },
        "seq": { number: report.state.seq },
      }, undefined);
      return { url: row.url ?? row.id, requests };
    },

    // 닫히거나 병합된 PR 행의 상태만 바꾼다(AI 호출 없음).
    async markClosed(prNumber, merged) {
      const database = await findChildDatabase(dashboardPageId, PR_DB_TITLE);
      if (!database) return 0;
      const rows = await findRows(database, prNumber);
      for (const row of rows) {
        await call("PATCH", `pages/${row.id}`, { properties: { "상태": select(merged ? LABELS.prState.merged : LABELS.prState.closed) } });
      }
      return rows.length;
    },
  };
}
