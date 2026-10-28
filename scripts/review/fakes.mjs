// 테스트 전용 가짜 연결이다(운영 코드에서 쓰지 않음).
// - createFakeNotionApi: Notion REST API(2026-03-11) 중 이 자동화가 쓰는 요청만 메모리에서 흉내 낸다. 실패 주입을 지원한다.
// - createFakeOpenAI: Responses API 응답을 순서대로 돌려주고 받은 요청을 기록한다.
// - createFakeGitHub·createFakeRepo: PR·파일·커밋·CI와 git 객체 읽기를 고정 데이터로 돌려준다.

const plainOf = (property) => (property?.title ?? property?.rich_text ?? []).map((part) => part.plain_text ?? part.text?.content ?? "").join("");

export function createFakeNotionApi({ failOn = () => null } = {}) {
  let counter = 0;
  let clock = 0;
  const pages = new Map();
  const databases = new Map();
  const sources = new Map();
  const blocks = new Map();
  const children = new Map();
  const calls = [];
  const nextId = (prefix) => `${prefix}${String(++counter).padStart(4, "0")}`;
  const json = (status, body) => ({ ok: status < 400, status, headers: new Map(), json: async () => body });

  function storeBlocks(parentId, list) {
    const created = [];
    for (const raw of list ?? []) {
      const { children: nested, ...value } = raw[raw.type] ?? {};
      const id = nextId("blk");
      const block = { object: "block", id, type: raw.type, [raw.type]: value, has_children: Boolean(nested?.length), in_trash: false };
      blocks.set(id, block);
      children.set(id, []);
      if (nested?.length) children.get(id).push(...storeBlocks(id, nested).map((item) => item.id));
      created.push(block);
    }
    return created;
  }

  function insert(parentId, ids, position) {
    const list = children.get(parentId) ?? [];
    let at = list.length;
    if (position?.type === "start") at = 0;
    if (position?.type === "after_block") at = list.indexOf(position.after_block.id) + 1;
    list.splice(at, 0, ...ids);
    children.set(parentId, list);
  }

  const schemaOf = (properties) => Object.fromEntries(Object.entries(properties).map(([name, config]) => [name, { type: config.type ?? Object.keys(config)[0], ...config }]));

  function matches(page, filter, schema) {
    if (!filter) return true;
    if (filter.and) return filter.and.every((item) => matches(page, item, schema));
    if (filter.or) return filter.or.some((item) => matches(page, item, schema));
    if (!schema[filter.property]) throw Object.assign(new Error("unknown property"), { status: 400 });
    const property = page.properties[filter.property];
    if (filter.number) {
      const value = property?.number ?? null;
      if ("equals" in filter.number) return value === filter.number.equals;
      if ("does_not_equal" in filter.number) return value !== filter.number.does_not_equal;
    }
    if (filter.rich_text) {
      const value = plainOf(property);
      if ("equals" in filter.rich_text) return value === filter.rich_text.equals;
      if ("is_empty" in filter.rich_text) return value === "";
      if ("contains" in filter.rich_text) return value.includes(filter.rich_text.contains);
    }
    if (filter.select) {
      const value = property?.select?.name ?? null;
      if ("equals" in filter.select) return value === filter.select.equals;
      if ("does_not_equal" in filter.select) return value !== filter.select.does_not_equal;
    }
    return false;
  }

  function createPage(parent, properties, list) {
    const id = nextId("page");
    const page = {
      object: "page", id, url: `https://notion.test/${id}`, parent, properties: structuredClone(properties ?? {}),
      created_time: new Date(Date.UTC(2026, 9, 26, 0, 0, clock++)).toISOString(), in_trash: false,
    };
    pages.set(id, page);
    children.set(id, []);
    insert(id, storeBlocks(id, list).map((block) => block.id));
    if (parent.type === "page_id") {
      const blockId = nextId("blk");
      blocks.set(blockId, { object: "block", id: blockId, type: "child_page", child_page: { title: plainOf(Object.values(properties)[0]) } });
      insert(parent.page_id, [blockId]);
    }
    return page;
  }

  async function fetchImpl(url, { method, body }) {
    const path = url.replace("https://api.notion.com/v1/", "");
    const data = body ? JSON.parse(body) : undefined;
    calls.push({ method, path, body: data });
    const injected = failOn(method, path, data);
    if (injected) return json(injected.status ?? 500, { code: injected.code ?? "fake_failure", message: "injected" });
    const [route, query = ""] = path.split("?");
    const params = new URLSearchParams(query);
    let match;
    try {
      if (method === "POST" && route === "databases") {
        const id = nextId("db");
        const sourceId = nextId("ds");
        databases.set(id, { object: "database", id, title: data.title, data_sources: [{ id: sourceId }], parent: data.parent });
        sources.set(sourceId, { id: sourceId, database: id, properties: schemaOf(data.initial_data_source?.properties ?? {}) });
        blocks.set(id, { object: "block", id, type: "child_database", child_database: { title: plainOf({ title: data.title }) } });
        insert(data.parent.page_id, [id]);
        return json(200, databases.get(id));
      }
      if ((match = /^databases\/([^/]+)$/.exec(route)) && method === "GET") {
        return databases.has(match[1]) ? json(200, databases.get(match[1])) : json(404, { code: "object_not_found" });
      }
      if ((match = /^data_sources\/([^/]+)$/.exec(route))) {
        const source = sources.get(match[1]);
        if (!source) return json(404, { code: "object_not_found" });
        if (method === "PATCH") {
          for (const [name, config] of Object.entries(data.properties)) {
            if (config.name && Object.keys(config).length === 1) {
              source.properties[config.name] = source.properties[name];
              delete source.properties[name];
            } else source.properties[name] = { type: config.type ?? Object.keys(config)[0], ...config };
          }
        }
        return json(200, { id: source.id, properties: source.properties });
      }
      if ((match = /^data_sources\/([^/]+)\/query$/.exec(route)) && method === "POST") {
        const source = sources.get(match[1]);
        const rows = [...pages.values()].filter((page) => !page.in_trash && (page.parent.data_source_id === source.id || page.parent.database_id === source.database));
        return json(200, { results: rows.filter((page) => matches(page, data.filter, source.properties)), has_more: false, next_cursor: null });
      }
      if (method === "POST" && route === "pages") {
        if (data.parent.type === "data_source_id" && !sources.has(data.parent.data_source_id)) return json(400, { code: "validation_error" });
        return json(200, createPage(data.parent, data.properties, data.children));
      }
      if ((match = /^pages\/([^/]+)$/.exec(route))) {
        const page = pages.get(match[1]);
        if (!page) return json(404, { code: "object_not_found" });
        if (method === "PATCH") {
          if (data.properties) Object.assign(page.properties, structuredClone(data.properties));
          if ("in_trash" in data) page.in_trash = data.in_trash;
        }
        return json(200, page);
      }
      if ((match = /^blocks\/([^/]+)\/children$/.exec(route))) {
        const parent = match[1];
        if (method === "GET") {
          const list = (children.get(parent) ?? []).map((id) => blocks.get(id)).filter((block) => block && !block.in_trash);
          const start = Number(params.get("start_cursor") ?? 0);
          const size = Number(params.get("page_size") ?? 100);
          const slice = list.slice(start, start + size);
          return json(200, { results: slice, has_more: start + size < list.length, next_cursor: start + size < list.length ? String(start + size) : null });
        }
        if (data.children.length > 100) return json(400, { code: "validation_error" });
        const created = storeBlocks(parent, data.children);
        insert(parent, created.map((block) => block.id), data.position);
        return json(200, { results: created });
      }
      if ((match = /^blocks\/([^/]+)$/.exec(route))) {
        const block = blocks.get(match[1]);
        if (!block || block.in_trash) return json(404, { code: "object_not_found" });
        if (method === "DELETE") {
          block.in_trash = true;
          for (const list of children.values()) {
            const at = list.indexOf(block.id);
            if (at >= 0) list.splice(at, 1);
          }
        }
        if (method === "PATCH") Object.assign(block[block.type], data[block.type]);
        return json(200, block);
      }
    } catch (error) {
      return json(error.status ?? 500, { code: "validation_error", message: error.message });
    }
    return json(400, { code: "unsupported_fake_route", message: `${method} ${route}` });
  }

  // 페이지 본문을 최상위 블록 형식·글 목록으로 돌려준다(검사용).
  const outline = (pageId) => (children.get(pageId) ?? []).map((id) => blocks.get(id)).map((block) => ({ id: block.id, type: block.type, text: plainOf({ rich_text: block[block.type]?.rich_text ?? [] }) }));

  return {
    fetchImpl,
    calls,
    pages,
    blocks,
    // 시작 상태: 대시보드·메모리 페이지와 PR 분석 표·카드 표
    seedPages() {
      const dashboard = createPage({ type: "workspace" }, { title: { title: [{ text: { content: "현재 작업 상황" } }] } });
      const memory = createPage({ type: "workspace" }, { title: { title: [{ text: { content: "PR 분석 메모리" } }] } });
      return { dashboard: dashboard.id, memory: memory.id };
    },
    createDatabase(parentPageId, title, properties) {
      const id = nextId("db");
      const sourceId = nextId("ds");
      databases.set(id, { object: "database", id, title: [{ text: { content: title } }], data_sources: [{ id: sourceId }] });
      sources.set(sourceId, { id: sourceId, database: id, properties: schemaOf(properties) });
      blocks.set(id, { object: "block", id, type: "child_database", child_database: { title } });
      insert(parentPageId, [id]);
      return { id, sourceId };
    },
    addRow(sourceId, properties, list) {
      return createPage({ type: "data_source_id", data_source_id: sourceId }, properties, list);
    },
    rows(sourceId) {
      return [...pages.values()].filter((page) => page.parent.data_source_id === sourceId && !page.in_trash);
    },
    outline,
    schema: (sourceId) => sources.get(sourceId).properties,
  };
}

