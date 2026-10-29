from frontend.market_trend_view import trend_rows
from src.schemas import MarketSearchTrend, MarketTrendPoint


def test_trend_rows_skip_months_without_reference():
    trend = MarketSearchTrend(
        status="completed",
        points=[
            MarketTrendPoint(
                period="2026-08", theme_ratio=0, reference_ratio=0, relative_index=None
            ),
            MarketTrendPoint(
                period="2026-09", theme_ratio=10, reference_ratio=25, relative_index=40
            ),
        ],
    )

    assert trend_rows(trend) == [{"월": "2026-09", "관심도 지수": 40.0}]
