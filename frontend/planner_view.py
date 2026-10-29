"""시장성 화면의 '사업기획 근거 비교' 영역.

저장된 자료집을 replay해 경쟁 주장 비교표·공급 관계·가정과 다음 질문·가격 조건·자료 범위를 보여준다.
화면은 저장된 의미 결과만 읽으며 LLM을 다시 부르지 않는다. 새 자료집 만들기(refresh)는
IDEALENS_PLANNER_REFRESH=1과 OpenAI·NAVER 키가 있는 로컬 실행에서만 켠다.
"""

import html
import os
import re
import threading
import time
from decimal import Decimal, InvalidOperation
from math import ceil
from uuid import uuid4

import altair as alt
import streamlit as st

from frontend.workflow import PLANNER_JOBS, PLANNER_JOBS_LOCK
from src.planner import store
from src.planner.config import available_profiles
from src.planner.matrix import STATUS_LABELS, STATUS_SYMBOLS, UNKNOWN_LABELS
from src.planner.pricing import EXAMPLE, FIELDS, LABELS, NOT_EVIDENCE, compute_price
from src.planner.relations import relation_label
from src.planner.report_text import (
    ASSUMPTION_LABELS,
    QUESTION_LABELS,
    semantic_to_markdown,
)

REFRESH_ENV = "IDEALENS_PLANNER_REFRESH"
_SAFE_URL = re.compile(r"https?://[^\s<>\"']+")
LAYER_LABELS = {
    "stored_snippet": "검색 제목·요약(저장 자료)",
    "reviewed_body": "본문(자동 수집)",
    "user_input": "사용자 입력",
    "scenario": "설명용 가정",
}
KIND_LABELS = {
    "reported_event": "보도된 사건",
    "supplier_claim": "공급사 주장",
    "analyst_interpretation": "분석 해석(규칙 템플릿)",
    "user_input": "사용자 입력",
    "scenario": "설명용 가정",
}
SCOPE_LABELS = {
    "direct": "직접(2차전지·전자부품 등)",
    "adjacent": "인접 산업",
    "unknown": "미확인",
}
COUNTERPART_LABELS = {
    "named": "실명 도입처",
    "anonymous": "익명 도입처(사건별)",
    "channel": "장비사·SI",
}
SOURCE_OPTIONS = ["미입력", "사용자 입력", "견적", "내부 원가", "가정"]
PRICE_LABELS = {
    "C": "프로젝트 직접비 C (만원)",
    "m": "목표 이익률 m (%)",
    "B": "고객 연간 추가 순효과 B (만원/년)",
    "I": "고객 별도 초기비용 I (만원)",
    "T": "허용 회수기간 T (개월)",
}


def safe_url(url: str | None) -> str | None:
    if url and _SAFE_URL.fullmatch(url.strip()):
        return url.strip()
    return None


def md(text) -> str:
    """외부 텍스트를 마크다운 한 줄로 안전하게 표시한다(HTML·링크 해석 차단)."""
    value = html.escape(" ".join(str(text or "").split()), quote=False)
    return re.sub(r"([\\`*_{}\[\]()#+\-.!|>~$])", r"\\\1", value)


def refresh_enabled() -> bool:
    return (
        os.getenv(REFRESH_ENV, "").strip() == "1"
        and bool(os.getenv("OPENAI_API_KEY", "").strip())
        and bool(os.getenv("NAVER_CLIENT_ID", "").strip())
        and bool(os.getenv("NAVER_CLIENT_SECRET", "").strip())
    )


def _idea(draft):
    if draft is None:
        return None
    try:
        return draft.to_structured_idea()
    except (ValueError, AttributeError):
        return None


def _report(path):
    """replay 결과를 세션에 보관한다(경로·최신 revision이 같으면 다시 계산하지 않음)."""
    from src.services.planner_service import replay

    key = (str(path), store.latest_revision(path))
    cache = st.session_state.setdefault("planner_reports", {})
    if key not in cache:
        cache.clear()
        cache[key] = replay(path)
    return cache[key]


