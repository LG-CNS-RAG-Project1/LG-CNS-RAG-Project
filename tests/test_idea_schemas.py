from src.idea_schemas import IdeaDraft, StructuredIdea
from src.schemas import IdeaDraft as CompatibilityIdeaDraft
from src.schemas import StructuredIdea as CompatibilityStructuredIdea


def test_idea_models_keep_compatibility_imports():
    assert CompatibilityIdeaDraft is IdeaDraft
    assert CompatibilityStructuredIdea is StructuredIdea


def test_complete_draft_converts_to_shared_analysis_input():
    draft = IdeaDraft(
        original_text="공장 진동을 분석한다",
        title="설비 이상 감지",
        problem="고장을 늦게 발견한다",
        technology="진동 신호 분석",
        customers="제조 공장",
        difference="기존 센서에 소프트웨어를 추가한다",
        revenue="월 구독료",
        status="complete",
    )

    idea = draft.to_structured_idea()

    assert idea.title == draft.title
    assert idea.technology == draft.technology
    assert isinstance(idea, StructuredIdea)
