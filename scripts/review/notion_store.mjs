// PR 분석 결과를 Notion에 기록하고, 분석 상태·영역 카드·운영 상태를 읽고 쓴다.
// - PR 분석 표(prDatabaseId, 없으면 현황판 안 'PR 분석' 표): PR마다 페이지 하나를 저장소+PR 번호로 찾아 제자리에서 고친다.
//   제목이 바뀌어도 새 페이지를 만들지 않는다. 이전 방식으로 쌓인 같은 PR의 '이전 분석' 행은 지우지 않고 그대로 둔다.
//   본문은 보고서 → 서비스 아키텍처 그림 → 리더 메모 순서다. 보고서만 새 블록을 맨 앞에 넣은 뒤 이전 보고서 블록을 지우는 방식으로 바꾸고,
//   그림은 페이지에 없을 때만 한 번 넣으며, 리더 메모는 건드리지 않는다.
// - 영역 카드 표(cardDatabaseId): 계층 태그마다 한 행. 리비전·적용 기록과 함께 쓴다.
// - 메모리 페이지: '분석 상태' 표에 PR별 상태 JSON(1900자 단위)과 운영 상태(PR 번호 0 행)를 저장한다.
import { bulleted, callout, chunkBlocks, heading, paragraph, splitText, text, toRichText } from "../notion/blocks.mjs";
import { cardFromFields, cardToFields } from "./cards.mjs";
import { LABELS } from "./labels.mjs";
import { DIAGRAM_HEADING, MEMO_HEADING, memoBlocks } from "./render.mjs";

const VERSION = "2026-03-11";
const PR_DB_TITLE = "PR 분석";
const STATE_DB_TITLE = "분석 상태";
const OPS_ROW = 0;
const PROTECTED_BLOCKS = new Set(["child_page", "child_database"]);
const sleep = (ms) => new Promise((resolve) => setTimeout(resolve, ms));

const rich = (value) => ({ rich_text: splitText(String(value ?? "")).slice(0, 100).map((content) => ({ type: "text", text: { content } })) });
const select = (name) => ({ select: name ? { name: String(name).replaceAll(",", " ") } : null });
const options = (names, colors = []) => ({ options: names.map((name, index) => ({ name, color: colors[index] ?? "default" })) });
export const plain = (property) => (property?.title ?? property?.rich_text ?? []).map((part) => part.plain_text ?? part.text?.content ?? "").join("");
const blockText = (block) => plain({ rich_text: block?.[block?.type]?.rich_text ?? [] });

// 여러 번 보내도 결과가 같은 요청인지(조회·검색, 페이지 속성·블록 내용 수정, 표 구조 수정, 삭제)
export const repeatable = (method, path) =>
  method === "GET" || method === "DELETE" || path.endsWith("/query") ||
  (method === "PATCH" && (/^pages\/[^/]+$/.test(path) || /^data_sources\/[^/]+$/.test(path) || /^blocks\/[^/]+$/.test(path)));

export const PR_DB_PROPERTIES = {
  "이름": { title: {} },
  "PR 번호": { number: { format: "number" } },
  "PR 링크": { url: {} },
  "저장소": { rich_text: {} },
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
  "현재 버전": { rich_text: {} },
  "마지막 시도": { rich_text: {} },
  "AI 모델": { rich_text: {} },
  "카드 반영": { rich_text: {} },
  "마지막 분석": { date: {} },
  "한 줄 요약": { rich_text: {} },
  "리더 봄": { checkbox: {} },
  "논의 완료": { checkbox: {} },
  "보안 처리 완료": { checkbox: {} },
  "병합 판단": { select: options(Object.values(LABELS.verdict), ["green", "orange", "blue", "gray"]) },
  "판단 근거": { rich_text: {} },
};

// 이전 형식의 표에서 이름이 바뀐 열(이전 이름 → 새 이름)
const PR_DB_RENAMES = { "담당 영역": "태그" };

// 카드 표 열. '요약'·'인터페이스·계약'·'알려진 위험'은 이전 형식 열로 읽기만 한다(새 내용은 쓰지 않음).
export const CARD_DB_PROPERTIES = {
  "범위": { rich_text: {} },
  "핵심 계약": { rich_text: {} },
  "근거 파일·심볼": { rich_text: {} },
  "기준 SHA": { rich_text: {} },
  "리비전": { number: { format: "number" } },
  "적용 기록": { rich_text: {} },
  "반영한 PR": { rich_text: {} },
  "키워드": { rich_text: {} },
  "갱신 시각": { date: {} },
};