def render_planner_section(area_id, draft, root=None) -> None:
    st.subheader("사업기획 근거 비교")
    st.caption(
        "뉴스에서 확인한 공급사 주장·공급 관계와 회사가 입력한 가정을 나란히 놓고 차별 주장·공급 방식·"
        "판매 경로·가격 조건·다음 조사를 정합니다. 시장 규모·점유율·성공 확률은 계산하지 않습니다."
    )
    profiles = available_profiles()
    if area_id and area_id not in profiles:
        st.info(
            f"{area_id} 분야는 구매 기준·질문 템플릿이 아직 정의되지 않아 비교표를 만들지 않습니다."
        )
        return
    area = area_id
    if not area:
        area = st.selectbox(
            "비교 기준 분야",
            profiles,
            key="planner_area",
            help="특허 분야가 자동이면 비교 기준(구매 기준·질문)을 정할 분야를 고릅니다.",
        )
    idea = _idea(draft)
    digest = store.idea_hash(idea, area) if idea else ""
    root = root or store.runs_root()
    runs = store.list_runs(root, area)
    _render_refresh(area, idea, root, runs, digest)
    if not runs:
        st.info(
            "저장된 자료집이 없습니다. 자료집이 있어야 경쟁 주장·공급 관계를 표시합니다. "
            "근거가 없다는 뜻이 아닙니다."
        )
        return
    runs.sort(key=lambda r: (r["manifest"].idea_hash != digest, r["manifest"].run_id))
    labels = [
        f"{r['manifest'].run_id} · {'현재 아이디어' if r['manifest'].idea_hash == digest else '입력 아이디어와 다름'}"
        f" · {r['manifest'].idea_title}"
        for r in runs
    ]
    index = st.selectbox(
        "자료집", range(len(runs)), format_func=lambda i: labels[i], key="planner_run"
    )
    path = runs[index]["path"]
    try:
        report = _report(path)
    except (store.RunIntegrityError, OSError, ValueError) as exc:
        st.error(f"자료집을 읽지 못했습니다: {exc}")
        return
    if not report["match"]:
        st.error(
            "저장된 의미 결과와 재계산 결과의 해시가 다릅니다. 이 자료집의 결과를 그대로 신뢰하지 마세요."
        )
    if runs[index]["manifest"].idea_hash != digest:
        st.warning(
            "현재 입력과 다른 아이디어로 만든 자료집입니다. 당사 주장·가정은 자료집에 저장된 입력을 씁니다."
        )
    if report["rule_drift"]:
        st.caption(
            "현재 규칙·프로필과 다른 버전으로 만든 자료집입니다. 결과는 저장 당시 규칙 기준입니다."
        )
    semantic = report["semantic"]
    tabs = st.tabs(
        ["경쟁 주장 비교", "공급 관계·다음 확인", "가격 조건", "자료집·재현"]
    )
    with tabs[0]:
        render_matrix(semantic)
    with tabs[1]:
        render_relations(semantic)
    with tabs[2]:
        render_price(report)
    with tabs[3]:
        render_dataset(report)


# 경쟁 주장 비교 --------------------------------------------------------------
def _cell_text(cell) -> str:
    text = f"{STATUS_SYMBOLS[cell.status]} {STATUS_LABELS[cell.status]}"
    if cell.candidate_evidence_ids:
        text += " · 후보"
    return text


def _cell_label(semantic, cell) -> str:
    rows = {r.row_id: r.label for r in semantic.rows}
    criteria = {c["id"]: c["label"] for c in semantic.criteria}
    return f"{rows[cell.row_id]} × {criteria[cell.criterion_id]} · {STATUS_LABELS[cell.status]}"


