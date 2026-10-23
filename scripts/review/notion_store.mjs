// PR 분석 결과를 Notion에 기록하고, 이전 분석 상태·영역 요약 카드·같은 키워드의 지난 PR 기록을 읽는다.
// - PR 분석 표: 표 ID(prDatabaseId)가 있으면 그 표에 쓴다. 없으면 현황판 페이지에 처음 한 번 골격과 'PR 분석' 표를 만든다.
//   분석마다(코드 변경이 없어 지난 AI 결과를 쓴 경우 포함) 새 행을 만들고, 같은 PR의 이전 행은 지우지 않고 '기록: 이전 분석'으로 표시한다.
//   표에 없는 열은 처음 쓸 때 추가한다.
// - 영역 요약 카드 표(cardDatabaseId): 계층 태그마다 한 행이며, 병합된 PR의 분석 결과로 갱신한다.
// - 메모리 페이지: '분석 상태' 표에 PR별 상태 JSON을 저장한다(1900자 단위로 나누고 같은 행을 덮어씀).
import { bulleted, callout, chunkBlocks, heading, paragraph, splitText, text, toRichText } from "../notion/blocks.mjs";
import { LABELS } from "./labels.mjs";

const VERSION = "2026-03-11";
const PR_DB_TITLE = "PR 분석";
const STATE_DB_TITLE = "분석 상태";
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const rich = (value) => ({ rich_text: splitText(String(value ?? "")).slice(0, 100).map((content) => ({ type: "text", text: { content } })) });
const select = (name) => ({ select: name ? { name: String(name).replaceAll(",", " ") } : null });
const options = (names, colors = []) => ({ options: names.map((name, index) => ({ name, color: colors[index] ?? "default" })) });
const plain = (property) => (property?.title ?? property?.rich_text ?? []).map((part) => part.plain_text ?? part.text?.content ?? "").join("");

