from pathlib import Path

from src.generation.swot import (
    SwotAnalysis,
    build_swot,
    swot_markdown_lines,
    validate_items,
)
from src.schemas import (
    IdeaDraft,
    MarketReport,
    PatentabilityPrecheck,
    PatentEvidence,
    PatentReport,
)

ROOT = Path(__file__).resolve().parents[1]
MARKET = MarketReport.model_validate_json(
    (ROOT / "data/samples/market_reports/SF-04.json").read_text(encoding="utf-8")
)
PATENT = PatentReport(
    status="completed",
    search_scope="테스트 특허",
    evidence=[
        PatentEvidence(
            citation_id=1,
            patent_id="KR1",
            title="공장 전력 예측 장치",
            section="claims",
            quote="설비별 전력 사용량을 15분 단위로 예측하는 장치",
        )
    ],
    patentability_precheck=PatentabilityPrecheck(
        status="potentially_distinct",
        summary="공정 단위 절감 조치 제시는 검색 문헌에서 확인되지 않음",
        citation_ids=[1],
    ),
)
DRAFT = IdeaDraft(
    original_text="공정별 전력 FEMS",
    title="공정별 전력 FEMS",
    problem="전기료 부담",
    technology="공정별 전력 계측과 절감 조치 추천",
    customers="중소 제조사",
    difference="공정·설비 단위로 낭비 구간과 절감 조치를 제시한다",
    revenue="월 구독료",
    status="complete",
)
ALLOWED = {
    "M:1": "LS ELECTRIC, 에이스침대 공장에 FEMS 구축 2026",
    "P:1": "설비별 전력 사용량을 15분 단위로 예측",
    "T": "검색 관심도는 스마트공장 대비 유지입니다 (+3.7%).",
}


def test_validate_items_keeps_grounded_items_and_drops_invalid_ones():
    raw = [
        {
            "text": "실제 FEMS 구축 사례가 있다",
            "basis": "evidence",
            "citation_ids": ["M:1", "M:99"],
        },
        {"text": "근거 없는 확인 문장", "basis": "evidence", "citation_ids": ["M:99"]},
        {"text": "시장 규모는 3조원이다", "basis": "evidence", "citation_ids": ["M:1"]},
        {
            "text": "FEMS 수요가 확인되었다",
            "basis": "evidence",
            "citation_ids": ["M:1"],
        },
        {
            "text": "사용자는 월 구독료를 받는다고 밝혔다",
            "basis": "user_claim",
            "citation_ids": ["M:1"],
        },
        {
            "text": "검색 관심도가 +3.7%로 유지된다",
            "basis": "evidence",
            "citation_ids": ["T"],
        },
        {"text": "형식 오류", "basis": "fact"},
    ]

    kept, dropped = validate_items(raw, ALLOWED, "공정별 전력 FEMS 월 구독료")

    assert [k.text for k in kept] == [
        "실제 FEMS 구축 사례가 있다",
        "사용자는 월 구독료를 받는다고 밝혔다",
        "검색 관심도가 +3.7%로 유지된다",
    ]
    assert kept[0].citation_ids == ["M:1"]
    assert kept[1].citation_ids == []
    assert dropped == 4


def test_validate_items_rejects_contradictions_seen_in_real_runs():
    raw = [
        {
            "text": "FEMS 관련 공공 조달 공고가 많아 수요가 증가하고 있다",
            "basis": "evidence",
            "citation_ids": ["M:1"],
        },
        {
            "text": "검색 관심도가 최근 6개월 동안 상승세를 보이고 있다",
            "basis": "evidence",
            "citation_ids": ["T"],
        },
        {
            "text": "고객과 수익모델이 명확히 정의되지 않았다",
            "basis": "user_claim",
            "citation_ids": [],
        },
        {
            "text": "고객과 수익모델이 정해지지 않았다",
            "basis": "user_claim",
            "citation_ids": [],
        },
        {
            "text": "검색 관심도가 유지되고 있어 시장 수요가 안정적이다",
            "basis": "evidence",
            "citation_ids": ["T"],
        },
        {
            "text": "차별점 근거가 아직 없다",
            "basis": "ai_hypothesis",
            "citation_ids": [],
        },
        {
            "text": "검색 관심도는 기준 대비 유지되고 있다",
            "basis": "evidence",
            "citation_ids": ["T"],
        },
    ]

    kept, dropped = validate_items(
        raw, ALLOWED, "", trend_direction="stable", missing_fields={"difference"}
    )

    assert [k.text for k in kept] == [
        "차별점 근거가 아직 없다",
        "검색 관심도는 기준 대비 유지되고 있다",
    ]
    assert dropped == 5


