// PR 페이지의 '서비스 아키텍처' 그림을 만든다(PR당 한 번, 첫 분석 때).
// develop(base) 코드로 이전 모델을, develop에 PR을 합친 결과(충돌이면 PR head) 코드로 이후 모델을 계산해 추가·변경·삭제를 색칠한다.
// 코드는 실행하지 않고 git 객체를 글자로만 해석한다.
import {
  buildModel, captionText, isServicePath, nodeFor, parseArchitectureRules, renderMermaid, validateMermaid,
} from "../notion/architecture.mjs";
import { diagramBlocks, diagramFirstLine } from "./render.mjs";

// repo: createRepoReader 결과. 반환: { blocks, meta: { head, at, problems } }
export function buildPrDiagram({ repo, architecture, baseSha, conflict, headSha, prNumber, files, at }) {
  const rules = parseArchitectureRules(architecture);
  const warnings = [];
  const afterTree = conflict.state === "clean" && conflict.tree ? conflict.tree : headSha;
  const before = buildModel(repo.filesAt(baseSha, isServicePath), rules, []);
  const after = buildModel(repo.filesAt(afterTree, isServicePath), rules, warnings);
  const changedIds = [...new Set(files.flatMap((file) => [file.filename, file.previous_filename]).filter(Boolean).filter(isServicePath).map((path) => nodeFor(path, rules).id))];
  const { mermaid, diff } = renderMermaid({ after, before, changedIds, sha: headSha, pr: prNumber });
  const problems = validateMermaid(mermaid);
  const source = afterTree === headSha ? "충돌로 PR 브랜치 코드만 기준" : "develop에 이 PR을 합친 코드 기준";
  const caption = `${captionText(diff, `develop ${String(baseSha).slice(0, 7)}과 비교, ${source}`)}${problems.length ? ` · 그림 점검 실패(${problems.join(", ")})` : ""}`;
  const statusText = diagramFirstLine({ head: headSha, at });
  return { blocks: diagramBlocks({ mermaid, caption, statusText }), meta: { head: headSha, at, problems, warnings } };
}