def render_matrix(semantic) -> None:
    import pandas as pd

    if semantic.insights:
        st.markdown("**비교 해석** · 분석 해석(규칙 템플릿)이며 사실 확인이 아닙니다.")
        for insight in semantic.insights:
            st.markdown(f"- {md(insight.text)}")
            st.caption(
                f"다음 질문 {', '.join(insight.next_question_ids)} · 한계: {insight.limits}"
            )
    criteria = semantic.criteria
    cells = {(c.row_id, c.criterion_id): c for c in semantic.cells}
    informative = [
        row
        for row in semantic.rows
        if row.kind == "our_claim"
        or any(cells[(row.row_id, c["id"])].status != "unknown" for c in criteria)
    ]
    hidden = len(semantic.rows) - len(informative)
    show_all = hidden and st.checkbox(
        f"미확인만 있는 공급사 {hidden}곳도 표시",
        key="planner_show_all",
        help="세 기준 모두 자료집에서 대응 주장을 찾지 못한 공급사입니다. 기능이 없다는 뜻이 아닙니다.",
    )
    rows = semantic.rows if show_all else informative
    table = pd.DataFrame(
        [
            {"공급사·제품": row.label}
            | {c["label"]: _cell_text(cells[(row.row_id, c["id"])]) for c in criteria}
            for row in rows
        ]
    )
    st.caption(
        "● 대응 주장 명시 · ◐ 설명 불완전 · ○ 미확인(기능이 없다는 뜻 아님) · ⇄ 상충. "
        "경쟁력 점수나 성능 순위가 아닙니다. 칸을 누르거나 아래 목록에서 골라 근거를 확인하세요."
    )
    ordered = [(r.row_id, c["id"]) for r in rows for c in criteria]
    event = st.dataframe(
        table,
        hide_index=True,
        width="stretch",
        on_select="rerun",
        selection_mode="single-cell",
        key="planner_matrix",
    )
    picked = getattr(getattr(event, "selection", None), "cells", None) or []
    if picked:
        row_index, column = picked[0]
        names = {c["label"]: c["id"] for c in criteria}
        if column in names and 0 <= row_index < len(rows):
            target = ordered.index((rows[row_index].row_id, names[column]))
            if st.session_state.get("planner_matrix_last") != target:
                st.session_state["planner_matrix_last"] = target
                st.session_state["planner_cell"] = target
    if not 0 <= st.session_state.get("planner_cell", 0) < len(ordered):
        st.session_state["planner_cell"] = 0
    choice = st.selectbox(
        "근거를 볼 칸",
        range(len(ordered)),
        format_func=lambda i: _cell_label(semantic, cells[ordered[i]]),
        key="planner_cell",
    )
    render_cell_detail(semantic, cells[ordered[choice]])
    pending = [
        e
        for e in semantic.entities
        if not e.approved and "supplier" in e.role.split("|")
    ]
    if pending:
        with st.expander(f"공급사 후보(규칙 미승인) {len(pending)}곳"):
            for entity in pending:
                st.write(
                    f"- {entity.name} · 사유: {', '.join(entity.reasons) or '미확인'}"
                )
    unassigned = [
        e
        for e in semantic.evidence
        if e.kind == "claim" and e.review_status == "approved" and not e.criteria
    ]
    if unassigned:
        st.caption(
            f"구매 기준에 배정되지 않은 승인 주장 {len(unassigned)}건은 비교표에 넣지 않았습니다."
        )


def _evidence_block(semantic, evidence_id, sources) -> None:
    item = next(e for e in semantic.evidence if e.evidence_id == evidence_id)
    source = sources.get(item.source_id, {})
    st.markdown(f"> {md(item.span.text)}")
    st.caption(
        f"{KIND_LABELS[item.statement_kind]} · {LAYER_LABELS[item.evidence_layer]} · "
        f"{source.get('publisher', '')} · 발행 {str(source.get('published_at') or '미확인')[:10]} · "
        f"수집 {str(source.get('collected_at') or '')[:10]} · 적용 산업 "
        f"{SCOPE_LABELS.get(item.industry_scope, '미확인')}"
        + (f" · 표지 {', '.join(item.markers)}" if item.markers else "")
    )
    url = safe_url(source.get("url"))
    if url:
        st.link_button("원문 확인 ↗", url)


