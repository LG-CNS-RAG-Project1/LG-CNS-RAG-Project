import pytest

from frontend.swot_view import swot_item_caption
from src.generation.swot import SwotItem


@pytest.mark.parametrize("basis", ["evidence", "user_claim", "ai_hypothesis"])
def test_swot_item_caption_shows_basis_and_citations(basis):
    item = SwotItem(
        text="x", basis=basis, citation_ids=["M:1"] if basis != "user_claim" else []
    )

    caption = swot_item_caption(item)

    assert caption.startswith(
        {
            "evidence": "근거 확인",
            "user_claim": "사용자 주장",
            "ai_hypothesis": "검증 전 가설",
        }[basis]
    )
    assert ("M:1" in caption) == (basis != "user_claim")
