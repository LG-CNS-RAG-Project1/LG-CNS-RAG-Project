"""사업기획 근거 테스트용 가상 기사·가짜 검색·가짜 본문·가짜 LLM.

모든 기업명과 문장은 가상이며 연구 예시의 실제 기업·문구를 쓰지 않는다. 각 기사는 회귀 사례
(역할 혼동, 계열 적용, 계획 단계, 철수, 부정 진술, 제목만, 추출 실패, 장비사 경로, 동시 언급 등)를 하나씩 담는다.
"""

import json
from datetime import datetime

from src.ingestion.news_client import make_source_id
from src.planner.anchors import process_articles
from src.planner.body import extract_article_text
from src.planner.collect import KST, industry_scope
from src.planner.config import load_profile
from src.planner.extract import Extractor
from src.planner.rules import evaluate_evidence
from src.schemas import StructuredIdea

FIXED_NOW = datetime(2026, 10, 29, 9, 0, tzinfo=KST)

IDEA = StructuredIdea(
    title="2차전지·전자부품 AI 비전 외관 검사",
    problem="외관 검사를 작업자 육안에 의존해 미세 불량을 놓친다",
    technology="딥러닝 AI 비전 외관 검사 장비",
    customers="2차전지·전자부품 제조사 품질 부서",
    difference="기존 라인에 추가 설치하는 검사 모듈과 적은 불량 이미지로 학습하는 모델",
    revenue="검사 장비 판매와 모델 유지보수 계약",
    field_sources={"difference": "user_answer"},
)


def article(key, title, snippet, body="", body_status="http_4xx", **kwargs):
    return {
        "key": key,
        "url": f"https://news.example.com/{key.lower()}",
        "title": title,
        "snippet": snippet,
        "body": body,
        "body_status": body_status,
        "pub": "Tue, 20 Oct 2026 09:00:00 +0900",
        "candidates": kwargs.get("candidates", {}),
        "fail": kwargs.get("fail", False),
        "question_id": kwargs.get("question_id", "C1"),
    }


