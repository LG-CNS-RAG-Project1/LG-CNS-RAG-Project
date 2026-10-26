// 구조화 출력 스키마를 다루는 순수 함수다.
// - checkStrictSchema: OpenAI Structured Outputs strict 규칙(루트 object, 모든 속성 required, additionalProperties:false,
//   지원 키워드만 사용, 중첩 10단계 이하)을 지키는지 점검한다.
// - validateValue: 모델 응답 JSON이 스키마(type·enum·required·additionalProperties·items·minItems·maxItems)에 맞는지 로컬에서 다시 확인한다.
const STRICT_KEYS = new Set(["type", "properties", "required", "additionalProperties", "items", "enum", "description", "minItems", "maxItems"]);

export function checkStrictSchema(schema) {
  const problems = [];
  if (schema?.type !== "object" || schema.anyOf) problems.push("$: 루트는 anyOf 없는 object여야 함");
  const walk = (node, path, depth) => {
    if (depth > 10) problems.push(`${path}: 중첩 10단계 초과`);
    for (const key of Object.keys(node ?? {})) if (!STRICT_KEYS.has(key)) problems.push(`${path}: 지원하지 않는 키워드 ${key}`);
    if (node?.type === "object") {
      const names = Object.keys(node.properties ?? {});
      const required = new Set(node.required ?? []);
      if (node.additionalProperties !== false) problems.push(`${path}: additionalProperties:false 필요`);
      for (const name of names) if (!required.has(name)) problems.push(`${path}.${name}: required에 없음`);
      for (const name of required) if (!names.includes(name)) problems.push(`${path}.${name}: 정의되지 않은 required`);
      for (const [name, child] of Object.entries(node.properties ?? {})) walk(child, `${path}.${name}`, depth + 1);
    } else if (node?.type === "array") {
      if (!node.items) problems.push(`${path}: items 없음`);
      else walk(node.items, `${path}[]`, depth + 1);
    } else if (node?.enum && !node.enum.length) {
      problems.push(`${path}: 빈 enum`);
    }
  };
  walk(schema, "$", 1);
  return problems;
}

const typeOf = (value) => (value === null ? "null" : Array.isArray(value) ? "array" : Number.isInteger(value) ? "integer" : typeof value);

// 응답 값이 스키마에 맞지 않는 곳을 찾는다(최대 limit개). 빈 배열이면 통과다.
export function validateValue(value, schema, path = "$", problems = [], limit = 20) {
  if (problems.length >= limit) return problems;
  const types = Array.isArray(schema.type) ? schema.type : [schema.type];
  const actual = typeOf(value);
  if (!types.some((type) => type === actual || (type === "number" && actual === "integer"))) {
    problems.push(`${path}: ${types.join("|")} 형식이 아님`);
    return problems;
  }
  if (schema.enum && !schema.enum.includes(value)) problems.push(`${path}: 허용되지 않은 값`);
  if (actual === "object") {
    const properties = schema.properties ?? {};
    for (const name of schema.required ?? []) if (!(name in value)) problems.push(`${path}.${name}: 없음`);
    if (schema.additionalProperties === false) {
      for (const name of Object.keys(value)) if (!(name in properties)) problems.push(`${path}.${name}: 정의되지 않은 항목`);
    }
    for (const [name, child] of Object.entries(properties)) if (name in value) validateValue(value[name], child, `${path}.${name}`, problems, limit);
  }
  if (actual === "array") {
    if (schema.maxItems !== undefined && value.length > schema.maxItems) problems.push(`${path}: 항목 ${value.length}개(최대 ${schema.maxItems})`);
    if (schema.minItems !== undefined && value.length < schema.minItems) problems.push(`${path}: 항목 ${value.length}개(최소 ${schema.minItems})`);
    value.forEach((item, index) => validateValue(item, schema.items, `${path}[${index}]`, problems, limit));
  }
  return problems.slice(0, limit);
}