def render_cell_detail(semantic, cell) -> None:
    sources = {s["source_id"]: s for s in semantic.sources}
    questions = {q.question_id: q for q in semantic.questions}
    rows = {r.row_id: r for r in semantic.rows}
    row = rows[cell.row_id]
    with st.container(border=True):
        st.markdown(f"**{md(_cell_label(semantic, cell))}**")
        if row.kind == "our_claim":
            origin = (
                "AI 가설(사용자 확인 전)"
                if row.input_origin == "ai_hypothesis"
                else "사용자 입력"
            )
            st.caption(
                f"{origin} · 아이디어 차별점 입력을 구매 기준 사전으로 대조한 결과입니다."
            )
        elif row.level == "company":
            st.caption("제품명이 확인되지 않아 회사 수준으로 비교합니다.")
        if cell.status == "unknown":
            st.info(
                f"미확인: {UNKNOWN_LABELS.get(cell.unknown_reason, cell.unknown_reason)}. "
                "기능이 없다는 뜻이 아닙니다."
            )
            if cell.reasons:
                st.caption("사유별 기사 수: " + ", ".join(cell.reasons))
        if cell.status == "partial" and cell.reasons:
            st.caption("설명 불완전 사유: " + ", ".join(cell.reasons))
        if cell.scope_note:
            st.caption(cell.scope_note)
        if cell.article_count is not None:
            st.caption(
                f"근거 기사 {cell.article_count}건 · 전재 묶음 {cell.dup_group_count}개 "
                "(같은 보도자료 전재는 독립 확인이 아닙니다)"
            )
        supporting = [
            e
            for e in cell.evidence_ids
            if next(x for x in semantic.evidence if x.evidence_id == e).source_id
            not in cell.conflicting_source_ids
        ]
        for evidence_id in supporting[:4]:
            _evidence_block(semantic, evidence_id, sources)
        conflicting = [e for e in cell.evidence_ids if e not in supporting]
        if conflicting:
            st.markdown("**상충 근거**")
            for evidence_id in conflicting[:4]:
                _evidence_block(semantic, evidence_id, sources)
        if cell.evidence_ids:
            st.caption("원문 구절의 존재를 확인했으며, 의미 판정은 규칙 기준입니다.")
        question = questions.get(cell.next_question_id)
        if question:
            st.markdown(
                f"**다음 질문 {question.question_id}** · {md(question.question)}"
            )
            st.caption(
                f"{QUESTION_LABELS[question.status]}"
                + (
                    f" · 중단 사유 {question.stop_reason}"
                    if question.stop_reason
                    else ""
                )
                + (f" · 질의 예: {question.queries[0]}" if question.queries else "")
            )
        if cell.candidate_evidence_ids:
            with st.expander(f"주체 미확정 후보 {len(cell.candidate_evidence_ids)}건"):
                for evidence_id in cell.candidate_evidence_ids[:5]:
                    _evidence_block(semantic, evidence_id, sources)


# 공급 관계·다음 확인 -----------------------------------------------------------
def relation_dot(semantic) -> str:
    """확정 간선만 DOT로 만든다. 후보 간선·간선 두께는 쓰지 않는다."""
    shapes = {
        "supplier": "box",
        "adopter": "ellipse",
        "anonymous_adopter": "ellipse",
        "channel": "diamond",
        "product": "note",
    }
    approved = [e for e in semantic.edges if e.status == "approved"]
    used = {e.supplier_id for e in approved} | {e.counterpart_id for e in approved}

    def quote(text):
        return '"' + str(text).replace("\\", "\\\\").replace('"', '\\"') + '"'

    lines = ["digraph G {", "rankdir=LR;", 'node [fontname="sans-serif"];']
    for node in semantic.nodes:
        if node.node_id not in used:
            continue
        style = ', style="dashed"' if node.kind == "anonymous_adopter" else ""
        lines.append(
            f"{quote(node.node_id)} [label={quote(node.label)}, shape={shapes[node.kind]}{style}];"
        )
    for edge in approved:
        label = relation_label(edge.relation_type) + (
            " · 계열 적용" if edge.affiliate else ""
        )
        style = ', style="dotted"' if edge.affiliate else ""
        lines.append(
            f"{quote(edge.supplier_id)} -> {quote(edge.counterpart_id)} "
            f"[label={quote(label)}{style}];"
        )
    lines.append("}")
    return "\n".join(lines)


