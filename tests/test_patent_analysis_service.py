from src.retrieval.schemas import RetrievalResult, SearchDocument
from types import SimpleNamespace

from src.schemas import PatentComparison, PatentSearchRequest, StructuredIdea
from src.services.patent_service import analyze_patents


def request(top_k=5):
    return PatentSearchRequest(
        idea=StructuredIdea(
            title="비전 검사",
            problem="외관 결함 검사",
            technology="비전 카메라와 결함 분류",
            technical_components=["비전 카메라", "결함 분류"],
        ),
        top_k=top_k,
    )


def query_plan(system_prompt, user_text):
    return {
        "queries": [
            {
                "technical_element": "비전 검사",
                "korean_queries": ["비전 검사 장치"],
                "english_queries": ["visual inspection system"],
            }
        ]
    }


def result(patent_id, section="abstract", content="비전 검사 장치.", rank=1):
    return RetrievalResult(
        document=SearchDocument(
            chunk_id=f"{patent_id}_{section}_{rank}",
            source_id=patent_id,
            source_type="patent",
            title=f"특허 {patent_id}",
            content=content,
            metadata={
                "section": section,
                "application_number": patent_id,
                "publication_number": f"KR{rank:05d}A",
                "source_url": f"https://example.test/{patent_id}",
            },
        ),
        dense_score=0.9 - rank / 100,
        dense_rank=rank,
    )


def judge_all(idea, results):
    return {item.document.source_id: SimpleNamespace(relevant=True) for item in results}


def compare_all(idea, evidence):
    return [
        PatentComparison(
            citation_id=item.citation_id,
            technical_element="비전 검사",
            similarity="근거 문구 확인",
            difference="전체 구성은 미확인",
            uncertainty="원문 범위만 확인",
        )
        for item in evidence
    ]


def test_analysis_limits_to_five_patents_and_keeps_claim_citations(monkeypatch):
    import src.services.patent_service as service

    monkeypatch.setattr(service, "judge_patent_candidates", judge_all)
    monkeypatch.setattr(
        service,
        "search_patents",
        lambda query, **kwargs: [result(f"P{i}", rank=i) for i in range(1, 6)],
    )
    fetched = []

    def fetch_claims(application_number):
        fetched.append(application_number)
        return [
            {"claim_number": 1, "text": "비전 카메라를 포함하는 검사 장치."},
            {"claim_number": 2, "text": "제1항에 있어서, 결함을 분류하는 장치."},
        ]

    def compare(idea, evidence):
        return [
            PatentComparison(
                citation_id=item.citation_id,
                technical_element="비전 검사",
                similarity="인용된 청구항의 문구와 대조함",
                difference="확인된 문구 차이",
                uncertainty="제품 적용 및 법적 판단은 확인하지 않음",
            )
            for item in evidence
        ]

    report = analyze_patents(
        request(),
        collection=object(),
        query_llm_fn=query_plan,
        claim_fetcher=fetch_claims,
        kipris_search_fn=lambda query, limit: [],
        comparison_fn=compare,
    )

    assert report.status == "completed"
    assert len({item.patent_id for item in report.evidence}) == 5
    assert len(report.evidence) == 10
    assert all(
        item.section == "claims" and item.claim_number for item in report.evidence
    )
    assert [item.citation_id for item in report.comparisons] == list(range(1, 11))
    assert len(fetched) == 5


def test_indexed_candidate_fallback_uses_exact_abstract_and_marks_claim_unknown(
    monkeypatch,
):
    import src.services.patent_service as service

    monkeypatch.setattr(service, "judge_patent_candidates", judge_all)
    monkeypatch.setattr(
        service, "search_patents", lambda query, **kwargs: [result("P1")]
    )
    report = analyze_patents(
        request(top_k=1),
        collection=object(),
        query_llm_fn=query_plan,
        claim_fetcher=lambda application_number: [],
        kipris_search_fn=lambda query, limit: [],
        comparison_fn=compare_all,
    )

    assert report.status == "completed"
    assert report.evidence[0].section == "abstract"
    assert report.evidence[0].quote == "비전 검사 장치."
    assert any("청구항 원문 미확보" in item for item in report.unknowns)


