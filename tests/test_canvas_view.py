from frontend.canvas_view import BOTTOM_ROW, TOP_ROW, canvas_item_line
from src.generation.business_canvas import BLOCKS, CanvasItem


def test_canvas_item_line_escapes_text_and_grays_suffix():
    claim = CanvasItem(text="중소 제조사", basis="user_claim")
    guess = CanvasItem(text="SI 협력 [채널]", basis="ai_hypothesis", citation_ids=["F"])

    assert canvas_item_line(claim) == "- **중소 제조사**"
    assert canvas_item_line(guess) == "- **SI 협력 \\[채널\\]** :gray[가설 · F]"


def test_layout_places_every_block_once():
    placed = [name for names in TOP_ROW for name in names] + list(BOTTOM_ROW)

    assert sorted(placed) == sorted(BLOCKS)
