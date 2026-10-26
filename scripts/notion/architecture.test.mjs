// 현재 서비스 아키텍처 모델(코드 해석·노드·연결선·렌더·역파싱·비교) 테스트

import assert from "node:assert/strict";
import { readFileSync } from "node:fs";
import { test } from "node:test";

import {
  buildModel, captionText, diffModels, hasContent, isServicePath, nodeFor, parseArchitectureRules, parseImports,
  parseMermaidModel, renderMermaid, resolveImport, scanPython, validateMermaid,
} from "./architecture.mjs";

const RULES = parseArchitectureRules([
  "```mermaid",
  "flowchart LR",
  '  frontend["frontend/<br/>Streamlit UI"]',
  '  ingestion["src/ingestion/<br/>수집·전처리"]',
  '  retrieval["src/retrieval/<br/>색인·검색"]',
  '  services["src/services/<br/>진입점"]',
  "  설명: `%% map <경로> <노드>` 형식은 줄 맨 앞에서만 읽는다",
  "  %% map frontend/ frontend",
  "  %% map src/ingestion/ ingestion",
  "  %% map src/retrieval/ retrieval",
  "  %% map src/services/ services",
  "  %% map src/schemas.py pipeline",
  "  %% ext import:chromadb chroma Chroma 벡터 저장소",
  "  %% ext host:plus.kipris.or.kr kipris KIPRIS Plus API",
  "```",
].join("\n"));

const file = (path, content) => ({ path, size: Buffer.byteLength(content), content });

test("실제 docs/architecture.md 규칙을 줄 맨 앞 기준으로 읽는다", () => {
  const rules = parseArchitectureRules(readFileSync(new URL("../../docs/architecture.md", import.meta.url), "utf8"));
  assert.ok(rules.maps.length >= 18);
  assert.ok(!rules.maps.some((map) => map.prefix.startsWith("<")));
  assert.deepEqual(rules.ext.map((rule) => rule.node).sort(), ["chroma", "dart", "kipris", "naver", "openai"]);
  assert.equal(rules.labels.frontend, "frontend/<br/>Streamlit UI");
  assert.equal(nodeFor("requirements-ui.txt", rules).id, "l_runtime");
});

test("scanPython은 주석·docstring을 지우고 한 줄 문자열만 모은다", () => {
  const source = [
    '"""사용 예:',
    "    from src.services import x",
    '"""',
    "import os  # from src.generation import y",
    'URL = "https://plus.kipris.or.kr/openapi/rest/" "freeSearch"',
    "def run():",
    "    from openai import OpenAI",
    "    note = 'import fake'",
  ].join("\n");
  const { code, strings } = scanPython(source);
  assert.ok(!code.includes("src.services"));
  assert.ok(!code.includes("src.generation"));
  assert.ok(code.includes("    from openai import OpenAI"));
  assert.deepEqual(strings, ["https://plus.kipris.or.kr/openapi/rest/", "freeSearch", "import fake"]);
  assert.deepEqual(parseImports(code).map((item) => item.module), ["os", "openai"]);
});

test("parseImports는 별칭·여러 모듈·괄호 여러 줄·상대·역슬래시 이어 쓰기를 읽는다", () => {
  const code = [
    "import a.b as c, d",
    "from x.y import (",
    "    m,",
    "    n as k,",
    ")",
    "from . import sibling",
    "from ..pkg import thing",
    "from z \\",
    "    import w",
  ].join("\n");
  assert.deepEqual(parseImports(code), [
    { level: 0, module: "a.b", names: [] },
    { level: 0, module: "d", names: [] },
    { level: 0, module: "x.y", names: ["m", "n"] },
    { level: 1, module: "", names: ["sibling"] },
    { level: 2, module: "pkg", names: ["thing"] },
    { level: 0, module: "z", names: ["w"] },
  ]);
});