def render_relations(semantic) -> None:
    counts = semantic.relation_counts
    nodes = {n.node_id: n.label for n in semantic.nodes}
    sources = {s["source_id"]: s for s in semantic.sources}
    st.caption(
        f"외부 공급·계약 보도 {counts.get('external_transaction_reports', 0)}건(전재 묶음 기준, 유상 여부 미확인) · "
        f"실명 외부 도입처 {counts.get('named_external_adopters', 0)}곳 · "
        f"익명 사례 {counts.get('anonymous_cases', 0)}건 · "
        f"계열 적용 제외 {counts.get('affiliate_excluded', 0)}건 · "
        f"장비사·SI 경로 {counts.get('channel_relations', 0)}건 · "
        f"계획·실증 {counts.get('plan_or_poc_only', 0)}건 · "
        f"관계 서술 없는 동시 언급 {counts.get('co_mentions_without_relation', 0)}건(연결하지 않음)"
    )
    approved = [e for e in semantic.edges if e.status == "approved"]
    if approved:
        st.graphviz_chart(relation_dot(semantic), width="stretch")
        st.caption(
            "관계 동사가 있는 확정 관계만 그렸습니다. 연결 수는 경쟁력·시장 지배력이 아니며 "
            "선 굵기는 금액을 뜻하지 않습니다. 점선 상자는 사건별 익명 도입처, 점선 화살표는 계열 적용입니다."
        )
        rows = [
            {
                "공급사": nodes.get(e.supplier_id, e.supplier_id),
                "상대": nodes.get(e.counterpart_id, e.counterpart_id),
                "상대 유형": COUNTERPART_LABELS[e.counterpart_kind],
                "관계": relation_label(e.relation_type),
                "계열 적용": "예" if e.affiliate else "",
                "사건일": e.event_at
                or (e.event_at_text and f"원문: {e.event_at_text}")
                or "미확인",
                "기사 수": len(e.source_ids),
            }
            for e in approved
        ]
        st.dataframe(rows, hide_index=True, width="stretch")
        choice = st.selectbox(
            "근거를 볼 관계",
            range(len(approved)),
            format_func=lambda i: f"{rows[i]['공급사']} → {rows[i]['상대']} · {rows[i]['관계']}",
            key="planner_edge",
        )
        for evidence_id in approved[choice].evidence_ids[:3]:
            _evidence_block(semantic, evidence_id, sources)
    else:
        st.info("확정된 공급 관계가 없습니다. 거래가 없다는 뜻이 아닙니다.")
    candidates = [e for e in semantic.edges if e.status == "candidate"]
    if candidates:
        with st.expander(
            f"규칙을 통과하지 못한 관계 후보 {len(candidates)}건(그래프에 넣지 않음)"
        ):
            for edge in candidates:
                st.write(
                    f"- {md(nodes.get(edge.supplier_id, edge.supplier_id))} → "
                    f"{md(nodes.get(edge.counterpart_id, edge.counterpart_id))} · "
                    f"사유 {', '.join(edge.reasons)}"
                )
    st.markdown("#### 사업 가정 → 근거 → 영향받는 선택 → 다음 질문")
    questions = {q.question_id: q for q in semantic.questions}
    for link in semantic.assumptions:
        with st.container(border=True):
            st.markdown(f"**{link.label}** · {ASSUMPTION_LABELS[link.status]}")
            st.caption(f"가정(입력): {link.statement}")
            st.write(f"영향받는 선택: {link.affected_choice}")
            if link.options:
                st.caption("비교할 대안: " + " / ".join(link.options))
            st.caption(
                f"지지 근거 {len(link.supporting_ids)}건 · 반대 근거 {len(link.counter_ids)}건 · {link.note}"
            )
            for qid in link.next_question_ids:
                q = questions.get(qid)
                if q:
                    st.markdown(
                        f"- {qid} {md(q.question)} — {QUESTION_LABELS[q.status]}"
                        + (f" · {q.stop_reason}" if q.stop_reason else "")
                    )
            evidence_ids = link.counter_ids[:2] + link.supporting_ids[:2]
            if evidence_ids:
                with st.expander("근거 구절 보기"):
                    for evidence_id in evidence_ids:
                        _evidence_block(semantic, evidence_id, sources)
    st.markdown("#### 추가 도표의 데이터 요건")
    for chart in semantic.followup_charts:
        if chart.available:
            st.success(f"{chart.label}: 표시 조건 충족")
        else:
            st.caption(
                f"{chart.label}: 표시 불가 — 누락 {'; '.join(chart.missing)} → 확보 방법 "
                f"{'; '.join(chart.how_to_obtain)}"
            )
    with st.expander("질문 은행 판정 전체"):
        st.dataframe(
            [
                {
                    "질문": q.question_id,
                    "결정": q.decision,
                    "상태": QUESTION_LABELS[q.status],
                    "중단 사유": q.stop_reason,
                    "질의 예": q.queries[0] if q.queries else "",
                }
                for q in semantic.questions
            ],
            hide_index=True,
            width="stretch",
        )


# 가격 조건 ---------------------------------------------------------------------
def _to_fraction(percent: str) -> str | None:
    text = (percent or "").strip().replace(",", "")
    if not text:
        return None
    try:
        return format(Decimal(text) / Decimal(100), "f")
    except InvalidOperation:
        return text


