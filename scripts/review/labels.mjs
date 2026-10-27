// PR 분석 보고서의 화면 라벨이다. 내부 값(영문)은 이 표를 거쳐 한국어로만 화면에 나온다.

export const LABELS = {
  readiness: {
    draft: "⚪ 초안", needs_fix: "🟠 보완 후 검토", discuss: "🔵 함께 논의",
    leader_look: "🟡 리더가 한 번 보기", ready: "🟢 검토 준비됨",
  },
  severity: { blocker: "꼭 고칠 점", major: "중요", minor: "작은 개선", info: "참고" },
  category: {
    bug: "버그 가능성", data_contract: "데이터 규칙과 다른 점", security: "보안", test_gap: "테스트 부족",
    performance: "성능", docs: "문서", other: "기타",
  },
  basis: { fact: "[확인됨]", interpretation: "[AI 판단]", assumption: "[추정]", unverified: "[확인 못 함]" },
  confidence: { high: "높음", medium: "보통", low: "낮음" },
  goal: {
    aligned: "목표와 맞음", partial: "일부 목표와 맞음", unclear: "판단 어려움(정보 부족)",
    misaligned: "목표 연결 확인 필요", no_baseline: "기준 없음(판단 보류)",
  },
  module: {
    within_role: "담당 영역 안", cross_boundary_ok: "다른 영역도 수정(문제 없음)",
    cross_boundary_unagreed: "다른 담당 영역 수정(사전 합의 확인 필요)", unclear: "판단 어려움", no_role_data: "역할 기준 없음",
  },
  impact: {
    none: "다른 부분 영향 없음", additive: "기능 추가(기존 연결 유지)",
    breaking: "다른 부분도 함께 고쳐야 할 수 있음", unclear: "영향 판단 어려움",
  },
  ci: {
    passed: "✅ 통과", failed: "❌ 실패(내 변경)", running: "⏳ 검사 중", conflict_no_ci: "⚠️ 충돌로 검사 안 돎",
    rules_changed: "⚠️ 검사 규칙이 바뀜", none: "– 검사 없음", undetermined: "⏳ 미확정",
  },
  // 행동 문구(다음에 할 일)에 쓰는 규칙 이름
  rule: {
    template: "PR 설명 빈칸", check_mismatch: "체크 표시와 결과 다름", AGENTS_4_docs: "문서 업데이트 확인",
    AGENTS_5_secrets: "보안 확인 필요", AGENTS_6_comments: "주석 규칙 확인", AGENTS_2_scope: "작업 나누기 검토",
    branch_name: "브랜치 이름 규칙", AGENTS_8_commits: "커밋 형식 확인",
  },
  // 점검표의 중립 항목 이름
  check: {
    template: "PR 설명 양식", check_mismatch: "체크 표시와 검사 결과", AGENTS_4_docs: "문서 업데이트",
    AGENTS_5_secrets: "비밀값", AGENTS_6_comments: "주석 규칙", AGENTS_2_scope: "작업 범위",
    branch_name: "브랜치 이름", AGENTS_8_commits: "커밋 형식",
  },
  job: {
    "Black format check": "코드 모양(Black)", Pytest: "테스트(Pytest)",
    "Automation script tests": "자동화 스크립트 테스트", "Docker build": "Docker 빌드",
  },
  conclusion: {
    success: "통과", failure: "실패", cancelled: "취소", skipped: "건너뜀", in_progress: "진행 중", missing: "없음",
    neutral: "중립", timed_out: "시간 초과", action_required: "조치 필요",
  },
  status: { ok: "✅ 문제 없음", warn: "⚠️ 확인해 주세요", fail: "❌ 보완 필요", "n/a": "– 해당 없음" },
  mode: { full: "처음부터 전체 분석", incremental: "바뀐 부분만", none: "코드 변경 없음(지난 결과 유지)", deterministic: "자동 규칙 점검만" },
  analysis: {
    done: "AI 분석 완료", partial: "AI 분석 완료(일부 범위)", reused: "AI 결과 유지(코드 변경 없음)", failed: "AI 분석 실패", skipped: "AI 분석 안 함",
  },
  // AI 호출 실패 분류(공식 오류 형태 기준)
  error: {
    auth: "인증 오류(리더 확인 필요)", model_access: "모델 접근 불가", quota: "사용·결제 한도 초과", rate_limit: "속도 제한",
    server: "OpenAI 서버 오류", timeout: "시간 초과", network: "연결 오류", invalid_request: "요청 형식 오류",
    incomplete: "응답 미완료(출력 한도)", refusal: "모델 거절", schema: "출력 형식 검증 실패", model_mismatch: "응답 모델 불일치",
  },
  // AI를 부르지 않은 이유
  skip: {
    draft: "초안", same_head: "같은 버전 이미 분석", no_change: "의미 있는 변경 없음", llm_disabled: "AI 분석 꺼짐(REVIEW_LLM_ENABLED)",
    no_key: "API 키 없음(OPENAI_API_KEY)", config: "지원하지 않는 제공자·모델 설정", actor: "수동 실행 권한 없음",
    secret: "비밀값 의심으로 생략", cooldown: "OpenAI 한도로 잠시 멈춤", retry_limit: "같은 버전 2회 실패로 자동 중단",
  },
  owner: { author: "작성자", leader: "리더", team: "팀" },
  prState: { open: "열림", draft: "초안", merged: "병합", closed: "닫힘" },
  record: { latest: "최신", previous: "이전 분석" },
  verdict: { merge_ok: "병합 가능", fix_then_merge: "보완 후 병합", discuss: "논의 후 결정", hold: "판단 보류" },
};