const STRING_PROPERTIES = ["담당", "브랜치", "준비 상태 사유", "키워드", "분석 내용", "분석한 버전", "현재 버전", "마지막 시도", "AI 모델", "한 줄 요약", "판단 근거", "저장소", "카드 반영"];
const SELECT_PROPERTIES = ["상태", "준비 상태", "목표 연결", "자동 검사", "분석 방식", "분석 상태", "병합 판단", "기록"];

// 렌더러의 속성 값을 Notion 속성 형식으로 바꾼다. values에 없는 열은 건드리지 않는다.
export function toNotionProperties(title, values, titleKey = "이름") {
  const properties = {};
  if (title !== null && title !== undefined) properties[titleKey] = { title: text(title) };
  for (const [name, value] of Object.entries(values)) {
    if (value === undefined) continue;
    if (STRING_PROPERTIES.includes(name)) properties[name] = rich(value);
    else if (SELECT_PROPERTIES.includes(name)) properties[name] = select(value);
    else if (name === "PR 번호" || name === "꼭 고칠 점" || name === "남은 확인") properties[name] = { number: value };
    else if (name === "PR 링크") properties[name] = { url: value };
    else if (name === "마지막 분석") properties[name] = { date: value ? { start: value } : null };
    else if (name === "태그") properties[name] = { multi_select: (value ?? []).map((item) => ({ name: String(item).replaceAll(",", " ") })) };
  }
  return properties;
}

// 상태 JSON을 Notion 칸 한도(1900자 × 100조각, 서로게이트 여유 1조각)와 요청 크기 한도(500KB, 여유 포함 400KB) 안에 맞춘다. 넘으면 기록·출력 원문·지적 세부를 차례로 줄이고,
// 그래도 넘으면 잘린 JSON을 저장하지 않도록 오류를 낸다(병합 때 카드 검증에 필요한 파일 지문·카드 후보는 끝까지 남긴다).
export const STATE_CHARS = 1900 * 99;
export const STATE_BYTES = 400_000;
export function fitState(value) {
  const cap = (list, limit = 50) => (Array.isArray(list) && list.length > limit ? [...list.slice(0, limit), `…외 ${list.length - limit}개`] : list);
  const withSuccess = (state, change) => ({ ...state, last_successful_analysis: state.last_successful_analysis ? change(state.last_successful_analysis) : null });
  const shrinks = [
    (state) => state,
    (state) => ({ ...state, history: (state.history ?? []).slice(-3) }),
    (state) => withSuccess(state, (success) => ({
      ...success,
      scope: { ...success.scope, changed: cap(success.scope?.changed), excluded: cap(success.scope?.excluded), no_patch: cap(success.scope?.no_patch), sources: [] },
      coverage: success.coverage ? { ...success.coverage, excluded: cap(success.coverage.excluded, 200) } : success.coverage,
    })),
    // 파일별 지문을 버리고 요약 해시만 남긴다(다음 수정본은 바뀌었으면 처음부터 전체 분석, 같으면 호출 안 함).
    (state) => withSuccess(state, (success) => ({ ...success, files: success.files_digest ? null : success.files })),
    (state) => withSuccess(state, (success) => ({ ...success, output: null })),
    (state) => ({ ...state, last_successful_analysis: state.last_successful_analysis ? { ...state.last_successful_analysis, findings: (state.last_successful_analysis.findings ?? []).map(({ id, severity, file, title, kind, anchor, side, line, anchor_found }) => ({ id, severity, file, title, kind, anchor: String(anchor ?? "").slice(0, 200), side, line, anchor_found })) } : null }),
  ];
  let current = value;
  for (const shrink of shrinks) {
    current = shrink(current);
    const json = JSON.stringify(current);
    if (json.length <= STATE_CHARS && Buffer.byteLength(json) <= STATE_BYTES) return json;
  }
  throw new Error(`분석 상태가 ${STATE_CHARS}자 또는 ${STATE_BYTES}바이트를 넘어 저장하지 않았습니다`);
}

