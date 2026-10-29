"""예산 안에서 아이디어별 뉴스 후보를 검색하고 자료집에 채택할 기사를 고른다.

- 고유 기사 총량(max_articles)·검색 요청 수·후보 수·재시도 수를 각각 제한한다.
- 선정은 코드 규칙만 쓴다: 같은 URL → 날짜 → 범위 사전 → 전재(제목 유사) 순으로 제외 사유를 남긴다.
- 전재 후보는 대표 1건만 예산을 쓰고, 나머지는 같은 dup_group의 재게재로 기록한다(독립 확인이 아님).
- 배분량을 채우지 못하면 부족분(shortfall)을 기록하며 무관한 기사로 채우지 않는다.
- 같은 질의를 다음 라운드에 다시 쓰면 첫 페이지부터 다시 받지 않고 이어서 받는다.
"""

import time
from collections.abc import Callable
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime

import requests

from src.ingestion.market_processor import (
    DUP_WINDOW_DAYS,
    TITLE_SIMILARITY,
    title_similarity,
)
from src.ingestion.news_client import normalize_item, search_news
from src.planner.config import Profile

KST = timezone(timedelta(hours=9))
SearchFn = Callable[..., dict]
RETRYABLE_MARKERS = ("error 429", "error 500", "error 502", "error 503", "error 504")


def now_kst() -> datetime:
    return datetime.now(KST)


def default_search(query: str, display: int, start: int, sort: str) -> dict:
    """NAVER 뉴스 검색 1회 호출(news_client 재사용)."""
    return search_news(query, display=display, start=start, sort=sort)


def is_retryable(exc: Exception) -> bool:
    if isinstance(exc, (requests.Timeout, requests.ConnectionError)):
        return True
    return isinstance(exc, RuntimeError) and any(
        marker in str(exc) for marker in RETRYABLE_MARKERS
    )


def in_scope(text: str, profile: Profile) -> bool:
    """범위 사전 판정. 포함어가 있어야 하고, 제외어가 있으면 비전 표현이 함께 있어야 한다."""
    scope = profile.scope
    if not any(term in text for term in scope.include_any):
        return False
    if any(term in text for term in scope.exclude_any):
        return any(term in text for term in scope.vision_terms)
    return True


def industry_scope(text: str, profile: Profile) -> str:
    return (
        "direct"
        if any(term in text for term in profile.scope.industry_direct)
        else "adjacent"
    )


def _days_between(a: int, b: int) -> int:
    fmt = "%Y%m%d"
    return abs((datetime.strptime(str(a), fmt) - datetime.strptime(str(b), fmt)).days)


def _published_iso(item: dict) -> str:
    try:
        return parsedate_to_datetime(item["pubDate"]).isoformat()
    except (KeyError, TypeError, ValueError):
        return ""