test("resolveImport는 모듈 파일·패키지·from 이름·상대 경로를 저장소 경로로 풀고, 없으면 외부 모듈로 본다", () => {
  const paths = new Set(["src/schemas.py", "src/ingestion/kipris_client.py", "src/ingestion/__init__.py", "src/retrieval/a.py"]);
  const dirs = new Set(["src", "src/ingestion", "src/retrieval"]);
  assert.deepEqual(resolveImport("src/retrieval/a.py", { level: 0, module: "src", names: ["schemas"] }, paths, dirs).internal, ["src/schemas.py"]);
  assert.deepEqual(resolveImport("x.py", { level: 0, module: "src.ingestion", names: ["kipris_client"] }, paths, dirs).internal, ["src/ingestion/kipris_client.py"]);
  assert.deepEqual(resolveImport("x.py", { level: 0, module: "src.ingestion", names: ["missing"] }, paths, dirs).internal, ["src/ingestion/__init__.py"]);
  assert.deepEqual(resolveImport("src/retrieval/a.py", { level: 2, module: "schemas", names: [] }, paths, dirs).internal, ["src/schemas.py"]);
  assert.deepEqual(resolveImport("src/retrieval/a.py", { level: 0, module: "chromadb.api", names: ["ClientAPI"] }, paths, dirs), { internal: [], external: "chromadb" });
});

test("hasContent는 docstring뿐인 .py·README·.gitkeep을 내용 없음으로 본다", () => {
  assert.equal(hasContent(file("src/a.py", '"""설명만 있음"""\n# 주석\n')), false);
  assert.equal(hasContent(file("src/a.py", "X = 1\n")), true);
  assert.equal(hasContent(file("src/x/README.md", "# 안내")), false);
  assert.equal(hasContent(file("src/x/.gitkeep", "")), false);
  assert.equal(hasContent(file("configs/a.yaml", "  \n")), false);
  assert.equal(hasContent(file("configs/a.yaml", "a: 1")), true);
  assert.equal(isServicePath("tests/test_a.py"), false);
  assert.equal(isServicePath("scripts/review/lib.mjs"), false);
  assert.equal(isServicePath("scripts/collect.py"), true);
});

test("buildModel은 내용 있는 계층·공통 계약·외부 서비스와 실제 연결만 그린다", () => {
  const warnings = [];
  const model = buildModel([
    file("src/schemas.py", "class A: pass\n"),
    file("src/ingestion/kipris_client.py", 'from src.schemas import A\nURL = "https://plus.kipris.or.kr/x"\n# https://opendart.fss.or.kr\n'),
    file("src/retrieval/search.py", "import chromadb\nfrom src.services import entry\n"),
    file("src/services/entry.py", ""),
    file("src/agents/plan.py", "from src.retrieval import search\n"),
    file("frontend/app.py", '"""from src.ingestion import kipris_client"""\nimport streamlit\n'),
    file("tests/test_x.py", "from src.schemas import A\n"),
  ], RULES, warnings);
  const ids = model.nodes.map((node) => node.id);
  assert.ok(ids.includes("l_frontend") && ids.includes("l_ingestion") && ids.includes("l_retrieval") && ids.includes("c_contract"));
  assert.ok(ids.includes("x_kipris") && ids.includes("x_chroma"));
  assert.ok(!ids.includes("l_services"), "빈 계층은 그리지 않음");
  assert.ok(ids.some((id) => id.startsWith("p_src_agents")), "map에 없는 src 디렉터리는 경로 노드");
  const edges = model.edges.map((edge) => `${edge.from}${edge.style === "dotted" ? "-.->" : "-->"}${edge.to}`);
  assert.ok(edges.includes("l_ingestion-.->c_contract"));
  assert.ok(edges.includes("l_ingestion-->x_kipris"));
  assert.ok(edges.includes("l_retrieval-->x_chroma"));
  assert.ok(edges.some((edge) => /^p_src_agents.*-->l_retrieval$/.test(edge)));
  assert.ok(!edges.some((edge) => edge.startsWith("l_frontend")), "docstring 속 import는 연결선이 아님");
  assert.ok(!ids.includes("x_dart"), "주석 속 주소는 외부 서비스가 아님");
  assert.equal(warnings.length, 1);
});