def price_chart(result):
    """공급자 하한·고객 상한·교집합 3줄. 계산은 Decimal 결과를 쓰고 좌표만 실수로 변환한다."""
    floor = Decimal(result.floor_display)
    ceiling = Decimal(result.ceiling_display)
    cost = Decimal(result.inputs["C"])
    domain = Decimal(
        ceil(float(max(Decimal(1000), floor, ceiling, cost) * Decimal("1.12") / 100))
        * 100
    )
    rows = [
        {"구분": "공급자 조건(하한 이상)", "시작": float(floor), "끝": float(domain)},
        {
            "구분": "고객 회수조건(상한 이하)",
            "시작": 0.0,
            "끝": float(max(ceiling, Decimal(0))),
        },
    ]
    if result.status == "overlap":
        rows.append(
            {"구분": "두 조건의 교집합", "시작": float(floor), "끝": float(ceiling)}
        )
    description = f"공급자 하한 {result.floor_display}만원, 고객 회수 상한 {result.ceiling_display}만원, " + (
        "교집합 있음" if result.status == "overlap" else "교집합 없음"
    )
    return (
        alt.Chart(alt.Data(values=rows))
        .mark_bar(size=18)
        .encode(
            y=alt.Y("구분:N", sort=None, title=None),
            x=alt.X(
                "시작:Q",
                title="판매가 (만원)",
                scale=alt.Scale(domain=[0, float(domain)]),
            ),
            x2="끝:Q",
            color=alt.Color(
                "구분:N",
                legend=None,
                scale=alt.Scale(
                    domain=[
                        "공급자 조건(하한 이상)",
                        "고객 회수조건(상한 이하)",
                        "두 조건의 교집합",
                    ],
                    range=["#4a78a8", "#d6a42c", "#47846d"],
                ),
            ),
            tooltip=["구분:N", "시작:Q", "끝:Q"],
        )
        .properties(height=150, description=description)
    )


def render_price(report) -> None:
    from src.services.planner_service import review

    st.caption(
        "판매 단위: 초기 구축 프로젝트 1건 · 금액 단위 만원 · 하한은 1만원 단위 올림, 상한은 내림. "
        "구독형 현금흐름은 이 산식에 넣지 않습니다(별도 모델 필요)."
    )
    mode = st.radio(
        "입력 방식",
        ["actual", "example"],
        format_func=lambda m: "실제 입력" if m == "actual" else "예시(설명용 가정)",
        horizontal=True,
        key="planner_price_mode",
    )
    saved = (report["revision_payload"].get("user_inputs") or {}).get("price") or {}
    values, provenance = {}, {}
    if mode == "example":
        st.warning(
            "예시 모드: 설명용 가정값이며 실제 사업 수치가 아닙니다. 저장하지 않습니다."
        )
        cols = st.columns(5)
        for col, field in zip(cols, FIELDS):
            shown = (
                str(Decimal(EXAMPLE[field]) * 100) if field == "m" else EXAMPLE[field]
            )
            col.text_input(
                PRICE_LABELS[field],
                value=shown,
                disabled=True,
                key=f"planner_example_{field}",
            )
        result = compute_price({}, mode="example")
    else:
        saved_values = saved.get("values", {})
        cols = st.columns(5)
        raw = {}
        for col, field in zip(cols, FIELDS):
            default = saved_values.get(field) or ""
            if field == "m" and default:
                default = format(Decimal(default) * 100, "f")
            raw[field] = col.text_input(
                PRICE_LABELS[field], value=default, key=f"planner_price_{field}"
            )
            source = col.selectbox(
                "출처",
                SOURCE_OPTIONS,
                index=SOURCE_OPTIONS.index(
                    saved.get("provenance", {}).get(field, {}).get("source", "미입력")
                ),
                key=f"planner_source_{field}",
            )
            if raw[field].strip():
                provenance[field] = {"source": source}
        values = {
            f: (_to_fraction(raw[f]) if f == "m" else raw[f].strip() or None)
            for f in FIELDS
        }
        result = compute_price(values, mode="actual", provenance=provenance)
    if result.status == "withheld":
        st.info(
            "계산 보류: "
            + ", ".join(LABELS[f] for f in result.missing)
            + " 입력이 필요합니다. 빈 값은 뉴스 수치로 채우지 않습니다."
        )
    elif result.status == "invalid":
        st.error("입력 오류: " + "; ".join(result.errors))
    else:
        if result.status == "overlap":
            st.success(
                f"두 조건이 겹치는 판매가: {result.floor_display}~{result.ceiling_display}만원"
            )
        elif result.status == "no_overlap":
            st.warning(
                f"공급자 하한 {result.floor_display}만원이 고객 회수 상한 {result.ceiling_display}만원보다 큽니다. "
                "가격 인상만으로 해결되지 않으므로 대상 공정·공급 범위·구축비·고객 효과·회수기간을 바꿔 비교하세요."
            )
        else:
            st.warning(
                "고객 회수 상한이 0 이하입니다. 현재 가정에서는 양수 판매가가 성립하지 않습니다."
            )
        st.altair_chart(price_chart(result), width="stretch")
        st.caption(
            f"연속값: 하한 {result.floor}만원 · 상한 {result.ceiling}만원. 다른 조건이 같을 때 필요한 고객 "
            f"연간 순효과 {result.required_benefit}만원(1만원 표시 기준 {result.required_benefit_display}만원)"
            + (
                f" · 상한을 지킬 때 최대 직접비 {result.max_direct_cost}만원"
                if result.max_direct_cost
                else ""
            )
        )
    st.caption(NOT_EVIDENCE)
    if mode == "actual" and st.button(
        "입력값 저장(검토 기록 추가)", key="planner_price_save"
    ):
        if result.status == "invalid":
            st.error("입력 오류를 고친 뒤 저장하세요.")
        else:
            rev, _ = review(
                report["path"],
                price={"values": values, "provenance": provenance},
                note="가격 조건 입력",
            )
            st.session_state.pop("planner_reports", None)
            st.success(f"검토 기록 {rev}번으로 저장했습니다.")