class Collection:
    """한 실행의 검색·선정 상태. 모든 상한은 이 객체에서 함께 센다."""

    def __init__(
        self,
        profile: Profile,
        search_fn: SearchFn = default_search,
        clock: Callable[[], datetime] = now_kst,
        sleep: Callable[[float], None] = time.sleep,
        cancelled: Callable[[], bool] = lambda: False,
        interval: float = 0.2,
    ):
        self.profile = profile
        self.budget = profile.budget
        self.search_fn = search_fn
        self.clock = clock
        self.sleep = sleep
        self.cancelled = cancelled
        self.interval = interval
        self.requests_used = 0
        self.candidates_seen = 0
        self.retained: list[dict] = []
        self.selection: list[dict] = []
        self.raw_responses: list[dict] = []
        self.shortfalls: list[dict] = []
        self.query_plan: list[dict] = []
        self.stops: list[str] = []
        self._urls: set[str] = set()
        self._next_start: dict[str, int] = {}
        self._exhausted_queries: set[str] = set()

    # 상한 ------------------------------------------------------------------
    def remaining_articles(self) -> int:
        return self.budget.max_articles - len(self.retained)

    def _limit_reached(self) -> str:
        if self.cancelled():
            return "cancelled"
        if self.requests_used >= self.budget.max_api_requests:
            return "request_cap_reached"
        if self.candidates_seen >= self.budget.max_candidates:
            return "candidate_cap_reached"
        if self.remaining_articles() <= 0:
            return "budget_exhausted"
        return ""

    def _stop(self, reason: str) -> None:
        if reason and reason not in self.stops:
            self.stops.append(reason)

    # 검색 ------------------------------------------------------------------
    def _search(self, query_id: str, query: str, start: int) -> dict | None:
        """검색 1회. 429·5xx·시간 초과만 api_retries만큼 다시 시도하며 시도마다 요청 수를 센다."""
        params = {
            "query": query,
            "display": self.budget.display_per_request,
            "start": start,
            "sort": self.budget.sort,
        }
        for attempt in range(self.budget.api_retries + 1):
            reason = self._limit_reached()
            if reason and reason != "budget_exhausted":
                self._stop(reason)
                return None
            if self.requests_used:
                self.sleep(self.interval)
            self.requests_used += 1
            requested_at = self.clock().isoformat()
            try:
                data = self.search_fn(query, params["display"], start, params["sort"])
            except Exception as exc:  # 검색 실패를 원응답 기록으로 남긴다
                self.raw_responses.append(
                    {
                        "query_id": query_id,
                        "params": params,
                        "attempt": attempt,
                        "requested_at": requested_at,
                        "status": "error",
                        "error": f"{type(exc).__name__}: {exc}"[:300],
                    }
                )
                if is_retryable(exc) and attempt < self.budget.api_retries:
                    continue
                return None
            self.raw_responses.append(
                {
                    "query_id": query_id,
                    "params": params,
                    "attempt": attempt,
                    "requested_at": requested_at,
                    "status": "ok",
                    "response": data,
                }
            )
            return data
        return None

    # 선정 ------------------------------------------------------------------
    def _decide(self, item: dict, meta: dict, rank: int) -> dict | None:
        """후보 1건을 판정한다. 채택하면 레코드를, 제외하면 None을 반환한다."""
        self.candidates_seen += 1
        try:
            record = normalize_item(
                item,
                {"id": meta["query_id"], "query": meta["query"]},
                int(self.clock().strftime("%Y%m%d")),
            )
        except (KeyError, TypeError, ValueError) as exc:
            self._log(
                meta, rank, {}, "excluded", f"malformed_item:{type(exc).__name__}"
            )
            return None
        text = f"{record['title']}\n{record['description']}"
        if record["url"] in self._urls:
            self._log(meta, rank, record, "excluded", "duplicate_url")
            return None
        if record["published_at"] < self.budget.date_from:
            self._log(meta, rank, record, "excluded", "before_date_from")
            return None
        if not in_scope(text, self.profile):
            self._log(meta, rank, record, "excluded", "out_of_scope")
            return None
        for kept in self.retained:
            if _days_between(
                kept["published_date"], record["published_at"]
            ) <= DUP_WINDOW_DAYS and (
                title_similarity(kept["title"], record["title"]) > TITLE_SIMILARITY
            ):
                self._urls.add(record["url"])
                self._log(
                    meta, rank, record, "excluded", "near_duplicate", kept["dup_group"]
                )
                return None
        self._urls.add(record["url"])
        retained = {
            "source_id": record["source_id"],
            "url": record["url"],
            "naver_link": record.get("naver_link") or "",
            "publisher": record["domain"].removeprefix("www."),
            "title": record["title"],
            "snippet": record["description"],
            "published_at": _published_iso(item),
            "published_date": record["published_at"],
            "collected_at": self.clock().isoformat(),
            "query_id": meta["query_id"],
            "question_id": meta["question_id"],
            "group": meta["group"],
            "round": meta["round"],
            "rank": rank,
            "dup_group": record["source_id"],
            "industry_scope": industry_scope(text, self.profile),
        }
        self._log(meta, rank, record, "retained", "", record["source_id"])
        return retained

    def _log(self, meta, rank, record, decision, reason, dup_group=""):
        self.selection.append(
            {
                "query_id": meta["query_id"],
                "question_id": meta["question_id"],
                "round": meta["round"],
                "rank": rank,
                "source_id": record.get("source_id", ""),
                "url": record.get("url", ""),
                "title": record.get("title", ""),
                "decision": decision,
                "reason": reason,
                "dup_group": dup_group,
            }
        )

    def collect(self, queries: list[dict], quota: int, label: str) -> list[dict]:
        """질의 목록을 돌아가며 quota건까지 채택한다. 페이지는 질의당 max_pages_per_query까지."""
        quota = min(quota, self.remaining_articles())
        cursors = [
            {
                "meta": q,
                "buffer": [],
                "start": self._next_start.get(q["query"], 1),
                "pages": 0,
                "done": q["query"] in self._exhausted_queries,
                "rank": 0,
            }
            for q in queries
        ]
        self.query_plan.extend(queries)
        taken: list[dict] = []
        share = -(-quota // max(len(cursors), 1))
        for pass_no in range(2):
            for cursor in cursors:
                limit = share if pass_no == 0 else quota
                took = 0
                while len(taken) < quota and took < limit and not cursor["done"]:
                    if self.cancelled():
                        self._stop("cancelled")
                        return taken
                    if self.candidates_seen >= self.budget.max_candidates:
                        self._stop("candidate_cap_reached")
                        break
                    if not cursor["buffer"] and not self._fetch(cursor):
                        break
                    item = cursor["buffer"].pop(0)
                    cursor["rank"] += 1
                    record = self._decide(item, cursor["meta"], cursor["rank"])
                    if record:
                        self.retained.append(record)
                        taken.append(record)
                        took += 1
        for cursor in cursors:
            query = cursor["meta"]["query"]
            self._next_start[query] = cursor["start"] - len(cursor["buffer"])
            if cursor.get("end"):
                self._exhausted_queries.add(query)
        if len(taken) < quota:
            self.shortfalls.append(
                {"label": label, "wanted": quota, "retained": len(taken)}
            )
        return taken

    def _fetch(self, cursor: dict) -> bool:
        if cursor["pages"] >= self.budget.max_pages_per_query:
            cursor["done"] = True
            return False
        meta = cursor["meta"]
        data = self._search(meta["query_id"], meta["query"], cursor["start"])
        cursor["pages"] += 1
        items = (data or {}).get("items") or []
        if not items:
            cursor["done"] = True
            cursor["end"] = data is not None
            return False
        cursor["buffer"].extend(items)
        cursor["start"] += len(items)
        if cursor["start"] > min(int((data or {}).get("total", 0)), 1000):
            cursor["pages"] = self.budget.max_pages_per_query
            cursor["end"] = True
        return True


def initial_queries(profile: Profile) -> list[tuple[dict, list[dict]]]:
    """초기 배분 그룹별 (그룹 정보, 질의 목록)을 프로필 순서대로 만든다."""
    plan = []
    for group in profile.initial_allocation:
        queries = [
            {
                "query_id": f"r0-{group.group}-{n}",
                "question_id": q.question_id,
                "query": q.query,
                "group": group.group,
                "round": 0,
            }
            for n, q in enumerate(group.queries, 1)
        ]
        plan.append(({"group": group.group, "articles": group.articles}, queries))
    return plan


def collect_initial(collection: Collection) -> list[dict]:
    retained = []
    for group, queries in initial_queries(collection.profile):
        retained += collection.collect(queries, group["articles"], group["group"])
    return retained


def collect_followup(
    collection: Collection, picks: list[dict], round_no: int
) -> list[dict]:
    """후속 라운드: 선택된 질문의 질의로 followup_batch건 안에서 채택한다."""
    queries = [
        {
            "query_id": f"r{round_no}-{pick['question_id']}-{n}",
            "question_id": pick["question_id"],
            "query": query,
            "group": "followup",
            "round": round_no,
        }
        for pick in picks
        for n, query in enumerate(pick["queries"], 1)
    ]
    if not queries:
        return []
    quota = min(collection.budget.followup_batch, collection.remaining_articles())
    if quota <= 0:
        collection._stop("budget_exhausted")
        return []
    return collection.collect(queries, quota, f"round-{round_no}")
