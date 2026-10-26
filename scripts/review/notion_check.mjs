// Notion 연결 점검(GitHub Actions의 REST 연결 'PR_Analysis' 기준). 운영 페이지에는 쓰지 않는다.
// 1) 설정된 표 ID로 DB를 읽어 DB ID와 data source ID를 구분해 보여 주고, 페이지 ID(현황판·메모리·시험용)를 읽는다.
// 2) 시험용 페이지(NOTION_SANDBOX_PAGE_ID) 아래 '연결 점검(자동)' 하위 페이지에서 만들기(없을 때) → 다시 읽기 → 고치기 → 다시 읽기를 확인한다.
// 출력은 ID·제목·성공 여부뿐이다. 하나라도 실패하면 종료 코드 1로 끝난다.
import { createNotion, plain } from "./notion_store.mjs";
import { paragraph, text } from "../notion/blocks.mjs";

const env = process.env;
const CHECK_TITLE = "PR 분석 연결 점검(자동)";
const notion = createNotion({ token: env.NOTION_REVIEW_TOKEN, repository: env.GITHUB_REPOSITORY });
const results = [];
const record = (name, ok, detail = "") => {
  results.push({ name, ok });
  console.log(`${ok ? "PASS" : "FAIL"} ${name}${detail ? ` · ${detail}` : ""}`);
};
const titleOf = (page) => plain(Object.values(page.properties ?? {}).find((property) => property.type === "title") ?? {}) || plain({ title: page.title ?? [] });

if (!env.NOTION_REVIEW_TOKEN) {
  console.log("NOTION_REVIEW_TOKEN이 없습니다.");
  process.exit(1);
}

for (const [name, id] of [["PR 분석 표", env.NOTION_PR_DATABASE_ID], ["영역 카드 표", env.NOTION_CARD_DATABASE_ID]]) {
  if (!id) {
    record(name, false, "ID 변수 없음");
    continue;
  }
  try {
    const database = await notion.call("GET", `databases/${id}`);
    const dataSources = (database.data_sources ?? []).map((source) => source.id);
    const schema = dataSources[0] ? await notion.call("GET", `data_sources/${dataSources[0]}`) : null;
    record(name, Boolean(dataSources.length), `DB ID ${database.id} · data source ID ${dataSources.join(", ") || "없음"} · 제목 '${plain({ title: database.title ?? [] })}' · 열 ${Object.keys(schema?.properties ?? {}).length}개`);
  } catch (error) {
    record(name, false, `${error.status ?? ""} ${error.code ?? error.message}`);
  }
}

for (const [name, id] of [["현황판 페이지", env.NOTION_DASHBOARD_PAGE_ID], ["메모리 페이지", env.NOTION_MEMORY_PAGE_ID], ["시험용 페이지", env.NOTION_SANDBOX_PAGE_ID]]) {
  if (!id) {
    record(name, false, "ID 변수 없음");
    continue;
  }
  try {
    const page = await notion.call("GET", `pages/${id}`);
    record(name, !page.in_trash, `페이지 ID ${page.id} · 제목 '${titleOf(page)}' · 상위 ${page.parent?.type ?? "-"}${page.in_trash ? " · 휴지통" : ""}`);
  } catch (error) {
    record(name, false, `${error.status ?? ""} ${error.code ?? error.message}`);
  }
}

if (env.NOTION_SANDBOX_PAGE_ID) {
  try {
    const stamp = new Date().toISOString();
    const children = await notion.listChildren(env.NOTION_SANDBOX_PAGE_ID);
    let pageId = children.find((block) => block.type === "child_page" && block.child_page?.title === CHECK_TITLE)?.id;
    if (!pageId) {
      const created = await notion.call("POST", "pages", {
        parent: { type: "page_id", page_id: env.NOTION_SANDBOX_PAGE_ID },
        properties: { title: { title: text(CHECK_TITLE) } },
        children: [paragraph(text(`점검 시각 ${stamp}`))],
      });
      pageId = created.id;
      record("시험용 하위 페이지 만들기", Boolean(pageId), `페이지 ID ${pageId}`);
    } else {
      record("시험용 하위 페이지 찾기", true, `페이지 ID ${pageId}(이전 점검에서 만든 페이지 재사용)`);
    }
    const before = (await notion.listChildren(pageId)).find((block) => block.type === "paragraph");
    record("다시 읽기", Boolean(before), before ? `문단 '${plain({ rich_text: before.paragraph.rich_text })}'` : "문단 없음");
    const wanted = `점검 시각 ${stamp}`;
    if (before) {
      await notion.call("PATCH", `blocks/${before.id}`, { paragraph: { rich_text: text(wanted) } });
      const after = (await notion.listChildren(pageId)).find((block) => block.id === before.id);
      record("고친 뒤 다시 읽기", plain({ rich_text: after?.paragraph?.rich_text ?? [] }) === wanted, `문단 '${plain({ rich_text: after?.paragraph?.rich_text ?? [] })}'`);
    }
  } catch (error) {
    record("시험용 쓰기 점검", false, `${error.status ?? ""} ${error.code ?? error.message}`);
  }
}

const failed = results.filter((item) => !item.ok).length;
console.log(`결과: 통과 ${results.length - failed} · 실패 ${failed} · Notion 요청 ${notion.requests}회`);
process.exit(failed ? 1 : 0);
