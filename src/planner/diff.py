"""두 실행(또는 두 revision)의 의미 결과 차이를 원인별로 나눈다.

- new_evidence: 새 기사에서 온 승인 근거
- removed_or_fetch_failed: 이전 기사가 빠졌거나 본문 수집이 실패로 바뀜
- judgment_changed: 같은 기사에서 판정(승인·상태)이 달라짐
- user_input_changed: 아이디어 입력·검토·가격 입력이 달라짐
- rule_changed: 규칙·추출기·프롬프트·프로필 버전이 달라짐
공급사 기능이 실제로 바뀐 것과 이번에 설명을 새로 찾은 것은 구분하지 않으므로 '시장 변화'로 표시하지 않는다.
"""

from src.planner.schemas import SemanticResult

VERSION_KEYS = (
    "rule_version",
    "extractor_version",
    "prompt_hash",
    "schema_hash",
    "profile_hash",
    "question_bank",
    "calc_version",
)


def diff_results(
    old: SemanticResult,
    new: SemanticResult,
    old_inputs: dict | None = None,
    new_inputs: dict | None = None,
) -> dict:
    old_sources = {s["source_id"]: s for s in old.sources}
    new_sources = {s["source_id"]: s for s in new.sources}
    added = sorted(set(new_sources) - set(old_sources))
    removed = sorted(set(old_sources) - set(new_sources))
    body_lost = sorted(
        sid
        for sid in set(old_sources) & set(new_sources)
        if old_sources[sid]["body_status"] == "ok"
        and new_sources[sid]["body_status"] != "ok"
    )
    version_changes = {
        key: {"from": old.versions.get(key, ""), "to": new.versions.get(key, "")}
        for key in VERSION_KEYS
        if old.versions.get(key, "") != new.versions.get(key, "")
    }
    input_changed = old.idea_hash != new.idea_hash or (old_inputs or {}) != (
        new_inputs or {}
    )
    old_evidence = {e.evidence_id: e for e in old.evidence}
    new_evidence = {e.evidence_id: e for e in new.evidence}
    judgment = sorted(
        eid
        for eid in set(old_evidence) & set(new_evidence)
        if old_evidence[eid].review_status != new_evidence[eid].review_status
        or old_evidence[eid].criteria != new_evidence[eid].criteria
    )
    fresh = sorted(
        e.evidence_id
        for e in new.evidence
        if e.source_id in added and e.review_status == "approved"
    )
    old_cells = {(c.row_id, c.criterion_id): c for c in old.cells}
    cell_changes = []
    for cell in new.cells:
        before = old_cells.get((cell.row_id, cell.criterion_id))
        if before is None or before.status == cell.status:
            continue
        sources = set(cell.supporting_source_ids + cell.conflicting_source_ids)
        sources |= set(before.supporting_source_ids + before.conflicting_source_ids)
        if version_changes:
            cause = "rule_changed"
        elif sources & set(added):
            cause = "new_evidence"
        elif sources & (set(removed) | set(body_lost)):
            cause = "removed_or_fetch_failed"
        elif input_changed:
            cause = "user_input_changed"
        else:
            cause = "judgment_changed"
        cell_changes.append(
            {
                "row_id": cell.row_id,
                "criterion_id": cell.criterion_id,
                "from": before.status,
                "to": cell.status,
                "cause": cause,
            }
        )
    return {
        "categories": {
            "new_evidence": fresh,
            "removed_or_fetch_failed": removed + body_lost,
            "judgment_changed": judgment,
            "user_input_changed": input_changed,
            "rule_changed": sorted(version_changes),
        },
        "version_changes": version_changes,
        "added_sources": added,
        "cell_changes": cell_changes,
    }
