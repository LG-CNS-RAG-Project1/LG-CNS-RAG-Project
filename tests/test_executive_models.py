from src.generation.executive_models import ExecutiveReview as ContractExecutiveReview
from src.generation.executive_review import ExecutiveReview
from src.pipeline_models import PipelineReport


def test_executive_review_contract_has_compatibility_import():
    assert ExecutiveReview is ContractExecutiveReview
    assert PipelineReport.model_fields["executive_review"].annotation == (
        ContractExecutiveReview | None
    )
