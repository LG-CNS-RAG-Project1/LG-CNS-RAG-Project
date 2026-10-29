"""자료집 refresh·replay·review·reanalyze: 예산·호출 상한, 외부 호출 없는 재현, 버전·차이 분류."""

import json
import shutil
import subprocess
import sys

import pytest
import requests

from src.planner import config as planner_config
from src.planner import store
from src.planner.config import load_profile
from src.planner.report_text import semantic_to_markdown
from src.services import planner_service
from src.services.planner_service import load_inputs, reanalyze, refresh, replay, review
from tests.planner_fixtures import (
    FIXED_NOW,
    IDEA,
    WORLD,
    FakeHttp,
    FakeLLM,
    FakeSearch,
    source_id,
)


def fakes(world=WORLD):
    profile = load_profile("SF-02")
    mapping = {
        q.query: q.question_id for g in profile.initial_allocation for q in g.queries
    }
    return FakeSearch(world, mapping), FakeHttp(world), FakeLLM(world)


def run_refresh(root, parent=None, **kwargs):
    search, http, llm = fakes()
    path = refresh(
        IDEA,
        "SF-02",
        root=root,
        search_fn=search,
        http_get=http,
        llm_fn=llm,
        parent=parent,
        clock=lambda: FIXED_NOW,
        sleep=lambda seconds: None,
        **kwargs,
    )
    return path, search, http, llm


@pytest.fixture
def published(tmp_path):
    return run_refresh(tmp_path)


def test_refresh_publishes_run_within_budget_and_call_limits(published, tmp_path):
    path, search, http, llm = published
    report = replay(path)
    counts = report["semantic"].counts
    assert counts["retained_articles"] == len(WORLD) <= 80
    assert counts["body_status"] == {"http_403": 1, "http_4xx": 8, "ok": 2}
    log = store.read_json(path / "run_log.json")
    assert log["llm_calls"] == len(llm.calls) == len(WORLD) + 1
    assert log["llm_calls"] <= counts["retained_articles"] + 10
    assert log["search_requests"] == len(search.calls) <= 40
    assert counts["shortfalls"] and 1 <= counts["rounds"] <= 3
    picks = {q.question_id: q for q in report["semantic"].questions}
    assert all(p.stop_reason for p in picks.values() if p.status != "not_automated")
    assert picks["C3"].stop_reason == "no_new_evidence_within_capped_search"
    assert picks["M4"].stop_reason == "requires_company_input"
    assert sorted(p.name for p in (path / "bodies").iterdir()) == sorted(
        f"{source_id(k)}.txt" for k in ("A1", "A3")
    )
    assert not any(p.name.startswith(".staging") for p in tmp_path.iterdir())


def test_replay_matches_with_all_external_calls_blocked(published, monkeypatch):
    path = published[0]

    def blocked(*args, **kwargs):
        raise AssertionError("replay에서 외부 호출 금지")

    monkeypatch.setattr(requests.Session, "request", blocked)
    monkeypatch.setattr(requests, "get", blocked)
    import chromadb
    import openai

    monkeypatch.setattr(openai, "OpenAI", blocked)
    monkeypatch.setattr(chromadb, "HttpClient", blocked)
    monkeypatch.setattr(chromadb, "PersistentClient", blocked)
    report = replay(path)
    assert report["match"] and not report["rule_drift"]
    assert report["stored_hash"] == report["computed_hash"]


def test_replay_path_does_not_load_retrieval_or_chromadb(published):
    code = (
        "import sys; from pathlib import Path; "
        "from src.services.planner_service import replay; "
        "r = replay(Path(sys.argv[1])); "
        "bad = [m for m in sys.modules if m.startswith(('chromadb', 'src.retrieval', 'openai'))]; "
        "print(r['match'], bad)"
    )
    out = subprocess.run(
        [sys.executable, "-c", code, str(published[0])],
        capture_output=True,
        text=True,
        check=True,
    )
    assert out.stdout.strip() == "True []"


def test_semantic_hash_ignores_storage_order(published):
    path = published[0]
    inputs = load_inputs(path)
    payload, _, stored_hash = store.load_revision(path, 0)
    inputs["articles"] = list(reversed(inputs["articles"]))
    inputs["anchors"] = list(reversed(inputs["anchors"]))
    assert (
        store.semantic_hash(planner_service._recompute(inputs, payload)) == stored_hash
    )


def test_body_files_can_be_removed_without_breaking_replay(published):
    path = published[0]
    shutil.rmtree(path / "bodies")
    report = replay(path)
    assert report["match"] and len(report["missing_optional"]) == 2


def test_refresh_with_parent_reuses_cache_and_keeps_parent_intact(published, tmp_path):
    parent = published[0]
    before = (parent / "semantic" / "0000.json").read_bytes()
    child, _, _, llm = run_refresh(tmp_path, parent=parent)
    assert child != parent
    assert llm.calls == [source_id("A10"), source_id("A10")]
    store.verify_run(parent)
    assert (parent / "semantic" / "0000.json").read_bytes() == before
    manifest = store.read_json(child / "manifest.json")
    assert (
        manifest["parent_run_id"] == store.read_json(parent / "manifest.json")["run_id"]
    )
    diff = store.read_json(child / "diff.json")
    assert diff["categories"]["new_evidence"] == []
    assert diff["cell_changes"] == []
    assert replay(child)["match"]


