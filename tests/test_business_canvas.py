import json

from src.generation.business_canvas import (
    BLOCKS,
    BusinessCanvas,
    build_business_canvas,
    canvas_markdown_lines,
    item_suffix,
    validate_canvas_items,
)
from src.schemas import ImplementationCostEstimate, ImplementationCostItem
from tests.test_swot import DRAFT, MARKET, PATENT

COST = ImplementationCostEstimate(
    status="estimated",
    items=[
        ImplementationCostItem(
            name="CT 센서 계측기",
            quantity=10,
            unit="대",
            low_unit_cost=200000,
            base_unit_cost=300000,
            high_unit_cost=400000,
            basis="견적 가정",
        )
    ],
)


def test_validate_canvas_items_keeps_title_when_only_detail_fails():
    allowed = {"M:11": "FEMS 입찰공고 40건 예산 중앙값 5,058만원"}
    raw = [
        {
            "text": "공공 조달",
            "detail": "FEMS 입찰공고 40건이 있어 공공기관 영업 경로가 될 수 있다.",
            "basis": "evidence",
            "citation_ids": ["M:11"],
        },
        {
            "text": "직접 영업",
            "detail": "연 매출 100억 원 이하 부품사를 겨냥할 수 있다.",
            "basis": "ai_hypothesis",
        },
        {
            "text": "CT 전류 센서",
            "detail": "전력 계측을 위한 CT 전류 센서가 필수적이다.",
            "basis": "user_claim",
        },
        {"text": "센서 공급사", "detail": "x" * 200, "basis": "ai_hypothesis"},
        {"text": "시장 수요 확인", "detail": "", "basis": "ai_hypothesis"},
    ]

    kept, dropped = validate_canvas_items(raw, allowed, "CT 전류 센서")

    assert [(k.text, bool(k.detail)) for k in kept] == [
        ("공공 조달", True),
        ("직접 영업", False),
        ("CT 전류 센서", False),
    ]
    assert dropped == 2


def test_build_canvas_sends_components_and_cost_and_validates_blocks():
    seen = {}

    def fake_llm(system_prompt, user_text):
        seen["payload"] = json.loads(user_text)
        return {
            "customer_segments": [
                {"text": "중소 제조사", "basis": "user_claim", "citation_ids": ["M:1"]}
            ],
            "value_propositions": [
                {
                    "text": "공정 단위 절감 조치 제시",
                    "basis": "evidence",
                    "citation_ids": ["P:1"],
                },
                {"text": "근거 없는 확인", "basis": "evidence", "citation_ids": []},
            ],
            "channels": [
                {
                    "text": "CT 센서 설치 협력사 경유 영업",
                    "basis": "ai_hypothesis",
                    "citation_ids": [],
                }
            ],
            "cost_structure": [
                {
                    "text": "CT 센서 계측기 300만원",
                    "basis": "evidence",
                    "citation_ids": ["C"],
                },
                {"text": "설치비 0만원", "basis": "ai_hypothesis", "citation_ids": []},
            ],
            "revenue_streams": [
                {
                    "text": "FEMS 수요가 확인된 월 구독료",
                    "basis": "user_claim",
                    "citation_ids": [],
                }
            ],
        }

    canvas = build_business_canvas(
        DRAFT,
        PATENT,
        MARKET,
        fake_llm,
        cost_estimate=COST,
        technical_components=["CT 센서 계측기"],
    )

    payload = seen["payload"]
    assert payload["idea"]["technical_components"] == ["CT 센서 계측기"]
    assert payload["cost_estimate"]["id"] == "C"
    assert payload["cost_estimate"]["items"][0]["base_total_manwon"] == 300
    assert canvas.status == "completed"
    assert canvas.customer_segments[0].citation_ids == []
    assert [i.text for i in canvas.value_propositions] == ["공정 단위 절감 조치 제시"]
    # 비용 추정(C)만 인용한 항목은 가설로 바뀌고, 없는 금액은 버린다
    assert [(i.text, i.basis) for i in canvas.cost_structure] == [
        ("CT 센서 계측기 300만원", "ai_hypothesis")
    ]
    assert canvas.revenue_streams == []
    assert canvas.key_partners == []
    assert canvas.dropped == 3


