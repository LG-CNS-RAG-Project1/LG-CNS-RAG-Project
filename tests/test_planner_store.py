"""사업기획 근거 자료집 저장소: 덮어쓰기 금지·해시 대조·정규 직렬화."""

from decimal import Decimal

import pytest

from src.planner.schemas import RunManifest
from src.planner.store import (
    RunIntegrityError,
    Staging,
    canonical_json,
    find_run,
    idea_hash,
    latest_revision,
    list_runs,
    load_revision,
    semantic_hash,
    verify_run,
    write_semantic,
)
from src.schemas import StructuredIdea


def idea():
    return StructuredIdea(title="가상 검사", problem="문제", technology="AI 비전")


def manifest(run_id="20261029-aaaa0001", digest="d" * 64):
    return RunManifest(
        run_id=run_id,
        mode="refresh",
        idea_hash=digest,
        area_id="SF-02",
        idea_title="가상 검사",
        as_of=run_id[:8],
        versions={"rule_version": "r1"},
        budget={"max_articles": 80},
    )


def publish(root, run_id="20261029-aaaa0001", digest="d" * 64):
    staging = Staging(root, "SF-02", digest, run_id)
    for name in [
        "idea.json",
        "profile.json",
        "question_bank.json",
        "query_plan.json",
        "selection.json",
    ]:
        staging.write_json(name, {"name": name})
    for name in ["articles.jsonl", "extraction.jsonl", "anchors.jsonl"]:
        staging.write_jsonl(name, [{"b": 2, "a": 1}])
    staging.write_text("bodies/news-1.txt", "본문")
    write_semantic(staging, 0, {"revision": 0}, {"x": 1})
    return staging.publish(manifest(run_id, digest))


def test_canonical_json_is_order_independent_and_keeps_decimal_as_fixed_text():
    a = canonical_json({"b": Decimal("5714.285714"), "a": [1, 2]})
    b = canonical_json({"a": [1, 2], "b": Decimal("5714.285714")})
    assert a == b
    assert b'"5714.285714"' in a
    assert semantic_hash({"k": "값"}) == semantic_hash({"k": "값"})


def test_idea_hash_changes_with_area_and_idea_fields():
    base = idea_hash(idea(), "SF-02")
    assert base == idea_hash(idea(), "SF-02")
    assert base != idea_hash(idea(), "SF-05")
    changed = idea().model_copy(update={"difference": "다른 차별점"})
    assert base != idea_hash(changed, "SF-02")


def test_staging_never_overwrites_files_or_published_runs(tmp_path):
    staging = Staging(tmp_path, "SF-02", "d" * 64, "20261029-dup00001")
    staging.write_json("idea.json", {"a": 1})
    with pytest.raises(FileExistsError):
        staging.write_json("idea.json", {"a": 2})
    staging.discard()

    path = publish(tmp_path)
    assert (path / "manifest.json").exists()
    with pytest.raises(FileExistsError):
        Staging(tmp_path, "SF-02", "d" * 64, "20261029-aaaa0001")


def test_verify_detects_tampering_and_tolerates_removed_bodies(tmp_path):
    path = publish(tmp_path)
    assert verify_run(path)["missing_optional"] == []

    (path / "bodies" / "news-1.txt").unlink()
    assert verify_run(path)["missing_optional"] == ["bodies/news-1.txt"]

    (path / "selection.json").write_text('{"changed": true}', encoding="utf-8")
    with pytest.raises(RunIntegrityError, match="selection.json"):
        verify_run(path)


def test_missing_required_file_is_an_integrity_error(tmp_path):
    path = publish(tmp_path)
    (path / "anchors.jsonl").unlink()
    with pytest.raises(RunIntegrityError, match="anchors.jsonl"):
        verify_run(path)


def test_revisions_are_append_only_and_self_hashed(tmp_path):
    path = publish(tmp_path)
    digest = write_semantic(path, 1, {"revision": 1, "reviews": []}, {"x": 2})
    assert latest_revision(path) == 1
    payload, semantic, stored = load_revision(path, 1)
    assert payload["revision"] == 1 and semantic == {"x": 2} and stored == digest
    with pytest.raises(FileExistsError):
        write_semantic(path, 1, {"revision": 1}, {"x": 3})

    (path / "revisions" / "0001.json").write_text('{"revision": 9}', "utf-8")
    with pytest.raises(RunIntegrityError):
        load_revision(path, 1)


def test_list_runs_skips_staging_and_sorts_latest_first(tmp_path):
    publish(tmp_path, "20261029-aaaa0001")
    publish(tmp_path, "20261030-bbbb0002")
    publish(tmp_path, "20261029-0000zzzz")
    later = tmp_path / "SF-02" / ("d" * 12) / "20261029-0000zzzz" / "manifest.json"
    import os

    os.utime(later, (later.stat().st_atime, later.stat().st_mtime + 10))
    Staging(tmp_path, "SF-02", "d" * 64, "20261031-cccc0003")
    runs = list_runs(tmp_path, "SF-02")
    assert [r["manifest"].run_id for r in runs] == [
        "20261030-bbbb0002",
        "20261029-0000zzzz",
        "20261029-aaaa0001",
    ]
    assert find_run(tmp_path, "20261029-aaaa0001") == runs[2]["path"]
    assert list_runs(tmp_path / "missing") == []
