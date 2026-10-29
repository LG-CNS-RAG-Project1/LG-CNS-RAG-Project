from evaluation.patent_review_context import build_review_context


def test_review_context_links_local_claims_and_keeps_labels_unchanged():
    candidates = [
        {
            "case_id": "Q1",
            "source_id": "P1",
            "title": "Local title",
            "summary": "Retrieved claim excerpt",
            "claim_number": "2",
            "relevant": "",
            "note": "",
        }
    ]
    patents = [
        {
            "application_number": "P1",
            "title": "Local title",
            "abstract": "Abstract text",
            "claim_items": [
                {"claim_number": 1, "text": "Base claim"},
                {"claim_number": 2, "text": "Dependent claim", "depends_on": [1]},
            ],
        }
    ]

    row = build_review_context(candidates, patents)[0]

    assert row["verification"]["application_number_matches_source_id"] is True
    assert row["verification"]["title_matches_local_record"] is True
    assert row["verification"]["candidate_claim_number_found"] is True
    assert row["claims"][1]["depends_on"] == [1]
    assert row["relevant"] == ""
    assert row["note"] == ""


def test_review_context_marks_missing_local_record_without_inventing_details():
    row = build_review_context(
        [
            {
                "case_id": "Q1",
                "source_id": "P-MISSING",
                "title": "Candidate title",
                "claim_number": "3",
                "url": "https://example.test/patent",
            }
        ],
        [],
    )[0]

    assert row["verification"]["local_record_found"] is False
    assert row["verification"]["title_matches_local_record"] is False
    assert row["verification"]["candidate_claim_number_found"] is False
    assert row["abstract"] == ""
    assert row["claims"] == []
