from frontend.market_network_view import cluster_label, network_rows
from src.generation.market_markdown import market_report_to_markdown
from src.schemas import (
    MarketKeywordEdge,
    MarketKeywordNetwork,
    MarketKeywordNode,
    MarketReport,
)

NETWORK = MarketKeywordNetwork(
    status="completed",
    document_count=100,
    nodes=[
        MarketKeywordNode(term="협동로봇", document_count=52, cluster=0, x=0.1, y=0.2),
        MarketKeywordNode(term="중소기업", document_count=25, cluster=0, x=-0.3, y=0.4),
        MarketKeywordNode(term="전기료", document_count=8, cluster=1, x=0.9, y=-0.5),
    ],
    edges=[
        MarketKeywordEdge(source="협동로봇", target="중소기업", weight=17),
        MarketKeywordEdge(source="협동로봇", target="없는명사", weight=3),
    ],
    clusters=[["협동로봇", "중소기업"], ["전기료"]],
    note="근거가 아닙니다.",
)


def test_network_rows_join_edge_coordinates_and_skip_unknown_terms():
    nodes, edges = network_rows(NETWORK)

    assert nodes[0] == {
        "명사": "협동로봇",
        "기사 수": 52,
        "묶음": "묶음 1 · 협동로봇·중소기업",
        "x": 0.1,
        "y": 0.2,
    }
    assert edges == [
        {
            "x": 0.1,
            "y": 0.2,
            "x2": -0.3,
            "y2": 0.4,
            "연결": "협동로봇 – 중소기업",
            "함께 나온 기사": 17,
        }
    ]


def test_cluster_label_folds_sixth_cluster_into_other():
    clusters = [[f"t{i}", f"u{i}"] for i in range(7)]

    assert cluster_label(4, clusters) == "묶음 5 · t4·u4"
    assert cluster_label(5, clusters) == "기타"


def test_markdown_lists_keyword_clusters():
    markdown = market_report_to_markdown(
        MarketReport(status="no_results", search_scope="범위", keyword_network=NETWORK)
    )

    assert "### 키워드 동시 출현" in markdown
    assert "뉴스 100건에서 두드러진 명사 3개가 2개 묶음" in markdown
    assert "- 묶음 1: 협동로봇 · 중소기업" in markdown
