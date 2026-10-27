from src.ingestion.news_client import load_keyword_config
from src.ingestion.patent_processor import load_technology_areas


def test_market_and_patent_loaders_share_one_technology_area_taxonomy():
    areas = load_technology_areas()
    market = load_keyword_config()

    assert set(areas) == {f"SF-{number:02d}" for number in range(1, 9)}
    assert areas["SF-05"]["name"] == "지능형 공정제어"
    assert areas["SF-05"]["technologies"] == ["공정 최적화", "자동제어"]
    assert all("idea_ids" in keyword for keyword in market["keywords"])
    assert len({keyword["id"] for keyword in market["keywords"]}) == len(
        market["keywords"]
    )


def test_market_loader_uses_process_control_terms_not_legacy_voice_terms():
    keywords = load_keyword_config()["keywords"]
    field_keywords = [
        keyword for keyword in keywords if keyword["idea_ids"] == ["SF-05"]
    ]
    field_queries = {keyword["query"] for keyword in field_keywords}

    assert "지능형 공정제어" in field_queries
    assert "제조 공정 최적화 자동제어" in field_queries
    assert "현장 작업자 AI 어시스턴트" not in field_queries
    assert "생산현장 음성 AI" not in field_queries