export const PR_DB_PROPERTIES = {
  "이름": { title: {} },
  "PR 번호": { number: { format: "number" } },
  "PR 링크": { url: {} },
  "담당": { rich_text: {} },
  "브랜치": { rich_text: {} },
  "상태": { select: options(Object.values(LABELS.prState), ["green", "gray", "purple", "default"]) },
  "기록": { select: options(Object.values(LABELS.record), ["green", "gray"]) },
  "준비 상태": { select: options(Object.values(LABELS.readiness), ["gray", "orange", "blue", "yellow", "green"]) },
  "준비 상태 사유": { rich_text: {} },
  "목표 연결": { select: options(Object.values(LABELS.goal)) },
  "태그": { multi_select: options([]) },
  "키워드": { rich_text: {} },
  "분석 내용": { rich_text: {} },
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

// 이전 형식의 표에서 이름이 바뀐 열(이전 이름 → 새 이름)
const PR_DB_RENAMES = { "담당 영역": "태그" };

export const CARD_DB_PROPERTIES = {
  "요약": { rich_text: {} },
  "인터페이스·계약": { rich_text: {} },
  "알려진 위험": { rich_text: {} },
  "키워드": { rich_text: {} },
  "반영한 PR": { rich_text: {} },
  "기준 SHA": { rich_text: {} },
  "갱신 시각": { date: {} },
};

// 렌더러의 속성 값을 Notion 속성 형식으로 바꾼다. '기록' 값이 없으면 그 열은 건드리지 않는다.
export function toNotionProperties(title, values, titleKey = "이름") {
  const properties = {
    [titleKey]: { title: text(title) },
    "PR 번호": { number: values["PR 번호"] },
    "PR 링크": { url: values["PR 링크"] },
    "담당": rich(values["담당"]),
    "브랜치": rich(values["브랜치"]),
    "상태": select(values["상태"]),
    "준비 상태": select(values["준비 상태"]),
    "준비 상태 사유": rich(values["준비 상태 사유"]),
    "목표 연결": select(values["목표 연결"]),
    "태그": { multi_select: (values["태그"] ?? []).map((name) => ({ name: String(name).replaceAll(",", " ") })) },
    "키워드": rich(values["키워드"]),
    "분석 내용": rich(values["분석 내용"]),
    "꼭 고칠 점": { number: values["꼭 고칠 점"] },
    "남은 확인": { number: values["남은 확인"] },
    "자동 검사": select(values["자동 검사"]),
    "분석 방식": select(values["분석 방식"]),
    "분석 상태": select(values["분석 상태"]),
    "분석한 버전": rich(values["분석한 버전"]),
    "마지막 분석": { date: { start: values["마지막 분석"] } },
    "한 줄 요약": rich(values["한 줄 요약"]),
  };
  if (values["기록"]) properties["기록"] = select(values["기록"]);
  return properties;
}

export function createNotion({ token, dashboardPageId, prDatabaseId, cardDatabaseId, memoryPageId, dryRun = false, log = console.log, delayMs = 350 }) {
  let requests = 0;
  const titleKeys = new Map();
  let cardStore = null;

  async function call(method, path, body, attempt = 1) {
    requests += 1;
    if (dryRun) {
      log(`  [DRY] ${method} ${path.split("?")[0]} ${body ? `(${Buffer.byteLength(JSON.stringify(body))}바이트)` : ""}`);
      return { id: "dry", url: "dry", results: [], data_sources: [{ id: "dry" }] };
    }
    await sleep(delayMs);
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

  const dataSourceOf = (database) => database.data_sources?.[0]?.id;

  // 표에 없는 열을 추가하고 이전 이름의 열은 새 이름으로 바꾼다. 표의 제목 열 이름을 돌려준다.
  // 다른 실행이 먼저 같은 변경을 해 400이 나면 표 구조를 다시 읽고 한 번 더 맞춘다.
  async function ensureSchema(database, wanted, renames = {}, attempt = 1) {
    if (titleKeys.has(database.id)) return titleKeys.get(database.id);
    const current = (await call("GET", `data_sources/${dataSourceOf(database)}`)).properties ?? {};
    const titleKey = Object.entries(current).find(([, config]) => config?.type === "title")?.[0] ?? "이름";
    const patch = {};
    for (const [from, to] of Object.entries(renames)) if (current[from] && !current[to]) patch[from] = { name: to };
    const renamed = new Set(Object.values(patch).map((item) => item.name));
    for (const [name, config] of Object.entries(wanted)) {
      if (config.title || current[name] || renamed.has(name)) continue;
      patch[name] = { type: Object.keys(config)[0], ...config };
    }
    if (Object.keys(patch).length) {
      try {
        await call("PATCH", `data_sources/${dataSourceOf(database)}`, { properties: patch });
      } catch (error) {
        if (error.status !== 400 || attempt > 1) throw error;
        return ensureSchema(database, wanted, renames, attempt + 1);
      }
    }
    titleKeys.set(database.id, titleKey);
    return titleKey;
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
    try {
      return await call("POST", "pages", { parent: { type: "data_source_id", data_source_id: dataSourceOf(database) }, properties, children });
    } catch (error) {
      if (error.status !== 400) throw error;
      return call("POST", "pages", { parent: { type: "database_id", database_id: database.id }, properties, children });
    }
  }

  async function findRows(database, prNumber) {
    const found = await call("POST", `data_sources/${dataSourceOf(database)}/query`, { filter: { property: "PR 번호", number: { equals: prNumber } } });
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

  // 표 ID가 있으면 그 표를 읽고, 없으면 현황판 안의 'PR 분석' 표를 찾는다(create면 없을 때 만든다).
  async function getPrDatabase({ create }) {
    if (prDatabaseId) return call("GET", `databases/${prDatabaseId}`);
    return create ? ensurePrDatabase() : findChildDatabase(dashboardPageId, PR_DB_TITLE);
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

  // PR별 상태 JSON을 같은 행에 덮어쓴다(행이 없으면 만들고, 중복 행은 휴지통으로 보낸다).
  async function saveState(prNumber, state) {
    const database = await ensureStateDatabase();
    const [current, ...duplicates] = await findRows(database, prNumber);
    let stateJson = JSON.stringify(state);
    if (stateJson.length > 1900 * 90) stateJson = JSON.stringify({ ...state, output: null });
    const properties = {
      "이름": { title: text(`PR #${prNumber} 상태`) },
      "PR 번호": { number: prNumber },
      "상태 JSON": { rich_text: splitText(stateJson, 1900).slice(0, 100).map((content) => ({ type: "text", text: { content } })) },
      "seq": { number: state.seq },
    };
    if (current) await call("PATCH", `pages/${current.id}`, { properties });
    else await createRow(database, properties, undefined);
    for (const extra of duplicates) await call("PATCH", `pages/${extra.id}`, { in_trash: true });
  }

  // 영역 요약 카드 표와 제목 열 이름, 태그별 카드를 한 번만 읽는다.
  async function loadCards() {
    if (cardStore || !cardDatabaseId) return cardStore;
    const database = await call("GET", `databases/${cardDatabaseId}`);
    const titleKey = await ensureSchema(database, CARD_DB_PROPERTIES);
    const rows = [];
    let cursor = null;
    do {
      const page = await call("POST", `data_sources/${dataSourceOf(database)}/query`, { page_size: 100, ...(cursor ? { start_cursor: cursor } : {}) });
      rows.push(...(page.results ?? []));
      cursor = page.has_more ? page.next_cursor : null;
    } while (cursor);
    const cards = {};
    for (const row of rows) {
      const props = row.properties ?? {};
      const tag = plain(props[titleKey]).trim();
      if (!tag || cards[tag]) continue;
      cards[tag] = {
        id: row.id, tag, summary: plain(props["요약"]), interfaces: plain(props["인터페이스·계약"]), risks: plain(props["알려진 위험"]),
        keywords: plain(props["키워드"]), prs: plain(props["반영한 PR"]), base_sha: plain(props["기준 SHA"]),
      };
    }
    cardStore = { database, titleKey, cards };
    return cardStore;
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

    // 분석 결과를 새 행으로 쓰고, 같은 PR의 이전 행은 '이전 분석'으로 표시한 뒤 상태 JSON을 저장한다.
    async publish(prNumber, report) {
      const prDatabase = await getPrDatabase({ create: true });
      const titleKey = await ensureSchema(prDatabase, PR_DB_PROPERTIES, PR_DB_RENAMES);
      const previousRows = await findRows(prDatabase, prNumber);
      const [first, ...rest] = chunkBlocks(report.blocks);
      const row = await createRow(prDatabase, toNotionProperties(report.title, { ...report.properties, "기록": LABELS.record.latest }, titleKey), first);
      for (const batch of rest) await call("PATCH", `blocks/${row.id}/children`, { children: batch });
      for (const old of previousRows) {
        if (old.properties?.["기록"]?.select?.name === LABELS.record.previous) continue;
        await call("PATCH", `pages/${old.id}`, { properties: { "기록": select(LABELS.record.previous) } });
      }
      await saveState(prNumber, report.state);
      return { url: row.url ?? row.id, requests, kept: previousRows.length };
    },

    // 닫히거나 병합된 PR의 모든 행 상태를 바꾼다(AI 호출 없음).
    async markClosed(prNumber, merged) {
      const database = await getPrDatabase({ create: false });
      if (!database) return 0;
      const rows = await findRows(database, prNumber);
      for (const row of rows) {
        await call("PATCH", `pages/${row.id}`, { properties: { "상태": select(merged ? LABELS.prState.merged : LABELS.prState.closed) } });
      }
      return rows.length;
    },

    // 태그별 영역 요약 카드. 카드 표가 설정되지 않았으면 빈 객체.
    async readCards() {
      return (await loadCards())?.cards ?? {};
    },

    // 태그 카드 한 행을 갱신하거나 새로 만든다.
    async upsertCard(tag, fields) {
      const store = await loadCards();
      if (!store) return null;
      const properties = {
        [store.titleKey]: { title: text(tag) },
        "요약": rich(fields.summary), "인터페이스·계약": rich(fields.interfaces), "알려진 위험": rich(fields.risks),
        "키워드": rich(fields.keywords), "반영한 PR": rich(fields.prs), "기준 SHA": rich(fields.base_sha),
        "갱신 시각": { date: { start: fields.updated_at } },
      };
      const existing = store.cards[tag];
      const row = existing ? await call("PATCH", `pages/${existing.id}`, { properties }) : await createRow(store.database, properties, undefined);
      store.cards[tag] = { ...fields, id: existing?.id ?? row.id, tag };
      return row;
    },

    // 같은 키워드를 가진 다른 PR의 최신 기록을 겹치는 키워드가 많은 순(같으면 최근 분석 순)으로 찾는다.
    async findRelated({ prNumber, keywords, limit = 3 }) {
      if (!keywords.length) return [];
      const database = await getPrDatabase({ create: false });
      if (!database) return [];
      await ensureSchema(database, PR_DB_PROPERTIES, PR_DB_RENAMES);
      const found = await call("POST", `data_sources/${dataSourceOf(database)}/query`, {
        filter: {
          and: [
            { property: "PR 번호", number: { does_not_equal: prNumber } },
            { property: "기록", select: { does_not_equal: LABELS.record.previous } },
            { or: keywords.map((keyword) => ({ property: "키워드", rich_text: { contains: keyword } })) },
          ],
        },
        sorts: [{ property: "마지막 분석", direction: "descending" }],
        page_size: 20,
      });
      const wanted = new Set(keywords);
      return (found.results ?? [])
        .map((row) => {
          const props = row.properties ?? {};
          const rowKeywords = plain(props["키워드"]);
          return {
            number: props["PR 번호"]?.number,
            state: props["상태"]?.select?.name ?? "",
            tags: (props["태그"]?.multi_select ?? []).map((item) => item.name),
            keywords: rowKeywords,
            summary: plain(props["한 줄 요약"]),
            content: plain(props["분석 내용"]),
            overlap: rowKeywords.split(",").map((word) => word.trim()).filter((word) => wanted.has(word)).length,
          };
        })
        .filter((row) => row.overlap > 0)
        .sort((a, b) => b.overlap - a.overlap)
        .slice(0, limit);
    },
  };
}