def test_review_adds_revisions_without_rewriting_earlier_results(published):
    path = published[0]
    base = replay(path)["semantic"]
    target = next(
        e
        for e in base.evidence
        if e.kind == "claim"
        and e.source_id == source_id("A1")
        and "defect_data_preparation" in e.criteria
    )
    with pytest.raises(ValueError, match="사유"):
        review(
            path,
            [{"evidence_id": target.evidence_id, "decision": "reject", "reason": ""}],
        )
    rev, digest = review(
        path,
        [
            {
                "evidence_id": target.evidence_id,
                "decision": "reject",
                "reason": "문맥 확인",
            }
        ],
        clock=lambda: FIXED_NOW,
    )
    assert rev == 1 and replay(path, 1)["match"] and replay(path, 0)["match"]
    changed = replay(path, 1)["semantic"]
    assert changed.cells != base.cells

    price = {
        "values": {"C": "4000", "m": "0.3", "B": "3600", "I": "1000", "T": "24"},
        "provenance": {"C": {"source": "내부 원가", "note": "가상"}},
    }
    rev, _ = review(path, price=price, clock=lambda: FIXED_NOW)
    result = replay(path, rev)
    assert result["match"] and result["semantic"].price.status == "overlap"
    assert result["semantic"].price.provenance["C"]["source"] == "내부 원가"
    links = {a.assumption_id: a.status for a in result["semantic"].assumptions}
    assert links["A5"] == "supporting_evidence"
    assert len(result["revision_payload"]["reviews"]) == 1


def test_reanalyze_with_changed_profile_is_reported_as_rule_change(
    published, tmp_path, monkeypatch
):
    path = published[0]
    config_dir = tmp_path / "configs"
    shutil.copytree(planner_config.CONFIG_DIR, config_dir)
    profile_file = config_dir / "SF-02.yaml"
    profile_file.write_text(
        profile_file.read_text("utf-8").replace("티칭]", "티칭, 신제품 전환]"), "utf-8"
    )
    monkeypatch.setattr(planner_config, "CONFIG_DIR", config_dir)
    monkeypatch.setattr(
        planner_config, "QUESTION_BANK_PATH", config_dir / "question_bank.json"
    )

    old = replay(path)
    assert old["match"] and old["rule_drift"]
    child = reanalyze(path, root=tmp_path / "runs2", clock=lambda: FIXED_NOW)
    manifest = store.read_json(child / "manifest.json")
    assert manifest["mode"] == "reanalyze"
    assert json.loads((child / "run_log.json").read_text())["llm_calls"] == 0
    diff = store.read_json(child / "diff.json")
    assert {"profile_hash", "rule_version"} <= set(diff["version_changes"])
    assert replay(child)["match"]


def test_cancelled_refresh_publishes_nothing(tmp_path):
    calls = {"n": 0}

    def cancelled():
        calls["n"] += 1
        return calls["n"] > 30

    with pytest.raises(RuntimeError, match="취소"):
        run_refresh(tmp_path, cancelled=cancelled)
    assert store.list_runs(tmp_path) == []
    assert not any(p.name.startswith(".staging") for p in tmp_path.iterdir())


def test_text_report_uses_same_semantic_result(published):
    semantic = replay(published[0])["semantic"]
    text = semantic_to_markdown(semantic, "가상")
    assert "## 경쟁 주장 비교" in text and "## 사업 가정과 다음 확인" in text
    assert "계산 보류" in text and "5715" not in text
    assert "의미 검증과 다르며" in text


def test_parent_cache_revalidates_stored_raw_responses(tmp_path):
    parent = tmp_path / "parent"
    parent.mkdir()
    content = json.dumps(
        {
            "source_id": "news-x",
            "mentions": [
                {
                    "sentence_id": "s1",
                    "exact_text": "가상",
                    "candidate_role": "supplier",
                },
                {"sentence_id": "b99", "exact_text": "없음", "candidate_role": "other"},
            ],
            "claims": [],
            "relations": [],
            "metrics": [],
            "unresolved_fields": [],
        },
        ensure_ascii=False,
    )
    (parent / "extraction.jsonl").write_text(
        json.dumps(
            {
                "source_id": "news-x",
                "status": "failed",
                "cache_key": "k1",
                "input_sentence_ids": ["t1", "s1"],
                "error": "unknown_sentence_id",
            }
        )
        + "\n",
        "utf-8",
    )
    (parent / "llm_responses.jsonl").write_text(
        json.dumps({"cache_key": "k1", "content": content, "finish_reason": "stop"})
        + "\n",
        "utf-8",
    )
    cache = planner_service._parent_cache(parent)
    assert [m["exact_text"] for m in cache["k1"]["mentions"]] == ["가상"]
    assert cache["k1"]["dropped"][0]["sentence_id"] == "b99"