WORLD = [
    article(
        "A1",
        "가나비전, '제로샷' AI 비전검사 솔루션 출시",
        "가나비전은 정상 이미지만으로 학습하는 검사 솔루션을 출시했다고 밝혔다. "
        "불량 데이터가 부족한 공정에서도...",
        body=(
            "가나비전은 정상 이미지만으로 학습하는 검사 솔루션을 출시했다고 밝혔다.\n"
            "회사는 고객 공정에 맞춘 광학 구성을 함께 제공한다고 설명했다.\n"
            "가나비전은 국내 이차전지 제조사에 검사 장비를 공급했다.\n"
            "가나비전과 마바솔루션 등 기업이 전시회에 참가했다."
        ),
        body_status="ok",
        candidates={
            "mentions": [
                ("가나비전", "supplier"),
                ("국내 이차전지 제조사", "adopter"),
                ("마바솔루션", "supplier"),
            ],
            "claims": [
                {
                    "exact_text": "정상 이미지만으로 학습하는 검사 솔루션을 출시했다",
                    "owner_text": "가나비전",
                    "product_text": "",
                },
                {
                    "exact_text": "고객 공정에 맞춘 광학 구성을 함께 제공한다",
                    "owner_text": "",
                    "product_text": "",
                },
            ],
            "relations": [
                {
                    "exact_clause": "가나비전은 국내 이차전지 제조사에 검사 장비를 공급했다",
                    "subject_text": "가나비전",
                    "object_text": "국내 이차전지 제조사",
                    "relation_hint": "supply",
                },
                {
                    "exact_clause": "가나비전과 마바솔루션 등 기업이 전시회에 참가했다",
                    "subject_text": "가나비전",
                    "object_text": "마바솔루션",
                    "relation_hint": "unknown",
                },
            ],
        },
    ),
    article(
        "A2",
        "다라테크, 다품종 검사 셋업 단축 플랫폼 공개",
        "다라테크는 제품이 바뀔 때마다 검사 조건을 다시 설정하던 셋업 시간을 95% "
        "줄였다고 밝혔다. 이 플랫폼은 노코딩 방식으로...",
        body_status="http_403",
        candidates={
            "mentions": [("다라테크", "supplier")],
            "claims": [
                {
                    "exact_text": "제품이 바뀔 때마다 검사 조건을 다시 설정하던 셋업 시간을 95% 줄였다",
                    "owner_text": "다라테크",
                    "product_text": "",
                }
            ],
            "metrics": [{"exact_text": "셋업 시간을 95% 줄였다"}],
        },
    ),
    article(
        "A3",
        "마바솔루션, 장비사 통해 검사 모듈 공급 확대",
        "마바솔루션은 장비사 사피엔장비를 통해 이차전지 검사 모듈을 공급한다고 밝혔다. "
        "회사 측은...",
        body=(
            "마바솔루션은 장비사 사피엔장비를 통해 이차전지 검사 모듈을 공급한다고 밝혔다.\n"
            "사피엔장비는 현장에 맞춘 조명 설계를 맡는다.\n"
            "이번 모듈은 기존 라인에 추가로 설치할 수 있도록 설계됐다.\n"
            "회사 측은 올해 공급처를 늘릴 계획이다."
        ),
        body_status="ok",
        question_id="G3",
        candidates={
            "mentions": [("마바솔루션", "supplier"), ("사피엔장비", "equipment_maker")],
            "claims": [
                {
                    "exact_text": "현장에 맞춘 조명 설계를 맡는다",
                    "owner_text": "사피엔장비",
                    "product_text": "",
                }
            ],
            "relations": [
                {
                    "exact_clause": "마바솔루션은 장비사 사피엔장비를 통해 이차전지 검사 모듈을 공급한다",
                    "subject_text": "마바솔루션",
                    "object_text": "사피엔장비",
                    "relation_hint": "supply",
                }
            ],
        },
    ),
    article(
        "A4",
        "자차로봇, 비전 AI 품질 검사 시스템 구축",
        "자차로봇은 자회사 자차비전의 베트남 현지 법인 생산라인에 AI 비전 검사 시스템을 "
        "구축했다고 밝혔다.",
        question_id="G1",
        candidates={
            "mentions": [("자차로봇", "supplier"), ("자차비전", "adopter")],
            "relations": [
                {
                    "exact_clause": "자차로봇은 자회사 자차비전의 베트남 현지 법인 생산라인에 "
                    "AI 비전 검사 시스템을 구축했다",
                    "subject_text": "자차로봇",
                    "object_text": "자차비전",
                    "relation_hint": "affiliate_site",
                }
            ],
        },
    ),
    article(
        "A5",
        "카타비전, 타파전자와 비전 검사장비 공급 계약",
        "카타비전은 타파전자와 비전 검사장비 공급 계약을 체결했다. 계약 규모는 31억원이다. "
        "장비는 내년 양산라인에 투입될 예정이다...",
        question_id="E1",
        candidates={
            "mentions": [("카타비전", "supplier"), ("타파전자", "adopter")],
            "relations": [
                {
                    "exact_clause": "카타비전은 타파전자와 비전 검사장비 공급 계약을 체결했다",
                    "subject_text": "카타비전",
                    "object_text": "타파전자",
                    "relation_hint": "contract",
                }
            ],
            "metrics": [{"exact_text": "계약 규모는 31억원이다"}],
        },
    ),
    article(
        "A6",
        "라마AI, 사바전자와 AI 외관검사 업무협약",
        "라마AI는 사바전자와 AI 외관검사 공급을 위한 업무협약을 맺었다고 밝혔다.",
        question_id="G1",
        candidates={
            "mentions": [("라마AI", "supplier"), ("사바전자", "adopter")],
            "relations": [
                {
                    "exact_clause": "라마AI는 사바전자와 AI 외관검사 공급을 위한 업무협약을 맺었다",
                    "subject_text": "라마AI",
                    "object_text": "사바전자",
                    "relation_hint": "plan",
                }
            ],
        },
    ),
    article(
        "A7",
        "부산 제조업, AI와 만나려면",
        "한 부품 업체는 비전 검사기를 도입했다가 전면 철수한 경험이 있다. 공정 시간이 오히려...",
        question_id="R1",
        candidates={"mentions": [("한 부품 업체", "adopter")]},
    ),
    article(
        "A8",
        "가나비전, 정상 이미지 검사 솔루션 고도화",
        "가나비전 측은 정상 이미지 방식에도 불량 데이터 확보가 여전히 필요하다고 설명했다. "
        "회사는...",
        candidates={
            "mentions": [("가나비전", "supplier")],
            "claims": [
                {
                    "exact_text": "정상 이미지 방식에도 불량 데이터 확보가 여전히 필요하다",
                    "owner_text": "가나비전",
                    "product_text": "",
                }
            ],
        },
    ),
    article(
        "A9",
        "파하AI, '제품 변경 셋업 부담 줄인' 검사 플랫폼 출시",
        "파하AI가 신제품을 공개했다. 행사에는...",
        candidates={
            "mentions": [("파하AI", "supplier")],
            "claims": [
                {
                    "exact_text": "제품 변경 셋업 부담 줄인",
                    "owner_text": "파하AI",
                    "product_text": "",
                }
            ],
        },
    ),
    article(
        "A10",
        "가나비전, 해외 전시회서 AI 비전검사 솔루션 선보여",
        "가나비전은 독일 전시회에서 AI 비전검사 솔루션을 선보였다...",
        fail=True,
    ),
    article(
        "A11",
        "사바전자, 검사 자동화 확대",
        "사바전자는 가나비전의 AI 검사 장비를 도입했다고 밝혔다.",
        question_id="M2",
        candidates={
            "mentions": [("사바전자", "supplier", "s1"), ("가나비전", "supplier")],
            "relations": [
                {
                    "exact_clause": "사바전자는 가나비전의 AI 검사 장비를 도입했다",
                    "subject_text": "사바전자",
                    "object_text": "가나비전",
                    "relation_hint": "install",
                }
            ],
        },
    ),
]