# 자료집·재현 -------------------------------------------------------------------
def render_dataset(report) -> None:
    semantic = report["semantic"]
    manifest = report["manifest"]
    counts = semantic.counts
    st.caption(
        f"실행 {manifest.run_id} · {manifest.mode} · 기준일 {manifest.as_of} · 검토 기록 {report['revision']}번 · "
        f"재계산 해시 {'일치' if report['match'] else '불일치'} · 외부 검색·LLM 호출 없이 저장 자료로 재계산"
    )
    st.caption(
        "의미 결과(판정·근거·건수)가 같다는 확인이며 그림의 픽셀 동일성과는 별개입니다. "
        "LLM temperature 고정만으로 재현되지 않으므로 저장한 추출 결과를 다시 읽습니다."
    )
    rows = [
        ("검색 요청", counts["requests_used"]),
        ("검색 후보", counts["candidates_seen"]),
        ("채택 기사(고유)", counts["retained_articles"]),
        ("전재 묶음", counts["dup_groups"]),
        ("승인 공급사", counts["approved_suppliers"]),
        ("원문에 없는 추출 구절(폐기)", counts["span_not_found"]),
        ("후속 라운드", counts["rounds"]),
    ]
    st.dataframe(
        [{"항목": k, "값": v} for k, v in rows], hide_index=True, width="stretch"
    )
    st.caption(
        "제외 사유: "
        + (
            ", ".join(f"{k} {v}" for k, v in counts["excluded_by_reason"].items())
            or "없음"
        )
        + " · 본문: "
        + ", ".join(f"{k} {v}" for k, v in counts["body_status"].items())
        + " · 추출: "
        + ", ".join(f"{k} {v}" for k, v in counts["extraction_status"].items())
    )
    if counts["shortfalls"]:
        st.caption(
            "배분을 채우지 못한 영역(무관 기사로 채우지 않음): "
            + ", ".join(
                f"{s['label']} {s['retained']}/{s['wanted']}"
                for s in counts["shortfalls"]
            )
        )
    st.caption(
        "버전: "
        + " · ".join(f"{k} {str(v)[:24]}" for k, v in semantic.versions.items())
    )
    if report.get("diff"):
        diff = report["diff"]
        cats = diff["categories"]
        st.markdown("**이전 자료집 대비 변화**")
        st.caption(
            f"신규 근거 {len(cats['new_evidence'])}건 · 삭제/수집 실패 {len(cats['removed_or_fetch_failed'])}건 · "
            f"판정 수정 {len(cats['judgment_changed'])}건 · 입력 변경 {'있음' if cats['user_input_changed'] else '없음'} · "
            f"규칙 변경 {', '.join(cats['rule_changed']) or '없음'}"
        )
        if diff["cell_changes"]:
            st.dataframe(diff["cell_changes"], hide_index=True, width="stretch")
    st.dataframe(
        [
            {
                "제목": s["title"],
                "매체": s["publisher"],
                "발행": str(s["published_at"] or "")[:10],
                "본문": s["body_status"],
                "추출": s["extraction_status"],
                "질문": s["question_id"],
                "라운드": s["round"],
                "원문": safe_url(s["url"]) or "",
            }
            for s in semantic.sources
        ],
        hide_index=True,
        width="stretch",
        column_config={
            "원문": st.column_config.LinkColumn("원문", display_text="열기")
        },
    )
    st.download_button(
        "텍스트 보고서(Markdown) 내려받기",
        semantic_to_markdown(semantic, manifest.idea_title),
        file_name=f"planner-{manifest.run_id}.md",
        mime="text/markdown",
        key="planner_text_report",
    )