export function okResponse(output, { model = "gpt-6-sol", usage } = {}) {
  return {
    id: "resp_test", object: "response", model, status: "completed",
    output: [{ type: "reasoning", summary: [] }, { type: "message", role: "assistant", content: [{ type: "output_text", text: JSON.stringify(output) }] }],
    usage: usage ?? { input_tokens: 1200, input_tokens_details: { cached_tokens: 300, cache_write_tokens: 0 }, output_tokens: 900, output_tokens_details: { reasoning_tokens: 400 }, total_tokens: 2100 },
  };
}

// respond(requestBody, index)가 { status, body, headers } 또는 응답 본문(200)을 돌려준다.
export function createFakeOpenAI(respond) {
  const requests = [];
  async function fetchImpl(url, { headers, body }) {
    const parsed = JSON.parse(body);
    requests.push({ url, headers, body: parsed });
    const reply = await respond(parsed, requests.length - 1);
    const spec = typeof reply?.status === "number" ? reply : { status: 200, body: reply };
    const headerMap = new Map(Object.entries(spec.headers ?? {}).map(([key, value]) => [key.toLowerCase(), String(value)]));
    return { ok: spec.status < 400, status: spec.status, headers: { get: (name) => headerMap.get(name.toLowerCase()) ?? null }, json: async () => spec.body };
  }
  return { fetchImpl, requests };
}

