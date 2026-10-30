"""아이디어와 가까운 뉴스에서 키워드 동시 출현 네트워크(MarketKeywordNetwork)를 만든다.

1. 아이디어 전체 문장(market_search.build_idea_query)으로 뉴스를 가까운 순으로 가져온다.
2. 기사마다 제목·요약에서 명사를 뽑는다 (kiwipiepy). 띄어쓰기 없이 붙은 명사는 하나로 합친다
   (협동 + 로봇 → 협동로봇, 2 + 차 + 전지 → 2차전지). 앞서 고른 기사와 명사가 많이 겹치는 기사는
   같은 소식의 재게재로 보고 빼서 documents건을 고른다.
3. 전체 뉴스보다 이 아이디어 주변에서 두드러진 명사(lift) max_nodes개를 고르고, 같은 기사에
   함께 나온 기사 수로 명사를 잇는다.
4. 가중 모듈성으로 키워드 묶음을 나누고, 화면 배치 좌표를 계산한다 (networkx).

LLM을 부르지 않으며 질의 임베딩 1회만 쓴다. 함께 나온다는 것은 같은 기사에서 다뤄졌다는 뜻이며,
시장 수요나 인과관계의 근거가 아니어서 차원별 판정에 쓰지 않는다.
"""

import math
from collections import Counter
from itertools import combinations
from pathlib import Path
from typing import Callable

import yaml

from src.retrieval.market_search import EmbedFn, build_idea_query, embed_texts
from src.schemas import (
    MarketKeywordEdge,
    MarketKeywordNetwork,
    MarketKeywordNode,
    MarketSearchRequest,
)

ROOT_DIR = Path(__file__).resolve().parents[2]
CONFIG_PATH = ROOT_DIR / "configs" / "keyword_network.yaml"
NOTE = (
    "아이디어와 가까운 뉴스 제목·요약에서 같은 기사에 함께 나온 명사를 이은 것이며, "
    "시장 수요나 인과관계의 근거가 아닙니다."
)
# 합칠 수 있는 명사성 품사(명사 파생 접미사 '-화·-형·-성' 포함)와, 합친 말에 하나 이상 있어야 하는 품사
NOUN_TAGS = {"NNG", "NNP", "NNB", "SN", "SL", "XSN"}
CONTENT_TAGS = {"NNG", "NNP", "SL"}

TokenizeFn = Callable[[str], list[tuple[str, str, int, int]]]
_KIWI = None
# 전체 뉴스 명사 기사 수 캐시: (컬렉션 이름, 문서 수) → (기사 수, Counter)
_CORPUS_DF: dict[tuple, tuple[int, Counter]] = {}


