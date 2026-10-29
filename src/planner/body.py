"""채택 기사의 본문을 자동 수집한다(reviewed_body 층, origin=auto_fetch).

- robots.txt를 먼저 읽는다: 2xx는 규칙 적용, 4xx는 허용, 5xx·시간 초과·접속 실패는 수집하지 않는다.
- 포털(naver.com) 링크와 제외 도메인은 열지 않는다. 도메인마다 최소 간격을 두고 식별 UA를 보낸다.
- 403은 다시 시도하지 않고, 시간 초과·접속 실패·5xx만 1회 다시 시도한다. 응답은 2MB까지만 읽는다.
- 저장 요약의 연속 구간이 추출 본문에 없으면 다른 페이지로 보고(snippet_mismatch) 쓰지 않는다.
- 본문은 실행 폴더에만 두며 화면에는 짧은 구절과 원문 링크만 보인다. 자동 수집은 사람 검토가 아니다.
"""

import re
import time
from collections.abc import Callable
from dataclasses import dataclass
from html.parser import HTMLParser
from urllib.parse import urlparse
from urllib.robotparser import RobotFileParser

import requests

USER_AGENT = "IdeaLensPlanner/1.0 (news evidence review; honors robots.txt)"
TIMEOUT = 8
ROBOTS_TIMEOUT = 5
MAX_BYTES = 2_000_000
MAX_BODY_CHARS = 20_000
MIN_BODY_CHARS = 100
DOMAIN_INTERVAL = 1.0
PORTAL_HOSTS = ("naver.com",)
_CONTAINER_RE = re.compile(
    r"article|news[_-]?body|newsbody|news[_-]?content|view[_-]?con|viewcon|"
    r"content[_-]?body|txt[_-]?area|artcl|story|entry-content|post-content|본문",
    re.I,
)
_SKIP_TAGS = {
    "script",
    "style",
    "noscript",
    "iframe",
    "svg",
    "header",
    "footer",
    "nav",
    "aside",
    "form",
    "button",
    "select",
    "figure",
    "template",
}
_BLOCK_TAGS = {"p", "div", "br", "li", "h1", "h2", "h3", "h4", "tr", "section"}
_VOID_TAGS = {"br", "img", "hr", "meta", "link", "input", "source", "wbr"}
_BOILERPLATE_RE = re.compile(
    r"무단\s*전재|재배포\s*금지|copyright|저작권자|ⓒ|©|기자\s*=?\s*[\w.]+@", re.I
)
_META_CHARSET_RE = re.compile(rb"charset\s*=\s*[\"']?([A-Za-z0-9_-]+)", re.I)
_NON_WORD_RE = re.compile(r"[\W_]+")


@dataclass
class BodyResult:
    status: str
    text: str = ""
    http_status: int | None = None
    encoding: str = ""
    attempts: int = 0


class ArticleTextParser(HTMLParser):
    """본문 후보 컨테이너(article·본문 class/id)별 텍스트와 문단 텍스트를 모은다."""

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.stack: list[tuple[str, int | None]] = []
        self.skip_depth = 0
        self.containers: list[list[str]] = []
        self.open_containers: list[int] = []
        self.paragraphs: list[str] = []
        self.in_p = 0
        self.current_p: list[str] = []

    def handle_starttag(self, tag, attrs):
        if tag in _VOID_TAGS:
            if tag == "br":
                self._newline()
            return
        if tag in _SKIP_TAGS:
            self.skip_depth += 1
        container = None
        if not self.skip_depth:
            marker = " ".join(
                value or "" for key, value in attrs if key in {"id", "class"}
            )
            if tag == "article" or (marker and _CONTAINER_RE.search(marker)):
                container = len(self.containers)
                self.containers.append([])
                self.open_containers.append(container)
        if tag == "p":
            self.in_p += 1
        if tag in _BLOCK_TAGS:
            self._newline()
        self.stack.append((tag, container))

    def handle_endtag(self, tag):
        if not any(t == tag for t, _ in self.stack):
            return
        while self.stack:
            open_tag, container = self.stack.pop()
            if open_tag in _SKIP_TAGS:
                self.skip_depth -= 1
            if container is not None and container in self.open_containers:
                self.open_containers.remove(container)
            if open_tag == "p":
                self.in_p -= 1
                if not self.in_p and self.current_p:
                    self.paragraphs.append(" ".join(self.current_p))
                    self.current_p = []
            if open_tag in _BLOCK_TAGS:
                self._newline()
            if open_tag == tag:
                break

    def handle_data(self, data):
        if self.skip_depth or not data.strip():
            return
        for index in self.open_containers:
            self.containers[index].append(data)
        if self.in_p:
            self.current_p.append(data.strip())

    def _newline(self):
        for index in self.open_containers:
            self.containers[index].append("\n")

    def best_text(self) -> str:
        texts = [clean_text("".join(parts)) for parts in self.containers]
        best = max(texts, key=len, default="")
        if len(best) >= MIN_BODY_CHARS * 2:
            return best
        joined = clean_text("\n".join(self.paragraphs))
        return joined if len(joined) > len(best) else best


def clean_text(text: str) -> str:
    """줄 단위 공백 정리·빈 줄 제거·저작권·기자 이메일 줄 제거."""
    lines = []
    for line in text.splitlines():
        line = " ".join(line.split())
        if line and not _BOILERPLATE_RE.search(line):
            lines.append(line)
    return "\n".join(lines)


def extract_article_text(html: str) -> str:
    parser = ArticleTextParser()
    try:
        parser.feed(html)
        parser.close()
    except Exception:  # 손상된 HTML은 지금까지 읽은 내용만 쓴다
        pass
    return parser.best_text()


def _normalize(text: str) -> str:
    return _NON_WORD_RE.sub("", text).lower()