// 페이지 하위 블록을 보고서·그림·리더 메모 구획으로 나눈다. 그림·메모 제목 앞의 구분선은 그 구획에 속한다.
export function splitSections(children) {
  const isHeading = (block, title) => block.type === "heading_2" && blockText(block).trim() === title;
  const diagramAt = children.findIndex((block) => isHeading(block, DIAGRAM_HEADING));
  const memoAt = children.findIndex((block) => isHeading(block, MEMO_HEADING));
  const special = [diagramAt, memoAt].filter((index) => index >= 0);
  let reportEnd = special.length ? Math.min(...special) : children.length;
  if (reportEnd > 0 && reportEnd < children.length && children[reportEnd - 1].type === "divider") reportEnd -= 1;
  const codeAt = diagramAt >= 0 ? children.findIndex((block, index) => index > diagramAt && block.type === "code") : -1;
  const code = codeAt >= 0 && (memoAt < 0 || codeAt < memoAt) ? children[codeAt] : null;
  const status = code && children[codeAt + 1]?.type === "paragraph" ? children[codeAt + 1] : null;
  return {
    report: children.slice(0, reportEnd),
    diagram: code ? { code, status, codeText: blockText(code), statusText: status ? blockText(status) : "" } : null,
    hasMemo: memoAt >= 0,
    lastReportIndex: reportEnd - 1,
  };
}