def load_network_config(path: Path = CONFIG_PATH) -> dict:
    """키워드 네트워크 설정(YAML)을 읽는다."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def kiwi_tokenize(text: str) -> list[tuple[str, str, int, int]]:
    """kiwipiepy 형태소 분석 결과를 (형태, 품사, 시작 위치, 길이) 목록으로 반환한다. 모델은 처음 한 번만 읽는다."""
    global _KIWI
    if _KIWI is None:
        from kiwipiepy import Kiwi

        _KIWI = Kiwi()
    return [(t.form, t.tag, t.start, t.len) for t in _KIWI.tokenize(text)]


def extract_terms(
    text: str, config: dict, tokenize: TokenizeFn = kiwi_tokenize
) -> set[str]:
    """기사 1건의 명사 집합. 띄어쓰기 없이 이어진 명사성 형태소는 하나로 합치고, 공백 하나로 이어진
    외국어 단어는 한 표현으로 합친다(LS ELECTRIC).

    합친 말에 일반·고유명사·외국어가 없거나(숫자·의존명사만), 2자 미만·max_term_length 초과이거나,
    불용어면 뺀다.
    """
    terms, run, tags, end, last = set(), "", set(), None, None
    stopwords = set(config["stopwords"])

    def flush():
        if run and tags & CONTENT_TAGS:
            if 2 <= len(run) <= config["max_term_length"] and run not in stopwords:
                terms.add(run)

    for form, tag, start, length in tokenize(text):
        if tag in NOUN_TAGS and run and start == end:
            run, end, last = run + form, start + length, tag
            tags.add(tag)
            continue
        if tag == "SL" and last == "SL" and run and start == end + 1:
            run, end = f"{run} {form}", start + length
            continue
        flush()
        run, tags, end, last = "", set(), None, None
        if tag in NOUN_TAGS and tag != "XSN":
            run, tags, end, last = form, {tag}, start + length, tag
    flush()
    return terms


def drop_reprints(
    documents: list[set[str]], threshold: float, limit: int
) -> list[set[str]]:
    """가까운 순 기사 명사 집합에서 같은 소식의 재게재를 빼고 최대 limit건을 고른다.

    이미 고른 기사 중 하나와 Jaccard 유사도가 threshold 이상이면 뺀다. 명사가 없는 기사도 뺀다.
    """
    kept: list[set[str]] = []
    for terms in documents:
        if not terms:
            continue
        if all(len(terms & k) / len(terms | k) < threshold for k in kept):
            kept.append(terms)
            if len(kept) == limit:
                break
    return kept


def corpus_document_frequency(
    collection, config: dict, tokenize: TokenizeFn = kiwi_tokenize
) -> tuple[int, Counter]:
    """컬렉션 전체 뉴스의 (기사 수, 명사별 기사 수). 컬렉션 이름·문서 수가 같으면 캐시를 쓴다."""
    key = (getattr(collection, "name", None), collection.count())
    if key not in _CORPUS_DF:
        texts = collection.get(where={"source_type": "news"}, include=["documents"])[
            "documents"
        ]
        df = Counter(t for text in texts for t in extract_terms(text, config, tokenize))
        _CORPUS_DF[key] = (len(texts), df)
    return _CORPUS_DF[key]


def select_graph(
    documents: list[set[str]],
    config: dict,
    corpus_size: int,
    corpus_df: Counter,
) -> tuple[Counter, list[tuple[str, str, int]]]:
    """기사별 명사 집합에서 표시할 명사(기사 수)와 연결(명사 쌍, 함께 나온 기사 수)을 고른다.

    너무 드물거나(min_node_documents 미만) 너무 흔하거나(max_document_share 초과) 전체 뉴스보다
    두드러지지 않는(lift < min_lift) 명사는 빼고, 기사 수 × ln(lift)가 큰 max_nodes개만 남긴다.
    corpus_df에 없는 명사는 아이디어 주변 기사 수를 전체 기사 수로 본다. 연결은 min_edge_documents
    이상이며 명사마다 가장 강한 max_edges_per_node개 중 하나인 것만 남긴다. 남은 연결이 없는 명사는 뺀다.
    """
    df = Counter(term for terms in documents for term in terms)
    limit = config["max_document_share"] * len(documents)
    candidates = []
    for term, n in df.items():
        if not config["min_node_documents"] <= n <= limit:
            continue
        lift = (n / len(documents)) / (max(corpus_df[term], n) / corpus_size)
        if lift >= config["min_lift"]:
            candidates.append((term, n, n * math.log(lift)))
    candidates.sort(key=lambda item: (-item[2], item[0]))
    nodes = Counter({term: n for term, n, _ in candidates[: config["max_nodes"]]})

    pairs = Counter()
    for terms in documents:
        kept = sorted(t for t in terms if t in nodes)
        pairs.update(combinations(kept, 2))
    strong = [
        (a, b, n) for (a, b), n in pairs.items() if n >= config["min_edge_documents"]
    ]
    strong.sort(key=lambda edge: (-edge[2], edge[0], edge[1]))
    per_node, edges = Counter(), []
    for a, b, n in strong:
        if (
            per_node[a] < config["max_edges_per_node"]
            or per_node[b] < config["max_edges_per_node"]
        ):
            edges.append((a, b, n))
            per_node[a] += 1
            per_node[b] += 1
    linked = {t for a, b, _ in edges for t in (a, b)}
    return Counter({t: n for t, n in nodes.items() if t in linked}), edges


def layout_graph(
    nodes: Counter, edges: list[tuple[str, str, int]]
) -> tuple[dict[str, int], dict[str, tuple[float, float]], list[list[str]]]:
    """키워드 묶음(가중 모듈성)과 배치 좌표(가중 spring layout, 고정 seed)를 계산한다.

    반환: ({명사: 묶음 번호}, {명사: (x, y)}, 묶음별 명사 목록). 묶음 번호는 묶음 목록의 위치이며,
    명사 기사 수 합이 큰 묶음부터 0번이다. 묶음 안 명사는 기사 수가 많은 순이다.
    """
    import networkx as nx
    from networkx.algorithms.community import greedy_modularity_communities

    graph = nx.Graph()
    graph.add_nodes_from(nodes)
    graph.add_weighted_edges_from(edges)
    communities = greedy_modularity_communities(graph, weight="weight")
    groups = [sorted(g, key=lambda t: (-nodes[t], t)) for g in communities]
    groups.sort(key=lambda g: (-sum(nodes[t] for t in g), g[0]))
    cluster = {term: i for i, group in enumerate(groups) for term in group}
    # 기본 간격(1/√n)이면 연결이 많은 명사가 가운데 몰려 이름이 겹쳐, 간격을 넓히고 반복을 늘린다.
    positions = nx.spring_layout(
        graph,
        weight="weight",
        seed=7,
        k=2.5 / math.sqrt(max(len(nodes), 1)),
        iterations=300,
    )
    spread = separate_points(
        {t: (float(p[0]), float(p[1])) for t, p in positions.items()}
    )
    coords = {t: (round(x, 4), round(y, 4)) for t, (x, y) in spread.items()}
    return cluster, coords, groups


def separate_points(
    points: dict[str, tuple[float, float]], min_distance: float = 0.22, rounds: int = 60
) -> dict[str, tuple[float, float]]:
    """가까운 두 점을 min_distance까지 서로 밀어 이름이 겹치지 않게 하고, 좌표를 -1~1로 다시 맞춘다.

    연결이 아주 많은 명사끼리는 spring layout에서 거의 같은 자리에 놓인다. 점 이름 순서대로 정해진
    횟수만 밀어 결과가 항상 같다.
    """
    names = sorted(points)
    xy = {t: list(points[t]) for t in names}
    for _ in range(rounds):
        moved = False
        for i, a in enumerate(names):
            for b in names[i + 1 :]:
                dx, dy = xy[b][0] - xy[a][0], xy[b][1] - xy[a][1]
                dist = math.hypot(dx, dy)
                if dist >= min_distance:
                    continue
                if dist == 0:
                    dx, dy, dist = 1.0, 0.0, 1.0
                push = (min_distance - dist) / 2 / dist
                xy[a][0] -= dx * push
                xy[a][1] -= dy * push
                xy[b][0] += dx * push
                xy[b][1] += dy * push
                moved = True
        if not moved:
            break
    scale = max((abs(v) for p in xy.values() for v in p), default=1.0) or 1.0
    return {t: (p[0] / scale, p[1] / scale) for t, p in xy.items()}


def nearest_news(
    request: MarketSearchRequest, collection, embed_fn: EmbedFn, n: int
) -> list[str]:
    """아이디어 전체 문장과 가까운 뉴스 n건의 텍스트(제목 + 요약). 같은 dup_group은 1건만 쓴다."""
    count = collection.count()
    if count == 0:
        return []
    result = collection.query(
        query_embeddings=embed_fn([build_idea_query(request)]),
        n_results=min(n * 2, count),
        where={"source_type": "news"},
        include=["documents", "metadatas"],
    )
    texts, groups = [], set()
    for text, meta in zip(result["documents"][0], result["metadatas"][0]):
        group = meta.get("dup_group") or meta.get("source_id")
        if group in groups:
            continue
        groups.add(group)
        texts.append(text)
        if len(texts) == n:
            break
    return texts


def build_keyword_network(
    request: MarketSearchRequest,
    collection,
    embed_fn: EmbedFn = embed_texts,
    config: dict | None = None,
    tokenize: TokenizeFn = kiwi_tokenize,
) -> MarketKeywordNetwork:
    """아이디어와 가까운 뉴스로 키워드 동시 출현 네트워크를 만든다.

    재게재를 뺀 기사가 min_documents건 미만이거나 연결이 하나도 없으면 insufficient, 검색·분석
    실패는 error다.
    """
    config = config or load_network_config()
    try:
        texts = nearest_news(
            request,
            collection,
            embed_fn,
            config["documents"] * config["candidate_factor"],
        )
        documents = drop_reprints(
            [extract_terms(text, config, tokenize) for text in texts],
            config["duplicate_similarity"],
            config["documents"],
        )
        if len(documents) < config["min_documents"]:
            return MarketKeywordNetwork(
                status="insufficient", document_count=len(documents), note=NOTE
            )
        corpus_size, corpus_df = corpus_document_frequency(collection, config, tokenize)
        nodes, edges = select_graph(documents, config, corpus_size, corpus_df)
        if not edges:
            return MarketKeywordNetwork(
                status="insufficient", document_count=len(documents), note=NOTE
            )
        cluster, coords, groups = layout_graph(nodes, edges)
    except Exception as exc:  # 네트워크 실패는 시장 보고서 전체를 막지 않는다
        return MarketKeywordNetwork(status="error", error_message=str(exc), note=NOTE)

    return MarketKeywordNetwork(
        status="completed",
        document_count=len(documents),
        nodes=[
            MarketKeywordNode(
                term=term,
                document_count=n,
                cluster=cluster[term],
                x=coords[term][0],
                y=coords[term][1],
            )
            for term, n in sorted(nodes.items(), key=lambda item: (-item[1], item[0]))
        ],
        edges=[MarketKeywordEdge(source=a, target=b, weight=n) for a, b, n in edges],
        clusters=groups,
        note=NOTE,
    )
