"""기사 본문 자동 수집: robots 처리, 상태 코드별 재시도, 크기·형식·인코딩, 요약 대조."""

import requests

from src.planner.body import (
    BodyFetcher,
    extract_article_text,
    matches_snippet,
)

SNIPPET = (
    "가상비전은 정상 이미지만으로 학습하는 검사 모델을 공급한다고 밝혔다. 회사 측은..."
)
ARTICLE = (
    "<html><head><title>t</title><script>var x='스크립트';</script></head><body>"
    "<nav>메뉴 홈 뉴스 경제</nav>"
    "<div class='article_body'><p>가상비전은 정상 이미지만으로 학습하는 검사 모델을 "
    "공급한다고 밝혔다.</p><p>회사 측은 고객 공정에 맞춘 광학 구성을 함께 제공한다고 "
    "설명했다. 이번 제품은 기존 라인에 추가로 설치할 수 있다.</p>"
    "<p>홍길동 기자 hong@example.com</p><p>무단전재 및 재배포 금지</p></div>"
    "<footer>회사 소개 저작권</footer></body></html>"
)


class Response:
    def __init__(self, status=200, body=b"", content_type="text/html; charset=utf-8"):
        self.status_code = status
        self.content = body
        self.headers = {"Content-Type": content_type}

    def iter_content(self, size):
        for i in range(0, len(self.content), size):
            yield self.content[i : i + size]


class FakeHttp:
    def __init__(self, routes):
        self.routes = routes
        self.calls = []

    def __call__(self, url, headers=None, timeout=None, stream=False):
        self.calls.append(url)
        outcome = self.routes[url]
        if isinstance(outcome, list):
            outcome = outcome.pop(0) if len(outcome) > 1 else outcome[0]
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def fetcher(routes, **kwargs):
    http = FakeHttp(routes)
    clock = {"t": 0.0}
    sleeps = []

    def sleep(seconds):
        sleeps.append(seconds)
        clock["t"] += seconds

    f = BodyFetcher(http, sleep=sleep, monotonic=lambda: clock["t"], **kwargs)
    return f, http, sleeps


URL = "https://news.example.com/a/1"
ROBOTS = "https://news.example.com/robots.txt"


def test_article_container_text_excludes_navigation_scripts_and_boilerplate():
    text = extract_article_text(ARTICLE)
    assert "정상 이미지만으로 학습" in text and "광학 구성" in text
    assert "메뉴" not in text and "스크립트" not in text
    assert "무단전재" not in text and "hong@example.com" not in text


def test_ok_fetch_after_robots_allow_and_snippet_match():
    f, http, _ = fetcher(
        {ROBOTS: Response(404), URL: Response(body=ARTICLE.encode("utf-8"))}
    )
    result = f.fetch(URL, SNIPPET)
    assert result.status == "ok" and "광학 구성" in result.text
    assert http.calls == [ROBOTS, URL]


def test_robots_disallow_and_server_error_block_fetching():
    disallow = Response(
        body=b"User-agent: *\nDisallow: /a/\n", content_type="text/plain"
    )
    f, http, _ = fetcher({ROBOTS: disallow, URL: Response(body=ARTICLE.encode())})
    assert f.fetch(URL, SNIPPET).status == "robots_disallowed"
    assert http.calls == [ROBOTS]

    f, http, _ = fetcher({ROBOTS: Response(503), URL: Response(body=ARTICLE.encode())})
    assert f.fetch(URL, SNIPPET).status == "robots_unavailable"
    f, http, _ = fetcher({ROBOTS: requests.Timeout(), URL: Response()})
    assert f.fetch(URL, SNIPPET).status == "robots_unavailable"
    assert URL not in http.calls


def test_403_is_not_retried_but_timeout_and_5xx_are_retried_once():
    f, http, _ = fetcher({ROBOTS: Response(404), URL: Response(403)})
    assert f.fetch(URL, SNIPPET).status == "http_403"
    assert http.calls.count(URL) == 1

    ok = Response(body=ARTICLE.encode())
    f, http, _ = fetcher({ROBOTS: Response(404), URL: [requests.Timeout(), ok]})
    result = f.fetch(URL, SNIPPET)
    assert result.status == "ok" and result.attempts == 2

    f, http, _ = fetcher({ROBOTS: Response(404), URL: [Response(502)]})
    assert f.fetch(URL, SNIPPET).status == "http_5xx"
    assert http.calls.count(URL) == 2


def test_size_type_and_parse_failures_have_distinct_statuses():
    big = Response(body=b"<p>" + b"a" * 2_100_000 + b"</p>")
    f, _, _ = fetcher({ROBOTS: Response(404), URL: big})
    assert f.fetch(URL, SNIPPET).status == "too_large"

    pdf = Response(body=b"%PDF", content_type="application/pdf")
    f, _, _ = fetcher({ROBOTS: Response(404), URL: pdf})
    assert f.fetch(URL, SNIPPET).status == "non_html"

    empty = Response(body="<html><body><p>짧음</p></body></html>".encode())
    f, _, _ = fetcher({ROBOTS: Response(404), URL: empty})
    assert f.fetch(URL, SNIPPET).status == "parse_empty"


def test_euc_kr_page_is_decoded_and_wrong_page_is_rejected():
    page = Response(
        body=ARTICLE.encode("cp949"), content_type="text/html; charset=EUC-KR"
    )
    f, _, _ = fetcher({ROBOTS: Response(404), URL: page})
    assert f.fetch(URL, SNIPPET).status == "ok"

    f, _, _ = fetcher({ROBOTS: Response(404), URL: Response(body=ARTICLE.encode())})
    other = "전혀 다른 기사의 요약 문장으로 시작하는 내용입니다..."
    result = f.fetch(URL, other)
    assert result.status == "snippet_mismatch" and result.text == ""


def test_portal_and_denylist_links_are_never_requested():
    f, http, _ = fetcher({}, deny_domains=["blocked.example.com"])
    assert f.fetch("https://n.news.naver.com/x", SNIPPET).status == "skipped_portal"
    assert (
        f.fetch("https://blocked.example.com/x", SNIPPET).status == "skipped_denylist"
    )
    assert http.calls == []


def test_same_domain_requests_keep_minimum_interval():
    url2 = "https://news.example.com/a/2"
    f, _, sleeps = fetcher(
        {
            ROBOTS: Response(404),
            URL: Response(body=ARTICLE.encode()),
            url2: Response(body=ARTICLE.encode()),
        }
    )
    f.fetch(URL, SNIPPET)
    f.fetch(url2, SNIPPET)
    assert len(sleeps) == 2 and all(abs(s - 1.0) < 1e-9 for s in sleeps)


def test_snippet_fragments_are_matched_after_normalization():
    assert matches_snippet("가상비전은, 정상 이미지만으로 학습하는", SNIPPET)
    assert not matches_snippet("관련 없는 본문", SNIPPET)