const CI_JOBS = ["Black format check", "Pytest", "Automation script tests", "Docker build"];

export function createFakeGitHub(data) {
  const calls = [];
  const track = (name, value) => {
    calls.push(name);
    return structuredClone(value);
  };
  return {
    calls,
    data,
    pull: async () => track("pull", data.pr),
    files: async () => track("files", data.files),
    commits: async () => track("commits", data.commits ?? []),
    commit: async () => track("commit", { files: [] }),
    compare: async (base) => track("compare", { files: data.compareFiles?.[base] ?? [] }),
    branchSha: async () => track("branchSha", data.baseSha),
    mergeBase: async () => track("mergeBase", data.mergeBase ?? data.baseSha),
    ciRuns: async () => track("ciRuns", data.ci === "none" ? [] : [{ id: 1, html_url: "https://ci.test/1", created_at: "2026-10-26T00:00:00Z" }]),
    runJobs: async () => track("runJobs", CI_JOBS.map((name) => ({ name, status: "completed", conclusion: "success" }))),
  };
}

export function createFakeRepo({ trees = {}, sources = {} } = {}) {
  const calls = [];
  return {
    calls,
    conflict: () => ({ state: "clean", files: [], tree: "tree-after" }),
    showFile: (sha, path) => sources[path] ?? null,
    filesAt(treeish, want) {
      calls.push(treeish);
      return (trees[treeish] ?? []).map((file) => ({ path: file.path, size: file.content.length, content: want(file.path) ? file.content : undefined }));
    },
  };
}
