from src.services.patent_context import (
    _build_patent_context as context_builder,
    _estimate_text_tokens as token_estimator,
    _select_claims as claim_selector,
)
from src.services.patent_service import (
    _build_patent_context,
    _estimate_text_tokens,
    _select_claims,
)


def test_patent_service_reexports_context_helpers():
    assert _build_patent_context is context_builder
    assert _estimate_text_tokens is token_estimator
    assert _select_claims is claim_selector
