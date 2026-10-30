from evaluation.patent_chunk_rerank_experiment import (
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
