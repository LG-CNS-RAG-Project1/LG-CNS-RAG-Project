"""Convert assessed market search results into traceable evidence records."""

from src.generation.market_claims import SIGNAL_ONLY_NATURES, _to_date
from src.schemas import ALL_DIMENSIONS, MarketEvidence

RECENT_DAYS = 365
STALE_DAYS = 3 * 365


def recency_grade(published_at: int, data_as_of: int) -> str:
    """기준일까지 경과 일수로 최신성 등급을 정한다 (1년 이내 high, 3년 이내 medium)."""
    days = (_to_date(data_as_of) - _to_date(published_at)).days
    if days <= RECENT_DAYS:
        return "high"
    return "medium" if days <= STALE_DAYS else "low"


def directness_grade(hit: dict, nature: str) -> str:
    """근거의 직접성 등급. 구매·지불 근거면 high, 관련성 판정 확신이 높으면 medium, 그 밖은 low."""
    if nature in ("direct_demand", "purchase_signal"):
        return "high"
    return "medium" if hit.get("relevance_confidence") == "high" else "low"


def source_natures(assessed: dict[str, dict]) -> dict[str, str]:
    """관련 기사별 근거 성격. 차원마다 판정이 다르면 confirmed를 열지 않는 쪽(약한 성격)을 쓴다."""
    natures: dict[str, str] = {}
    for result in assessed.values():
        if result["status"] == "error":
            continue
        for hit in result["hits"]:
            if not hit.get("relevant"):
                continue
            current = natures.get(hit["source_id"])
            if current is None or (
                current not in SIGNAL_ONLY_NATURES
                and hit["evidence_nature"] in SIGNAL_ONLY_NATURES
            ):
                natures[hit["source_id"]] = hit["evidence_nature"]
    return natures


def quote_text(hit: dict) -> str:
    """검색 결과 text(제목 + 줄바꿈 + 요약)에서 요약을 인용문으로 쓴다. 요약이 없으면 제목."""
    _, _, summary = hit["text"].partition("\n")
    return summary.strip() or hit["title"]


def build_evidence(
    assessed: dict[str, dict], data_as_of: int
) -> tuple[list[MarketEvidence], dict[str, list[int]]]:
    """관련 판정된 기사를 인용 근거로 만들고 차원별 citation_id 목록을 반환한다.

    같은 기사가 여러 차원에 나오면 citation_id 하나와 source_natures의 성격을 공유한다.
    판정 실패(error) 차원의 결과는 근거로 쓰지 않는다.
    """
    natures = source_natures(assessed)
    evidence: list[MarketEvidence] = []
    by_source: dict[str, int] = {}
    ids_by_dimension: dict[str, list[int]] = {}
    for dimension in ALL_DIMENSIONS:
        result = assessed.get(dimension)
        ids = []
        if result and result["status"] != "error":
            for hit in result["hits"]:
                if not hit.get("relevant"):
                    continue
                if hit["source_id"] not in by_source:
                    distance = hit.get("distance")
                    evidence.append(
                        MarketEvidence(
                            citation_id=len(evidence) + 1,
                            source_id=hit["source_id"],
                            source_type=hit["source_type"],
                            title=hit["title"],
                            publisher=hit["publisher"],
                            quote=quote_text(hit),
                            section=hit.get("section"),
                            url=hit.get("url"),
                            published_at=hit["published_at"],
                            period=hit.get("period"),
                            reliability=hit["reliability"],
                            recency=recency_grade(hit["published_at"], data_as_of),
                            directness=directness_grade(hit, natures[hit["source_id"]]),
                            evidence_nature=natures[hit["source_id"]],
                            similarity=(
                                None
                                if distance is None
                                else min(max(1 - distance, 0.0), 1.0)
                            ),
                        )
                    )
                    by_source[hit["source_id"]] = len(evidence)
                ids.append(by_source[hit["source_id"]])
        ids_by_dimension[dimension] = ids
    return evidence, ids_by_dimension
