from types import SimpleNamespace

import pytest

from src.retrieval.patent_relevance import judge_patent_candidates
from src.retrieval.schemas import SearchDocument
from src.schemas import StructuredIdea


def candidate(source_id="P1"):
    return SimpleNamespace(
        document=SearchDocument(
            chunk_id=f"{source_id}_abstract_0",
            source_id=source_id,
            source_type="patent",
            title="비전 검사 특허",
            content="영상으로 결함을 검출하는 장치.",
            metadata={"section": "abstract"},
        )
    )


def idea():
    return StructuredIdea(
        title="검사",
        problem="불량 검사",
        technology="비전 검사",
    )


def test_judges_every_document_once():
    calls = []

    def llm(prompt, user_text):
        calls.append((prompt, user_text))
        return {
            "judgments": [
                {
                    "source_id": "P1",
                    "relevant": True,
                    "confidence": "high",
                    "reason": "영상 결함 검출 구성이 있음",
                }
            ]
        }

    result = judge_patent_candidates(idea(), [candidate()], llm)

    assert result["P1"].relevant is True
    assert calls and "candidates" in calls[0][1]


def test_relevance_judgment_must_cover_all_candidates():
    with pytest.raises(ValueError, match="one-to-one"):
        judge_patent_candidates(
            idea(),
            [candidate("P1"), candidate("P2")],
            lambda *_: {
                "judgments": [
                    {
                        "source_id": "P1",
                        "relevant": True,
                        "confidence": "high",
                        "reason": "기술 구성 일치",
                    }
                ]
            },
        )