def test_validate_items_caps_quadrant_at_three():
    raw = [
        {
            "text": f"가설 {chr(0xAC00 + i)}",
            "basis": "ai_hypothesis",
            "citation_ids": [],
        }
        for i in range(5)
    ]

    kept, dropped = validate_items(raw, ALLOWED, "")

    assert len(kept) == 3
    assert dropped == 2


def test_build_swot_sends_digest_and_validates_response():
    seen = {}

    def fake_llm(system_prompt, user_text):
        import json

        seen["payload"] = json.loads(user_text)
        return {
            "strengths": [
                {
                    "text": "공정 단위 절감 조치 제시는 검색 특허와 다를 수 있다",
                    "basis": "ai_hypothesis",
                    "citation_ids": ["P:1"],
                }
            ],
            "weaknesses": [],
            "opportunities": [
                {"text": "근거 없는 기회", "basis": "evidence", "citation_ids": []}
            ],
            "threats": [
                {
                    "text": "사용자는 중소 제조사를 고객으로 밝혔다",
                    "basis": "user_claim",
                    "citation_ids": [],
                }
            ],
        }

    swot = build_swot(DRAFT, PATENT, MARKET, fake_llm)

    payload = seen["payload"]
    assert payload["idea"]["difference"].startswith("공정·설비 단위")
    assert payload["patent"]["precheck"]["citation_ids"] == ["P:1"]
    assert payload["market"]["evidence"][0]["id"].startswith("M:")
    assert payload["market"]["search_trend"]["id"] == "T"
    assert swot.status == "completed"
    assert swot.strengths[0].citation_ids == ["P:1"]
    assert swot.opportunities == []
    assert swot.dropped == 1


def test_build_swot_skips_llm_when_both_reports_are_empty_and_reports_errors():
    def must_not_call(*args):
        raise AssertionError("LLM을 부르면 안 됨")

    empty = build_swot(
        DRAFT,
        PatentReport(status="error", search_scope="p"),
        MarketReport(status="no_results", search_scope="m"),
        must_not_call,
    )

    def broken(*args):
        raise RuntimeError("quota")

    failed = build_swot(DRAFT, PATENT, MARKET, broken)
    nothing = build_swot(DRAFT, PATENT, MARKET, lambda s, u: {"strengths": []})

    assert empty.status == "insufficient"
    assert failed.status == "error" and "quota" in failed.error_message
    assert nothing.status == "insufficient"


def test_swot_markdown_lines():
    swot = SwotAnalysis(
        status="completed",
        strengths=[
            {"text": "차별 구성 신호", "basis": "evidence", "citation_ids": ["P:1"]}
        ],
        threats=[{"text": "도입 비용 부담일 수 있다", "basis": "ai_hypothesis"}],
    )

    lines = "\n".join(swot_markdown_lines(swot))

    assert "## SWOT 분석 (예비)" in lines
    assert "- 차별 구성 신호 (근거 확인, P:1)" in lines
    assert "- 도입 비용 부담일 수 있다 (검증 전 가설)" in lines
    assert "**약점 (W)**\n- 확인된 항목 없음" in lines
    assert swot_markdown_lines(None) == []
    assert "만들지 못했습니다" in "\n".join(
        swot_markdown_lines(SwotAnalysis(status="error", error_message="quota"))
    )


def test_run_pipeline_attaches_swot_and_markdown():
    import src.pipeline as pipeline

    sources = pipeline.SourceAnalysis(
        patent=PATENT,
        market=MARKET,
        patent_run=pipeline.PartRun(state="completed", seconds=1.0),
        market_run=pipeline.PartRun(state="completed", seconds=2.0),
        analyzed_on=20261030,
        total_seconds=2.0,
    )
    swot_response = {
        "strengths": [
            {
                "text": "차별 구성 신호가 있다",
                "basis": "evidence",
                "citation_ids": ["P:1"],
            }
        ]
    }

    def fake_llm(system_prompt, user_text):
        if "SWOT" in system_prompt:
            return swot_response
        from tests.test_pipeline import link_response

        return link_response()

    result = pipeline.run_pipeline(
        DRAFT,
        [{"id": "Q1", "question": "검토 질문", "condition": ""}],
        sources=sources,
        link_llm_fn=fake_llm,
        swot_llm_fn=fake_llm,
    )
    without = pipeline.run_pipeline(
        DRAFT,
        [{"id": "Q1", "question": "검토 질문", "condition": ""}],
        sources=sources,
        link_llm_fn=fake_llm,
    )

    assert result.swot.status == "completed"
    assert "## SWOT 분석 (예비)" in result.markdown
    assert without.swot is None
    assert "SWOT" not in without.markdown