def source_id(key: str) -> str:
    return make_source_id(next(a["url"] for a in WORLD if a["key"] == key))


def naver_item(a: dict) -> dict:
    return {
        "title": a["title"],
        "description": a["snippet"],
        "originallink": a["url"],
        "link": a["url"].replace("news.example.com", "n.news.naver.com"),
        "pubDate": a["pub"],
    }


def html_page(a: dict) -> str:
    paragraphs = "".join(f"<p>{line}</p>" for line in a["body"].splitlines())
    return (
        "<html><body><nav>메뉴 홈</nav>"
        f"<div class='article_body'>{paragraphs}</div>"
        "<footer>저작권자 가상</footer></body></html>"
    )


class FakeResponse:
    def __init__(self, status=200, body=b"", content_type="text/html; charset=utf-8"):
        self.status_code = status
        self.content = body
        self.headers = {"Content-Type": content_type}

    def iter_content(self, size):
        for i in range(0, len(self.content), size):
            yield self.content[i : i + size]


class FakeHttp:
    """robots.txt는 모두 404(허용), 기사별 body_status에 맞춰 응답한다."""

    def __init__(self, world=WORLD):
        self.by_url = {a["url"]: a for a in world}
        self.calls = []

    def __call__(self, url, headers=None, timeout=None, stream=False):
        self.calls.append(url)
        if url.endswith("/robots.txt"):
            return FakeResponse(404)
        a = self.by_url[url]
        if a["body_status"] == "ok":
            return FakeResponse(body=html_page(a).encode("utf-8"))
        if a["body_status"] == "http_403":
            return FakeResponse(403)
        return FakeResponse(404)


