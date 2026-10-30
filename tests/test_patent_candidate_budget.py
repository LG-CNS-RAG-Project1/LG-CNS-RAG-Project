from evaluation.patent_candidate_budget import determine_label_source


def test_determine_label_source_identifies_ai_drafted_candidates():
    candidates = [
        {"note": "AI 초안(제목·초록 기준, 사람 검토 전)"},
        {"note": "AI 초안(제목·초록 기준, 사람 검토 전)"},
    ]

    assert determine_label_source(candidates) == "assistant_title_abstract_prelabel"


def test_determine_label_source_marks_mixed_candidate_notes():
    candidates = [
        {"note": "AI 초안(제목·초록 기준, 사람 검토 전)"},
        {"note": "사람이 원문 확인"},
    ]

    assert determine_label_source(candidates) == "mixed_or_partially_reviewed"
