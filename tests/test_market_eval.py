import csv

import pytest

from evaluation.evaluate import (
    evaluate_market,
    hit_at_k,
    ndcg_at_k,
    precision_at_k,
    recall_at_k,
    reciprocal_rank,
    summarize,
)
from evaluation.market_labeling import (
    CSV_FIELDS,
    collect_candidates,
    export_candidates,
    import_labels,
    make_cases,
)

IDEAS = {
    "SF-01": {
        "idea_id": "SF-01",
        "idea": {
            "title": "협동로봇 턴키 자동화",
            "problem": "인력 부족",
            "technology": "협동로봇",
            "customers": "중소 제조사",
            "difference": "턴키",
            "revenue": "구독",
        },
    }
}


def fake_search(ranked_ids, texts=None):
    """질의와 관계없이 고정 순서의 결과를 돌려주는 가짜 검색."""
    texts = texts or {}

    def search(query, top_k, idea_id):
        return [
            {
                "source_id": sid,
                "text": texts.get(sid, f"{sid} 제목\n{sid} 요약"),
                "title": f"{sid} 제목",
                "url": f"https://example.com/{sid}",
                "published_at": 20261020,
                "distance": 0.1 * i,
            }
            for i, sid in enumerate(ranked_ids[:top_k])
        ]

    return search


def test_retrieval_metrics():
    retrieved = ["a", "b", "c", "d", "e", "f"]

    assert hit_at_k(retrieved, {"f"}) == 0.0
    assert hit_at_k(retrieved, {"c"}) == 1.0
    assert recall_at_k(retrieved, {"b", "c", "x", "y"}) == 0.5
    assert recall_at_k(retrieved, set()) == 0.0
    assert reciprocal_rank(retrieved, {"c", "e"}) == pytest.approx(1 / 3)
    assert reciprocal_rank(retrieved, {"f"}) == 0.0
    assert precision_at_k(retrieved, {"b", "c"}, 5) == pytest.approx(0.4)
    assert ndcg_at_k(retrieved, {"b", "c"}, 5) == pytest.approx(0.6934264036)


def test_make_cases_covers_all_dimensions():
    cases = make_cases(IDEAS)

    assert [c["case_id"] for c in cases] == [
        "SF-01-demand",
        "SF-01-competition",
        "SF-01-price",
        "SF-01-buyer",
        "SF-01-adoption_barrier",
    ]
    assert all(not c["labeled"] and c["relevant_source_ids"] == [] for c in cases)
    assert "협동로봇 턴키 자동화" in cases[2]["question"]


def test_collect_candidates_adds_term_matches_below_vector_pool():
    ids = [f"n{i:02d}" for i in range(20)]
    texts = {"n15": "협동로봇 가격 인하\n요약", "n17": "협동로봇 도입 비용 부담\n요약"}
    case = make_cases(IDEAS)[2]  # price

    candidates = collect_candidates(case, IDEAS, fake_search(ids, texts))

    assert [c["source_id"] for c in candidates if c["pool"] == "vector"] == ids[:8]
    assert [c["source_id"] for c in candidates if c["pool"] == "term"] == [
        "n15",
        "n17",
    ]


def label_csv(path, labels):
    """export한 CSV의 relevant 열을 {source_id: 값}으로 채운다."""
    with open(path, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    for row in rows:
        row["relevant"] = labels.get(row["source_id"], "")
    with open(path, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS)
        writer.writeheader()
        writer.writerows(rows)


def test_export_and_import_labels(tmp_path):
    cases = make_cases(IDEAS)[:1]
    path = tmp_path / "candidates.csv"
    count = export_candidates(cases, IDEAS, fake_search(["a", "b", "c"]), path)
    assert count == 3

    label_csv(path, {"a": "1", "b": "0"})
    updated, pending = import_labels(cases, path)
    assert pending == {"SF-01-demand": 1}
    assert updated[0]["labeled"] is False

    label_csv(path, {"a": "1", "b": "0", "c": "1"})
    updated, pending = import_labels(cases, path)
    assert pending == {}
    assert updated[0]["labeled"] is True
    assert updated[0]["relevant_source_ids"] == ["a", "c"]
    assert updated[0]["judged_source_ids"] == ["a", "b", "c"]


def test_import_labels_saved_by_excel_cp949(tmp_path):
    cases = make_cases(IDEAS)[:1]
    path = tmp_path / "candidates.csv"
    export_candidates(cases, IDEAS, fake_search(["a"]), path)
    label_csv(path, {"a": "1"})
    text = path.read_text(encoding="utf-8-sig")
    path.write_bytes(text.encode("cp949"))

    updated, _ = import_labels(cases, path)

    assert updated[0]["relevant_source_ids"] == ["a"]


def test_import_rejects_unknown_case(tmp_path):
    path = tmp_path / "candidates.csv"
    export_candidates(make_cases(IDEAS)[:1], IDEAS, fake_search(["a"]), path)

    with pytest.raises(ValueError):
        import_labels([], path)


def test_evaluate_market_and_summary():
    cases = make_cases(IDEAS)[:2]
    cases[0].update(
        labeled=True, relevant_source_ids=["b"], judged_source_ids=["a", "b"]
    )
    cases[1].update(labeled=True, relevant_source_ids=[], judged_source_ids=["a"])

    rows = evaluate_market(cases, IDEAS, fake_search(["a", "b", "x"]))
    summary = summarize(rows)

    assert rows[0]["rr"] == 0.5
    assert rows[0]["unjudged"] == 1
    assert rows[0]["precision"] == pytest.approx(1 / 3)
    assert rows[0]["ndcg"] == pytest.approx(0.6309297536)
    assert rows[1]["hit"] is None
    assert summary["all"]["no_relevant"] == 1
    assert summary["all"]["mrr"] == 0.5
    assert summary["competition"]["hit"] is None