class FakeSearch:
    """질의와 무관하게 질문 ID가 같은 가상 기사를 돌려준다(없으면 빈 결과)."""

    def __init__(self, world=WORLD, plan_questions=None):
        self.world = world
        self.plan_questions = plan_questions or {}
        self.calls = []

    def __call__(self, query, display, start, sort):
        self.calls.append(query)
        question = self.plan_questions.get(query)
        items = [naver_item(a) for a in self.world if a["question_id"] == question]
        page = items[start - 1 : start - 1 + display]
        return {"total": len(items), "items": page}


class FakeLLM:
    """입력 문장에서 후보 구절이 처음 나오는 문장 ID를 찾아 응답을 만든다."""

    def __init__(self, world=WORLD):
        self.by_source = {make_source_id(a["url"]): a for a in world}
        self.calls = []

    def __call__(self, system, user, schema):
        payload = json.loads(user)
        sid = payload["source_id"]
        self.calls.append(sid)
        a = self.by_source[sid]
        if a["fail"]:
            return {"content": "not json", "model": "fake", "finish_reason": "stop"}
        sentences = payload["sentences"]

        def where(text, override=None):
            if override:
                return override
            return next((s["id"] for s in sentences if text in s["text"]), None)

        out = {
            "source_id": sid,
            "mentions": [],
            "claims": [],
            "relations": [],
            "metrics": [],
            "unresolved_fields": [],
        }
        candidates = a["candidates"]
        for mention in candidates.get("mentions", []):
            sentence_id = where(mention[0], mention[2] if len(mention) > 2 else None)
            if sentence_id:
                out["mentions"].append(
                    {
                        "sentence_id": sentence_id,
                        "exact_text": mention[0],
                        "candidate_role": mention[1],
                    }
                )
        for kind, key in (
            ("claims", "exact_text"),
            ("relations", "exact_clause"),
            ("metrics", "exact_text"),
        ):
            for item in candidates.get(kind, []):
                sentence_id = where(item[key])
                if sentence_id:
                    out[kind].append({"sentence_id": sentence_id, **item})
        return {
            "content": json.dumps(out, ensure_ascii=False),
            "model": "gpt-4o-mini-fake",
            "system_fingerprint": "fp_fake",
            "finish_reason": "stop",
            "usage": {"prompt_tokens": 100, "completion_tokens": 50},
        }


def records(world=WORLD, profile=None) -> list[dict]:
    """collect 단계가 만든 것과 같은 형식의 채택 기사 레코드."""
    profile = profile or load_profile("SF-02")
    out = []
    for rank, a in enumerate(world, 1):
        sid = make_source_id(a["url"])
        text = f"{a['title']}\n{a['snippet']}"
        out.append(
            {
                "source_id": sid,
                "url": a["url"],
                "naver_link": "",
                "publisher": "news.example.com",
                "title": a["title"],
                "snippet": a["snippet"],
                "published_at": "2026-10-20T09:00:00+09:00",
                "published_date": 20261020,
                "collected_at": FIXED_NOW.isoformat(),
                "query_id": f"q-{a['key']}",
                "question_id": a["question_id"],
                "group": "fixture",
                "round": 0,
                "rank": rank,
                "dup_group": sid,
                "industry_scope": industry_scope(text, profile),
            }
        )
    return out


def processed(world=WORLD, profile=None, reviews=None):
    """가상 기사로 본문 → 추출 → Anchor → 판정까지 수행한 결과."""
    profile = profile or load_profile("SF-02")
    bodies, statuses = {}, {}
    for a in world:
        sid = make_source_id(a["url"])
        statuses[sid] = a["body_status"]
        if a["body_status"] == "ok":
            bodies[sid] = extract_article_text(html_page(a))
    llm = FakeLLM(world)
    result = process_articles(
        records(world, profile), bodies, statuses, Extractor(profile, llm), profile
    )
    evidence, entities, approved_in = evaluate_evidence(result["anchors"], reviews)
    articles = {meta["source_id"]: meta for meta in result["articles"]}
    return {
        **result,
        "evidence": evidence,
        "entities": entities,
        "approved_in": approved_in,
        "articles_by_id": articles,
        "llm": llm,
        "profile": profile,
    }