def test_build_canvas_without_cost_estimate_and_failures():
    seen = {}

    def fake_llm(system_prompt, user_text):
        seen["payload"] = json.loads(user_text)
        return {"key_partners": []}

    def broken(*args):
        raise RuntimeError("quota")

    empty = build_business_canvas(DRAFT, PATENT, MARKET, fake_llm)
    failed = build_business_canvas(DRAFT, PATENT, MARKET, broken)
    not_dict = build_business_canvas(DRAFT, PATENT, MARKET, lambda s, u: [])

    assert seen["payload"]["cost_estimate"] is None
    assert empty.status == "insufficient"
    assert failed.status == "error" and "quota" in failed.error_message
    assert not_dict.status == "error"


def test_item_suffix_hides_user_claims():
    canvas = BusinessCanvas(
        status="completed",
        customer_segments=[{"text": "중소 제조사", "basis": "user_claim"}],
        revenue_streams=[
            {"text": "조달 공고", "basis": "evidence", "citation_ids": ["M:11"]}
        ],
        channels=[{"text": "SI 협력", "basis": "ai_hypothesis", "citation_ids": ["F"]}],
        key_partners=[{"text": "센서 공급사", "basis": "ai_hypothesis"}],
    )

    assert item_suffix(canvas.customer_segments[0]) == ""
    assert item_suffix(canvas.revenue_streams[0]) == "M:11"
    assert item_suffix(canvas.channels[0]) == "가설 · F"
    assert item_suffix(canvas.key_partners[0]) == "가설"


def test_canvas_markdown_lines():
    canvas = BusinessCanvas(
        status="completed",
        customer_segments=[{"text": "중소 제조사", "basis": "user_claim"}],
        channels=[
            {
                "text": "직접 영업",
                "detail": "생산기술팀에 데모를 보여 줄 수 있다.",
                "basis": "ai_hypothesis",
            },
            {"text": "공공 조달", "basis": "evidence", "citation_ids": ["M:11"]},
        ],
    )

    lines = "\n".join(canvas_markdown_lines(canvas))

    assert "## 비즈니스 모델 캔버스 (예비)" in lines
    assert "| 고객 세그먼트 | **중소 제조사** |" in lines
    assert (
        "| 채널 | **직접 영업** — 생산기술팀에 데모를 보여 줄 수 있다. (가설)"
        "<br>**공공 조달** (M:11) |"
    ) in lines
    assert "| 핵심 파트너 | - |" in lines
    assert lines.count("\n| ") == len(BLOCKS) + 1
    assert canvas_markdown_lines(None) == []
    assert "만들지 못했습니다" in "\n".join(
        canvas_markdown_lines(BusinessCanvas(status="error", error_message="quota"))
    )


def test_run_pipeline_attaches_canvas_with_screen_components():
    import src.pipeline as pipeline

    sources = pipeline.SourceAnalysis(
        patent=PATENT,
        market=MARKET,
        patent_run=pipeline.PartRun(state="completed", seconds=1.0),
        market_run=pipeline.PartRun(state="completed", seconds=2.0),
        analyzed_on=20261030,
        total_seconds=2.0,
    )
    seen = {}

    def fake_llm(system_prompt, user_text):
        if "비즈니스 모델 캔버스" in system_prompt:
            seen["payload"] = json.loads(user_text)
            return {
                "channels": [{"text": "센서 협력사 경유", "basis": "ai_hypothesis"}]
            }
        from tests.test_pipeline import link_response

        return link_response()

    result = pipeline.run_pipeline(
        DRAFT,
        [{"id": "Q1", "question": "검토 질문", "condition": ""}],
        technical_components=["CT 센서"],
        sources=sources,
        link_llm_fn=fake_llm,
        canvas_llm_fn=fake_llm,
    )
    without = pipeline.run_pipeline(
        DRAFT,
        [{"id": "Q1", "question": "검토 질문", "condition": ""}],
        sources=sources,
        link_llm_fn=fake_llm,
    )

    assert seen["payload"]["idea"]["technical_components"] == ["CT 센서"]
    assert result.canvas.status == "completed"
    assert "## 비즈니스 모델 캔버스 (예비)" in result.markdown
    assert without.canvas is None
    assert "비즈니스 모델 캔버스" not in without.markdown