def matches_snippet(body: str, snippet: str, window: int = 15) -> bool:
    """저장 요약을 '...'로 나눈 조각 중 하나의 앞 window자가 본문에 있으면 같은 기사로 본다."""
    target = _normalize(body)
    for fragment in re.split(r"\.\.\.|…", snippet or ""):
        piece = _normalize(fragment)
        if len(piece) >= window and piece[:window] in target:
            return True
    return False


def _decode(content: bytes, content_type: str) -> tuple[str, str]:
    match = re.search(r"charset\s*=\s*([\w-]+)", content_type or "", re.I)
    candidates = []
    if match:
        candidates.append(match.group(1))
    meta = _META_CHARSET_RE.search(content[:4096])
    if meta:
        candidates.append(meta.group(1).decode("ascii", "ignore"))
    candidates += ["utf-8", "cp949"]
    for encoding in candidates:
        encoding = (
            "cp949" if encoding.lower() in {"euc-kr", "ks_c_5601-1987"} else encoding
        )
        try:
            return content.decode(encoding), encoding
        except (LookupError, UnicodeDecodeError):
            continue
    return content.decode("utf-8", "replace"), "utf-8-replace"


class BodyFetcher:
    """도메인별 robots 캐시와 접근 간격을 유지하며 본문을 가져온다."""

    def __init__(
        self,
        http_get: Callable | None = None,
        sleep: Callable[[float], None] = time.sleep,
        monotonic: Callable[[], float] = time.monotonic,
        deny_domains: list[str] | tuple = (),
        retries: int = 1,
        interval: float = DOMAIN_INTERVAL,
        cancelled: Callable[[], bool] = lambda: False,
    ):
        self.http_get = http_get or requests.Session().get
        self.sleep = sleep
        self.monotonic = monotonic
        self.deny_domains = tuple(deny_domains)
        self.retries = retries
        self.interval = interval
        self.cancelled = cancelled
        self.robots: dict[str, RobotFileParser | str] = {}
        self.last_access: dict[str, float] = {}
        self.requests_made = 0

    def _wait(self, host: str) -> None:
        last = self.last_access.get(host)
        if last is not None:
            delay = self.interval - (self.monotonic() - last)
            if delay > 0:
                self.sleep(delay)
        self.last_access[host] = self.monotonic()

    def _robots(self, scheme: str, host: str):
        if host in self.robots:
            return self.robots[host]
        self._wait(host)
        self.requests_made += 1
        try:
            response = self.http_get(
                f"{scheme}://{host}/robots.txt",
                headers={"User-Agent": USER_AGENT},
                timeout=ROBOTS_TIMEOUT,
            )
        except requests.RequestException:
            self.robots[host] = "robots_unavailable"
            return self.robots[host]
        if response.status_code >= 500:
            self.robots[host] = "robots_unavailable"
        elif response.status_code >= 400:
            parser = RobotFileParser()
            parser.allow_all = True
            self.robots[host] = parser
        else:
            parser = RobotFileParser()
            text, _ = _decode(response.content or b"", "")
            parser.parse(text.splitlines())
            self.robots[host] = parser
        return self.robots[host]

    def fetch(self, url: str, snippet: str) -> BodyResult:
        parsed = urlparse(url)
        host = parsed.netloc.lower()
        if self.cancelled():
            return BodyResult("cancelled")
        if parsed.scheme not in {"http", "https"} or not host:
            return BodyResult("network_error")
        if any(host == p or host.endswith("." + p) for p in PORTAL_HOSTS):
            return BodyResult("skipped_portal")
        if any(host == d or host.endswith("." + d) for d in self.deny_domains):
            return BodyResult("skipped_denylist")
        robots = self._robots(parsed.scheme, host)
        if robots == "robots_unavailable":
            return BodyResult("robots_unavailable")
        if not robots.can_fetch(USER_AGENT, url):
            return BodyResult("robots_disallowed")

        status, attempts = "network_error", 0
        for attempt in range(self.retries + 1):
            attempts = attempt + 1
            self._wait(host)
            self.requests_made += 1
            try:
                response = self.http_get(
                    url,
                    headers={"User-Agent": USER_AGENT, "Accept": "text/html"},
                    timeout=TIMEOUT,
                    stream=True,
                )
            except requests.Timeout:
                status = "timeout"
                continue
            except requests.RequestException:
                status = "network_error"
                continue
            code = response.status_code
            if code == 403:
                return BodyResult("http_403", http_status=code, attempts=attempts)
            if 400 <= code < 500:
                return BodyResult("http_4xx", http_status=code, attempts=attempts)
            if code >= 500:
                status = "http_5xx"
                continue
            return self._read(response, snippet, attempts)
        return BodyResult(status, attempts=attempts)

    def _read(self, response, snippet: str, attempts: int) -> BodyResult:
        content_type = response.headers.get("Content-Type", "")
        code = response.status_code
        if "html" not in content_type.lower():
            return BodyResult("non_html", http_status=code, attempts=attempts)
        chunks, size = [], 0
        for chunk in response.iter_content(65536):
            size += len(chunk)
            if size > MAX_BYTES:
                return BodyResult("too_large", http_status=code, attempts=attempts)
            chunks.append(chunk)
        html, encoding = _decode(b"".join(chunks), content_type)
        text = extract_article_text(html)
        if len(text) < MIN_BODY_CHARS:
            return BodyResult("parse_empty", http_status=code, attempts=attempts)
        if not matches_snippet(text, snippet):
            return BodyResult(
                "snippet_mismatch",
                http_status=code,
                encoding=encoding,
                attempts=attempts,
            )
        return BodyResult(
            "ok",
            text=text[:MAX_BODY_CHARS],
            http_status=code,
            encoding=encoding,
            attempts=attempts,
        )