def test_kipris_candidates_supplement_short_local_results(monkeypatch):
    import src.services.patent_service as service

    monkeypatch.setattr(service, "judge_patent_candidates", judge_all)
    monkeypatch.setattr(
        service, "search_patents", lambda query, **kwargs: [result("P1")]
    )
    calls = []

    def supplement(query, limit):
        calls.append((query, limit))
        return [
            {
                "application_number": "P2",
                "title": "보충 후보",
                "abstract": "검색어와 관련된 공개 초록",
                "publication_number": "KR12345A",
            }
        ]

    report = analyze_patents(
        request(top_k=2),
        collection=object(),
        query_llm_fn=query_plan,
        claim_fetcher=lambda application_number: [],
        kipris_search_fn=supplement,
        comparison_fn=compare_all,
    )

    assert len({item.patent_id for item in report.evidence}) == 2
    assert report.evidence[1].application_number == "P2"
    assert calls


def test_local_indexed_claim_metadata_is_preserved(monkeypatch):
    import src.services.patent_service as service

    monkeypatch.setattr(service, "judge_patent_candidates", judge_all)
    indexed = result(
        "P1", section="claims", content="제2항에 있어서, 카메라를 포함하는 장치."
    )
    indexed.document.metadata.update(
        claim_number=3,
        claim_type="dependent",
        depends_on="2",
        version_id="KR12345B1",
    )
    monkeypatch.setattr(service, "search_patents", lambda query, **kwargs: [indexed])
    report = analyze_patents(
        request(top_k=1),
        collection=object(),
        query_llm_fn=query_plan,
        claim_fetcher=lambda application_number: [],
        kipris_search_fn=lambda query, limit: [],
        comparison_fn=lambda idea, evidence: [
            PatentComparison(
                citation_id=evidence[0].citation_id,
                similarity="관련 표현이 확인됨",
                difference="전체 장치 구성은 추가 확인 필요",
                uncertainty="인용 문구 범위로만 비교함",
            )
        ],
    )

    assert report.evidence[0].claim_number == 3
    assert report.evidence[0].claim_type == "dependent"
    assert report.evidence[0].depends_on == [2]
    assert report.evidence[0].version_id == "KR12345B1"


def test_supplement_without_abstract_is_not_used_as_abstract_citation():
    from src.services.patent_service import _supplement_result

    assert (
        _supplement_result({"application_number": "P1", "title": "제목뿐인 특허"})
        is None
    )


def test_citation_validator_checks_original_quote():
    import pytest

    from src.services.patent_service import validate_patent_citations
    from src.schemas import PatentEvidence

    evidence = [
        PatentEvidence(
            citation_id=1,
            patent_id="P1",
            title="특허",
            section="abstract",
            quote="영상 결함을 검출한다.",
        )
    ]
    validate_patent_citations(evidence, {1: "요약\n영상   결함을 검출한다."})
    with pytest.raises(ValueError, match="does not match"):
        validate_patent_citations(evidence, {1: "다른 원문 내용"})


def test_comparison_failure_is_retried_once_and_reported(monkeypatch):
    import src.services.patent_service as service

    monkeypatch.setattr(service, "judge_patent_candidates", judge_all)
    monkeypatch.setattr(
        service, "search_patents", lambda query, **kwargs: [result("P1")]
    )
    attempts = []

    def fail(idea, evidence):
        attempts.append(1)
        raise RuntimeError("temporary failure")

    report = analyze_patents(
        request(top_k=1),
        query_llm_fn=query_plan,
        claim_fetcher=lambda _: [],
        kipris_search_fn=lambda *_: [],
        comparison_fn=fail,
    )

    assert report.status == "error"
    assert len(attempts) == 2
    assert report.evidence