test("렌더한 그림은 문법 점검을 통과하고, 메타 줄과 노드·연결선 줄로 같은 모델이 복원된다", () => {
  const before = buildModel([file("src/ingestion/a.py", "X = 1\n"), file("src/old/b.py", "Y = 2\n")], RULES);
  const after = buildModel([
    file("src/ingestion/a.py", "from src.schemas import A\n"),
    file("src/schemas.py", "class A: pass\n"),
    file("src/retrieval/s.py", "import chromadb\n"),
  ], RULES);
  const { mermaid, diff } = renderMermaid({ after, before, changedIds: ["l_ingestion"], sha: "a".repeat(40), pr: 7 });
  assert.deepEqual(validateMermaid(mermaid), []);
  assert.deepEqual(diff.addedNodes.map((node) => node.id).sort(), ["c_contract", "l_retrieval", "x_chroma"]);
  assert.deepEqual(diff.changedNodes.map((node) => node.id), ["l_ingestion"]);
  assert.equal(diff.removedNodes.length, 1);
  assert.match(mermaid, /class c_contract,l_retrieval,x_chroma added|class [a-z_,]+ added/);
  assert.match(mermaid, /class l_ingestion changed/);
  assert.match(mermaid, /class p_src_old_\w+ removed/);
  assert.match(mermaid, /linkStyle 0,1 stroke:#16a34a/);
  const parsed = parseMermaidModel(mermaid);
  assert.equal(parsed.sha, "a".repeat(40));
  assert.equal(parsed.pr, 7);
  assert.deepEqual(parsed.nodes.map((node) => node.id).sort(), after.nodes.map((node) => node.id).sort());
  assert.deepEqual(parsed.edges.length, after.edges.length);
  assert.ok(!parsed.nodes.some((node) => node.id.startsWith("p_src_old")), "삭제 표시 뒤의 노드는 복원하지 않음");
  assert.deepEqual(diffModels(after, parsed, []).addedNodes, []);
});

test("이전 그림의 노드 순서를 지키고 새 노드는 뒤에 붙인다", () => {
  const previous = { nodes: [{ id: "l_retrieval", label: "r", kind: "layer" }, { id: "l_ingestion", label: "i", kind: "layer" }], edges: [] };
  const after = buildModel([file("src/ingestion/a.py", "X = 1\n"), file("src/retrieval/s.py", "Y = 1\n"), file("frontend/app.py", "Z = 1\n")], RULES);
  const { mermaid } = renderMermaid({ after, before: previous, sha: "b".repeat(7), pr: 8 });
  const order = mermaid.split("\n").map((line) => /^\s+(l_\w+)\[/.exec(line)?.[1]).filter(Boolean);
  assert.deepEqual(order, ["l_retrieval", "l_ingestion", "l_frontend"]);
});

test("validateMermaid는 선언 안 된 끝점·예약어 ID·linkStyle 범위 초과·메타 줄 누락을 잡는다", () => {
  assert.ok(validateMermaid('flowchart LR\n  %% arch v1 sha=abcdef1 pr=1\n  a["x"]\n  a --> b\n  linkStyle 3 stroke:#000').length >= 2);
  assert.ok(validateMermaid('flowchart LR\n  %% arch v1 sha=abcdef1 pr=1\n  end["x"]').some((problem) => problem.includes("허용되지 않는")));
  assert.ok(validateMermaid('flowchart LR\n  a["x"]').some((problem) => problem.includes("메타")));
});

test("캡션은 추가·변경·삭제를 라벨 첫 줄로 적고, 변화가 없으면 '서비스 구성 변경 없음'이라고 쓴다", () => {
  const node = (id, label, kind = "layer") => ({ id, label, kind });
  const diff = {
    addedNodes: [node("x_openai", "OpenAI API", "external")], changedNodes: [node("l_runtime", "configs/ · requirements<br/>Dockerfile")],
    removedNodes: [], addedEdges: [{}], removedEdges: [],
  };
  assert.equal(captionText(diff, "이전 그림: PR #1"), "🟩 추가 OpenAI API · 🟨 변경 configs/ · requirements · 이전 그림: PR #1");
  assert.equal(captionText({ addedNodes: [], changedNodes: [], removedNodes: [], addedEdges: [], removedEdges: [] }, "출처"), "서비스 구성 변경 없음 · 출처");
});
