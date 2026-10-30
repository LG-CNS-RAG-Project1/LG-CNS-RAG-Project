from evaluation.patent_chunk_rerank_experiment import (
    build_experiment_chunks,
    corpus_fingerprint,
    corpus_inventory,
)
from src.schemas import PatentClaim, PatentDocument


def sample_patent():
    return PatentDocument(
        patent_id="P-1",
        application_number="P-1",
        title="공정 제어 장치",
        abstract="공정 데이터를 이용해 제어 조건을 조정한다.",
        claims="독립항 원문 종속항 원문",
        claim_items=[
            PatentClaim(
                claim_number=1,
                text="공정 제어 장치.",
                claim_type="independent",
                version_id="V1",
            ),
            PatentClaim(
                claim_number=2,
                text="제1항에 있어서 센서를 포함하는 장치.",
                claim_type="dependent",
                depends_on=[1],
                version_id="V1",
            ),
        ],
        claim_version_id="V1",
        publication_number="PUB-1",
        technology_area_ids=["SF-05"],
    )


def test_inventory_tracks_claim_coverage_and_reproducible_fingerprint():
    patents = [sample_patent()]

    inventory = corpus_inventory(patents)

    assert inventory["areas"]["SF-05"]["patent_count"] == 1
    assert inventory["areas"]["SF-05"]["independent_claim_count"] == 1
    assert inventory["areas"]["SF-05"]["dependent_claim_count"] == 1
    assert inventory["areas"]["SF-02"]["patent_count"] == 0
    assert corpus_fingerprint(patents) == corpus_fingerprint(patents)


def test_independent_strategy_keeps_abstract_and_only_independent_claims():
    chunks = build_experiment_chunks([sample_patent()], "SF-05", "independent")

    assert [chunk.section for chunk in chunks] == ["abstract", "claims"]
    assert chunks[-1].claim_number == 1
    assert chunks[-1].claim_type == "independent"


def test_parent_context_adds_exact_ancestor_text_and_preserves_claim_metadata():
    chunks = build_experiment_chunks([sample_patent()], "SF-05", "parent_context")
    dependent = next(chunk for chunk in chunks if chunk.claim_number == 2)

    assert "상위 청구항 1 원문: 공정 제어 장치." in dependent.text
    assert "현재 청구항 2 원문: 제1항에 있어서 센서를 포함하는 장치." in dependent.text
    assert dependent.depends_on == [1]
    assert dependent.version_id == "V1"


def test_parent_context_ignores_missing_and_cyclic_dependency_references():
    patent = sample_patent()
    patent.claim_items[0].depends_on = [2, 99]
    chunks = build_experiment_chunks([patent], "SF-05", "parent_context")

    assert len(chunks) == 3