export function createNotion({
  token, repository, dashboardPageId, prDatabaseId, cardDatabaseId, memoryPageId,
  dryRun = false, log = console.log, delayMs = 350, fetchImpl = (...args) => fetch(...args),
}) {
  let requests = 0;
  const titleKeys = new Map();
  let cardStore = null;
  let stateDatabase = null;

  async function call(method, path, body, attempt = 1) {
    requests += 1;
    if (dryRun) {
      log(`  [DRY] ${method} ${path.split("?")[0]} ${body ? `(${Buffer.byteLength(JSON.stringify(body))}바이트)` : ""}`);
      return { id: "dry", url: "dry", results: [], data_sources: [{ id: "dry" }], properties: {} };
    }
    await sleep(delayMs);
    let response;
    try {
      response = await fetchImpl(`https://api.notion.com/v1/${path}`, {
        method,
        headers: { Authorization: `Bearer ${token}`, "Notion-Version": VERSION, "Content-Type": "application/json" },
        body: body ? JSON.stringify(body) : undefined,
      });
    } catch (error) {
      // 연결 오류는 다시 보내도 결과가 같은 요청만 다시 보낸다. 행 만들기·블록 추가는 중복을 막기 위해 다시 보내지 않는다.
      if (!repeatable(method, path) || attempt >= 4) throw error;
      await sleep(delayMs * 2 ** attempt);
      return call(method, path, body, attempt + 1);
    }
    const retryable = response.status === 429 || response.status === 529 || (response.status >= 500 && repeatable(method, path));
    if (retryable && attempt < 4) {
      await sleep(Math.min(Number(response.headers?.get?.("retry-after")) * 1000 || delayMs * 2 ** attempt, 60_000));
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

  async function listChildren(blockId) {
    const blocks = [];
    let cursor = null;
    do {
      const page = await call("GET", `blocks/${blockId}/children?page_size=100${cursor ? `&start_cursor=${cursor}` : ""}`);
      blocks.push(...(page.results ?? []));
      cursor = page.has_more ? page.next_cursor : null;
    } while (cursor);
    return blocks;
  }

  async function findChildDatabase(pageId, title) {
    const children = await listChildren(pageId);
    const block = children.find((item) => item.type === "child_database" && item.child_database?.title === title);
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

  async function queryAll(database, body) {
    const rows = [];
    let cursor = null;
    do {
      const page = await call("POST", `data_sources/${dataSourceOf(database)}/query`, { page_size: 100, ...body, ...(cursor ? { start_cursor: cursor } : {}) });
      rows.push(...(page.results ?? []));
      cursor = page.has_more ? page.next_cursor : null;
    } while (cursor);
    return rows;
  }

  // 이 저장소의 같은 PR 행들(저장소 열이 비어 있는 이전 형식 행 포함)
  async function findPrRows(database, prNumber) {
    return queryAll(database, {
      filter: {
        and: [
          { property: "PR 번호", number: { equals: prNumber } },
          { or: [{ property: "저장소", rich_text: { equals: repository } }, { property: "저장소", rich_text: { is_empty: true } }] },
        ],
      },
    });
  }

  // 같은 PR의 대표 페이지: '최신' 기록 중 가장 최근에 만든 행, 없으면 가장 최근 행
  const pickPrPage = (rows) => {
    const live = rows.filter((row) => !row.in_trash && !row.archived);
    const latest = live.filter((row) => row.properties?.["기록"]?.select?.name !== LABELS.record.previous);
    const pool = latest.length ? latest : live;
    return [...pool].sort((a, b) => String(b.created_time ?? "").localeCompare(String(a.created_time ?? "")))[0] ?? null;
  };

  async function ensurePrDatabase() {
    const existing = await findChildDatabase(dashboardPageId, PR_DB_TITLE);
    if (existing) return existing;
    for (const batch of chunkBlocks([
      callout(toRichText([
        { text: "현재 작업 상황\n", bold: true },
        { text: "PR이 검토 요청 상태로 열리거나 수정본이 올라오면 GitHub Actions가 자동으로 분석해 아래 표에 기록합니다. 행을 열면 PR별 보고서가 나옵니다.\n" },
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

  async function getPrDatabase({ create }) {
    if (prDatabaseId) return call("GET", `databases/${prDatabaseId}`);
    return create ? ensurePrDatabase() : findChildDatabase(dashboardPageId, PR_DB_TITLE);
  }

  async function getStateDatabase({ create }) {
    if (stateDatabase) return stateDatabase;
    stateDatabase = await findChildDatabase(memoryPageId, STATE_DB_TITLE);
    if (!stateDatabase && create) {
      stateDatabase = await call("POST", "databases", {
        parent: { type: "page_id", page_id: memoryPageId },
        is_inline: true,
        title: text(STATE_DB_TITLE),
        initial_data_source: {
          properties: { "이름": { title: {} }, "PR 번호": { number: { format: "number" } }, "상태 JSON": { rich_text: {} }, "seq": { number: { format: "number" } } },
        },
      });
    }
    return stateDatabase;
  }

  async function readJsonRow(number) {
    const database = await getStateDatabase({ create: false });
    if (!database) return null;
    const rows = await queryAll(database, { filter: { property: "PR 번호", number: { equals: number } } });
    const parts = rows[0]?.properties?.["상태 JSON"]?.rich_text ?? [];
    try {
      return parts.length ? JSON.parse(parts.map((part) => part.plain_text ?? part.text?.content ?? "").join("")) : null;
    } catch {
      return null;
    }
  }

  // JSON을 같은 행에 덮어쓴다(행이 없으면 만들고, 중복 행은 휴지통으로 보낸다).
  async function writeJsonRow(number, title, value, seq) {
    const database = await getStateDatabase({ create: true });
    const [current, ...duplicates] = await queryAll(database, { filter: { property: "PR 번호", number: { equals: number } } });
    const json = fitState(value);
    const properties = {
      "이름": { title: text(title) },
      "PR 번호": { number },
      "상태 JSON": { rich_text: splitText(json, 1900).slice(0, 100).map((content) => ({ type: "text", text: { content } })) },
      "seq": { number: seq ?? null },
    };
    if (current) await call("PATCH", `pages/${current.id}`, { properties });
    else await createRow(database, properties, undefined);
    for (const extra of duplicates) await call("PATCH", `pages/${extra.id}`, { in_trash: true });
  }

  // 블록 목록을 parentId 아래 지정 위치(start·after_block·end)에 100개씩 넣는다. 넣은 최상위 블록 ID 목록을 돌려준다.
  async function insertBlocks(parentId, blocks, position) {
    const ids = [];
    let after = position?.type === "after_block" ? position.after_block.id : null;
    let first = position?.type === "start";
    for (const batch of chunkBlocks(blocks)) {
      const where = first ? { type: "start" } : after ? { type: "after_block", after_block: { id: after } } : { type: "end" };
      const result = await call("PATCH", `blocks/${parentId}/children`, { children: batch, position: where });
      ids.push(...(result.results ?? []).map((block) => block.id));
      after = ids.at(-1) ?? after;
      first = false;
    }
    return ids;
  }

  // 블록을 휴지통으로 보낸다. 하위 페이지·표 블록은 지우지 않는다. 지우지 못한 블록 ID를 돌려준다(이미 없으면 성공으로 본다).
  async function deleteBlocks(blocks) {
    const failed = [];
    for (const block of blocks) {
      if (PROTECTED_BLOCKS.has(block.type)) continue;
      try {
        await call("DELETE", `blocks/${block.id}`);
      } catch (error) {
        if (error.status !== 404) failed.push(block.id);
      }
    }
    return failed;
  }

  // 카드 표와 제목 열 이름, 태그별 카드를 한 번만 읽는다.
  async function loadCards({ fresh = false } = {}) {
    if (!cardDatabaseId) return null;
    if (cardStore && !fresh) return cardStore;
    const database = cardStore?.database ?? await call("GET", `databases/${cardDatabaseId}`);
    const titleKey = await ensureSchema(database, CARD_DB_PROPERTIES);
    const rows = await queryAll(database, {});
    const cards = {};
    for (const row of rows) {
      const props = row.properties ?? {};
      const tag = plain(props[titleKey]).trim();
      if (!tag || cards[tag] || row.in_trash) continue;
      cards[tag] = {
        ...cardFromFields(tag, {
          scope: plain(props["범위"]), contracts: plain(props["핵심 계약"]), evidence: plain(props["근거 파일·심볼"]),
          revision: props["리비전"]?.number ?? 0, base_sha: plain(props["기준 SHA"]), prs: plain(props["반영한 PR"]),
          records: plain(props["적용 기록"]), keywords: plain(props["키워드"]), legacy_summary: plain(props["요약"]),
        }),
        id: row.id,
      };
    }
    cardStore = { database, titleKey, cards };
    return cardStore;
  }

  return {
    get requests() {
      return requests;
    },

    // PR의 분석 상태를 읽는다. 없거나 해석에 실패하거나 다른 저장소의 것이면 null.
    async readState(prNumber) {
      const state = await readJsonRow(prNumber);
      if (!state || (state.repo && state.repo !== repository)) return null;
      return state;
    },

    async saveState(prNumber, state) {
      await writeJsonRow(prNumber, `PR #${prNumber} 상태`, state, state.seq);
    },

    // 운영 상태(전체 대기 시각 등). PR 번호 0 행에 둔다.
    async readOps() {
      return (await readJsonRow(OPS_ROW)) ?? {};
    },

    async saveOps(ops) {
      await writeJsonRow(OPS_ROW, "운영 상태(자동)", ops, null);
    },

    // PR 페이지를 쓴다. 없으면 보고서·그림·리더 메모로 만들고, 있으면 속성과 보고서만 바꾼다.
    // makeDiagram(): 페이지에 그림이 없을 때만 불러 그림 블록을 만든다(null이면 넣지 않음).
    // diagramStatus(diagram): 그림이 이미 있을 때 상태 줄 글을 돌려주면 그 줄을 고친다(null이면 그대로).
    // previousReportIds: 직전 실행이 넣은 보고서 블록 ID. 있으면 그 블록만 지우고, 없으면(상태 유실·이전 형식 페이지)
    //   리더 메모·그림 제목 앞까지를 보고서로 보고 지운다. 두 제목이 모두 없으면 아무것도 지우지 않는다.
    async publishPr({ prNumber, report, pageIdHint, makeDiagram, diagramStatus, previousReportIds = [] }) {
      const database = await getPrDatabase({ create: true });
      const titleKey = await ensureSchema(database, PR_DB_PROPERTIES, PR_DB_RENAMES);
      const properties = toNotionProperties(report.title, { ...report.properties, "기록": LABELS.record.latest }, titleKey);
      let page = null;
      if (pageIdHint) {
        page = await call("GET", `pages/${pageIdHint}`).catch(() => null);
        if (page && (page.in_trash || page.archived)) page = null;
      }
      if (!page) page = pickPrPage(await findPrRows(database, prNumber));

      if (!page) {
        const diagram = makeDiagram?.() ?? null;
        const [first, ...rest] = chunkBlocks([...report.blocks, ...(diagram?.blocks ?? []), ...memoBlocks()]);
        const created = await createRow(database, properties, first);
        for (const batch of rest) await call("PATCH", `blocks/${created.id}/children`, { children: batch });
        const listed = await listChildren(created.id);
        return {
          page_id: created.id, url: created.url ?? created.id, created: true, diagram: diagram ? { created: true, ...diagram.meta } : null,
          report_block_ids: listed.slice(0, report.blocks.length).map((block) => block.id), undeleted_ids: [], deleted: 0,
        };
      }

      await call("PATCH", `pages/${page.id}`, { properties });
      const children = await listChildren(page.id);
      const sections = splitSections(children);
      // 그림·리더 메모 제목이 모두 없는 페이지는 구조를 알 수 없으므로 기존 블록을 지우지 않고 리더 메모 아래로 남긴다.
      const unknownLayout = !sections.diagram && !sections.hasMemo && children.length > 0;
      const known = new Set(previousReportIds);
      const toDelete = known.size ? children.filter((block) => known.has(block.id)) : unknownLayout ? [] : sections.report;
      const newIds = await insertBlocks(page.id, report.blocks, { type: "start" });
      let lastNew = newIds.at(-1) ?? null;
      let diagramResult = null;
      if (!sections.diagram) {
        const diagram = makeDiagram?.() ?? null;
        if (diagram) {
          lastNew = (await insertBlocks(page.id, diagram.blocks, lastNew ? { type: "after_block", after_block: { id: lastNew } } : { type: "end" })).at(-1) ?? lastNew;
          diagramResult = { created: true, ...diagram.meta };
        }
      } else {
        diagramResult = { created: false, code_text: sections.diagram.codeText, status_text: sections.diagram.statusText };
        const nextStatus = diagramStatus?.(diagramResult);
        if (nextStatus && sections.diagram.status && nextStatus !== sections.diagram.statusText) {
          await call("PATCH", `blocks/${sections.diagram.status.id}`, { paragraph: { rich_text: text(nextStatus, { italic: true }) } });
          diagramResult.status_updated = true;
        }
      }
      if (!sections.hasMemo) await insertBlocks(page.id, memoBlocks(), unknownLayout && lastNew ? { type: "after_block", after_block: { id: lastNew } } : { type: "end" });
      const undeleted = await deleteBlocks(toDelete);
      return {
        page_id: page.id, url: page.url ?? page.id, created: false, diagram: diagramResult,
        report_block_ids: newIds, undeleted_ids: undeleted, deleted: toDelete.length - undeleted.length,
      };
    },

    // 같은 PR의 모든 행 상태를 바꾸고, 대표 페이지에는 추가 속성을 쓴다(AI 호출 없음). 행이 없으면 아무것도 만들지 않는다.
    async markStatus(prNumber, statusLabel, extra = {}) {
      const database = await getPrDatabase({ create: false });
      if (!database) return 0;
      await ensureSchema(database, PR_DB_PROPERTIES, PR_DB_RENAMES);
      const rows = (await findPrRows(database, prNumber)).filter((row) => !row.in_trash);
      const main = pickPrPage(rows);
      for (const row of rows) {
        const values = { "상태": statusLabel, ...(row.id === main?.id ? extra : {}) };
        await call("PATCH", `pages/${row.id}`, { properties: toNotionProperties(null, values) });
      }
      return rows.length;
    },

    // 대표 페이지 속성만 고친다.
    async setPrProperties(prNumber, values) {
      const database = await getPrDatabase({ create: false });
      if (!database) return null;
      await ensureSchema(database, PR_DB_PROPERTIES, PR_DB_RENAMES);
      const main = pickPrPage(await findPrRows(database, prNumber));
      if (!main) return null;
      await call("PATCH", `pages/${main.id}`, { properties: toNotionProperties(null, values) });
      return main.id;
    },

    // 태그별 영역 카드. 카드 표가 설정되지 않았으면 빈 객체. fresh면 다시 읽는다.
    async readCards({ fresh = false } = {}) {
      return (await loadCards({ fresh }))?.cards ?? {};
    },

    // 카드 한 행을 쓴다. 쓰기 직전에 다시 읽어 리비전이 expectedRevision과 다르면 쓰지 않고 false를 돌려준다.
    async writeCard(tag, card, expectedRevision) {
      const store = await loadCards();
      if (!store) return false;
      const existing = store.cards[tag];
      if (existing) {
        const row = await call("GET", `pages/${existing.id}`);
        if ((row.properties?.["리비전"]?.number ?? 0) !== expectedRevision) return false;
      } else if (expectedRevision !== 0) {
        return false;
      }
      const fields = cardToFields(card);
      const properties = {
        [store.titleKey]: { title: text(tag) },
        "범위": rich(fields.scope), "핵심 계약": rich(fields.contracts), "근거 파일·심볼": rich(fields.evidence),
        "기준 SHA": rich(fields.base_sha), "리비전": { number: fields.revision }, "적용 기록": rich(fields.records),
        "반영한 PR": rich(fields.prs), "키워드": rich(fields.keywords), "갱신 시각": { date: { start: card.updated_at } },
      };
      const row = existing ? await call("PATCH", `pages/${existing.id}`, { properties }) : await createRow(store.database, properties, undefined);
      store.cards[tag] = { ...card, id: existing?.id ?? row.id, tag };
      return true;
    },

    listChildren,
    findChildDatabase,
    call,
  };
}