# 새 자료집 만들기 ---------------------------------------------------------------
def _worker(job_id, idea, area, parent, root):
    from src.services.planner_service import refresh

    def progress(stage, done, total):
        with PLANNER_JOBS_LOCK:
            PLANNER_JOBS[job_id].update(stage=stage, done=done, total=total)

    def cancelled():
        with PLANNER_JOBS_LOCK:
            return PLANNER_JOBS[job_id]["cancel"]

    try:
        path = refresh(
            idea, area, root=root, parent=parent, progress=progress, cancelled=cancelled
        )
        update = {"state": "done", "path": str(path)}
    except Exception as exc:  # 작업 실패는 화면 상태로 전달한다
        update = {"state": "error", "error": f"{type(exc).__name__}: {exc}"[:300]}
    with PLANNER_JOBS_LOCK:
        PLANNER_JOBS[job_id].update(update)


@st.fragment(run_every=2)
def _refresh_progress():
    job_id = st.session_state.get("planner_job")
    with PLANNER_JOBS_LOCK:
        job = dict(PLANNER_JOBS.get(job_id) or {})
    if not job:
        return
    elapsed = int(time.monotonic() - job["started"])
    if job["state"] == "running":
        st.info(
            f"자료집 생성 중 · {job.get('stage', '준비')} {job.get('done', 0)}/{job.get('total', 0)} · {elapsed}초"
        )
        if st.button("생성 취소", key="planner_cancel"):
            with PLANNER_JOBS_LOCK:
                PLANNER_JOBS[job_id]["cancel"] = True
    elif job["state"] == "done":
        st.success("새 자료집을 저장했습니다.")
        st.session_state.pop("planner_job", None)
        st.rerun(scope="app")
    else:
        st.error(f"자료집 생성 실패: {job.get('error')}")
        st.session_state.pop("planner_job", None)


def _render_refresh(area, idea, root, runs, digest) -> None:
    if not refresh_enabled():
        st.caption(
            "새 자료집 만들기는 로컬 실행에서 IDEALENS_PLANNER_REFRESH=1과 OpenAI·NAVER 키가 있을 때만 "
            "켭니다. 명령: python -m src.services.planner_service refresh --idea-id SF-02"
        )
        return
    if st.session_state.get("planner_job"):
        _refresh_progress()
        return
    if idea is None:
        st.caption("아이디어 초안이 완성되면 새 자료집을 만들 수 있습니다.")
        return
    with st.expander("새 자료집 만들기 · 외부 검색·본문 수집·API 비용 발생"):
        from src.planner.config import load_profile

        budget = load_profile(area).budget
        st.write(
            f"고유 기사 최대 {budget.max_articles}건(초기 {budget.initial_articles} + 후속 "
            f"{budget.followup_batch}×{budget.max_followup_rounds}) · NAVER 검색 최대 "
            f"{budget.max_api_requests}회 · 본문 수집 최대 {budget.max_body_fetches}건 · gpt-4o-mini "
            f"기사당 1회 + 재시도 최대 {budget.llm_retry_total}회. 기존 자료집은 덮어쓰지 않습니다."
        )
        agreed = st.checkbox(
            "외부 호출과 비용 발생을 확인했습니다", key="planner_agree"
        )
        if st.button("새 자료집 만들기", disabled=not agreed, key="planner_start"):
            parent = next(
                (r["path"] for r in runs if r["manifest"].idea_hash == digest), None
            )
            job_id = uuid4().hex
            with PLANNER_JOBS_LOCK:
                PLANNER_JOBS[job_id] = {
                    "state": "running",
                    "cancel": False,
                    "started": time.monotonic(),
                }
            threading.Thread(
                target=_worker, args=(job_id, idea, area, parent, root), daemon=True
            ).start()
            st.session_state["planner_job"] = job_id
            st.rerun()
