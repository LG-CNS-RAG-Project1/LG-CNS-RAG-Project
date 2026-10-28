"""조사 결과를 탭으로 읽고, 세션 기록과 문서 다운로드를 제공한다.

분석 내용은 파이프라인의 반환값을 그대로 사용한다. 별도 요약·평가 점수는 만들지 않는다.
"""

from copy import deepcopy
from datetime import datetime
from hashlib import sha256
import json

import streamlit as st
from frontend.report_overview import dashboard_data

from frontend.live import (
    COST_NOTE,
    LINK_LABELS,
    RUN_LOCK,
    cost_markdown,
    cost_rows_list,
    run_line,
)
from frontend.quick import report, review_rows
from frontend.workspace import cost_summary


def _criteria(link):
    return [
        {
            "검토 기준": c.criterion,
            "판단": c.assessment,
            "인용": ", ".join(c.citation_ids) or "없음",
        }
        for c in link.criteria
    ]


def _evidence(items, label, key, patent=False):
    from src.generation.report_builder import patent_location, safe_url

    if not items:
        st.info(f"{label} 근거가 없습니다. 이 영역은 판단을 보류합니다.")
        return
    selected = st.selectbox(
        f"{label} 문헌 선택 · {len(items)}건",
        range(len(items)),
        format_func=lambda i: f"{i+1}. {items[i].title}",
        key=key,
    )
    item = items[selected]
    with st.container(height=360, border=True):
        st.subheader(item.title)
        st.caption(f"{'P' if patent else 'M'}:{item.citation_id}")
        if patent:
            st.caption(
                f"{patent_location(item)} · 출원 {item.application_date or '미확인'} · 공개 {item.publication_date or '미확인'}"
            )
        else:
            st.caption(f"{item.publisher} · {item.published_at or '발행일 미확인'}")
        st.write(item.quote)
        url = safe_url(item.source_url if patent else item.url)
        if url:
            st.link_button("원문 확인 ↗", url)


def _links(items):
    if not items:
        st.info("질문별 연결 결과가 없습니다.")
        return
    index = st.selectbox(
        "검토 질문 선택",
        range(len(items)),
        format_func=lambda i: f"{items[i].question_id} · {LINK_LABELS.get(items[i].status, items[i].status)}",
    )
    item = items[index]
    st.write(item.summary)
    with st.container(height=340, border=True):
        st.dataframe(_criteria(item), hide_index=True, use_container_width=True)
    st.caption("연결·부분 연결·판단 보류는 근거 연결 상태이며 사업성 점수가 아닙니다.")


def render_live_review(s, run, key_fn, navigate):
    st.title("특허와 시장, 나란히 검토하기")
    st.caption(
        "문헌을 선택하면 해당 근거만 표시됩니다. 연결 검토에서 질문별 판단 과정을 확인하세요."
    )
    if s.pipeline_result is None:
        cached = s.analysis_sources is not None and s.analysis_key == key_fn()
        st.info("기존 조사 결과로 질문 연결만 다시 만듭니다." if cached else COST_NOTE)
        if st.button(
            "질문 연결 다시 실행" if cached else "특허·시장 조사 실행",
            type="primary",
            disabled=RUN_LOCK.locked(),
        ):
            with st.status(
                "특허·시장 근거를 조사하고 연결하는 중…", expanded=True
            ) as progress:
                st.write("완료될 때까지 기다려 주세요. 결과는 이 화면에 표시됩니다.")
                run()
                progress.update(
                    label="조사 완료" if s.pipeline_result else "실행 결과 확인 필요",
                    state="complete" if s.pipeline_result else "error",
                )
            st.rerun()
        if s.get("pipeline_error"):
            st.error(s.pipeline_error)
    else:
        r = s.pipeline_result
        a, b = st.columns(2)
        a.caption(f"{run_line('특허', r.patent_run)} · 근거 {len(r.patent.evidence)}건")
        b.caption(f"{run_line('시장', r.market_run)} · 근거 {len(r.market.evidence)}건")
        for error in r.errors:
            st.warning(error)
        sources, links = st.tabs(["특허 · 시장 근거", "질문별 연결 검토"])
        with sources:
            left, right = st.columns(2, gap="large")
            with left:
                st.subheader("특허 · 기술")
                _evidence(r.patent.evidence, "특허", "patent_source", patent=True)
            with right:
                st.subheader("시장 · 기업")
                _evidence(r.market.evidence, "시장", "market_source")
        with links:
            _links(r.links)
        go, again = st.columns([2, 1])
        go.button("종합 보고서 확인 →", type="primary", on_click=navigate, args=(4,))
        with again.popover("조사 다시 실행"):
            st.caption("새 외부 API 호출과 비용이 발생합니다.")
            if st.button("결과를 비우고 재조사 준비", key="rerun_analysis"):
                s.analysis_sources = None
                s.analysis_key = ""
                s.pipeline_result = None
                st.rerun()
    st.button("← 아이디어·질문 수정", on_click=navigate, args=(2,))


def report_payload(s):
    """가공·추가 요약 없이 기존 분석과 시연 보고서를 문서 화면 계약으로 맞춘다."""
    if s.real_mode and s.pipeline_result:
        r = s.pipeline_result
        rows = [
            {
                "질문": x.question_id,
                "연결 상태": LINK_LABELS.get(x.status, x.status),
                "기존 분석 결과": x.summary,
            }
            for x in r.links
        ]
        return {
            "title": s.research_title or r.title,
            "raw": s.raw,
            "markdown": r.markdown,
            "rows": rows,
            "patent_count": len(r.patent.evidence),
            "market_count": len(r.market.evidence),
            "demo": False,
            "dashboard": dashboard_data(r),
        }
    snap = s.report_snapshot
    if not snap:
        return None
    rows = review_rows(
        snap["raw"], snap["parts"], snap["ids"], snap["questions"], snap["links"]
    )
    return {
        "title": snap["title"] or "아이디어 조사",
        "raw": snap["raw"],
        "markdown": report(
            snap["raw"],
            snap["title"],
            snap["parts"],
            snap["ids"],
            s.saved_memo,
            snap["questions"],
            snap["links"],
        ),
        "rows": [
            {
                "질문": r["question"],
                "연결 상태": r["status"],
                "기존 분석 결과": r["reason"] or "미확인",
            }
            for r in rows
        ],
        "patent_count": sum(x["kind"] == "특허" for x in snap["sources"]),
        "market_count": sum(x["kind"] in ("시장", "기업") for x in snap["sources"]),
        "demo": True,
    }


def render_report(s, payload, archived=False):
    st.title(payload["title"])
    st.caption(
        "종합 보고서 / "
        + ("시연용 가상 자료" if payload["demo"] else "실제 조사 결과 · 원문 검토 필요")
    )
    overview, full, costs = st.tabs(["한눈에 보기", "보고서 원문", "비용 · 메모"])
    cost_rows = s.cost_rows
    with costs:
        st.caption(
            "비용은 직접 입력한 보조 자료입니다. 금액 누락을 0으로 확정하지 않습니다."
        )
        if archived:
            st.markdown(payload.get("appendix", "") or "저장된 부록이 없습니다.")
        else:
            cost_rows = cost_rows_list(
                st.data_editor(
                    s.cost_rows,
                    num_rows="dynamic",
                    use_container_width=True,
                    key="real_cost_rows",
                )
            )
            total = cost_summary(cost_rows)
            st.metric("입력 항목 소계 (만원)", f"{total['total']:,.1f}")
            if total["missing"]:
                st.caption("금액 미입력: " + ", ".join(total["missing"]))
            if total["errors"]:
                st.warning("유효하지 않은 비용 입력: " + ", ".join(total["errors"]))
            st.text_area("검토 메모", key="report_note", value=s.saved_memo)
            s.saved_memo = s.get("report_note", "")
    with overview:
        if payload.get("dashboard"):
            from frontend.report_overview import render_dashboard

            render_dashboard(payload["dashboard"])
            st.divider()
        a, b, c = st.columns(3)
        a.metric("특허 근거", f"{payload['patent_count']}건")
        b.metric("시장 근거", f"{payload['market_count']}건")
        c.metric("검토 질문", f"{len(payload['rows'])}개")
        st.caption(
            "건수는 이번 분석이 인용한 근거 수입니다. 품질·시장성 점수가 아닙니다."
        )
        st.subheader("질문별 결과")
        st.dataframe(
            [
                {"질문": row["질문"], "연결 상태": row["연결 상태"]}
                for row in payload["rows"]
            ],
            hide_index=True,
            use_container_width=True,
            height=150,
        )
        if payload["rows"]:
            selected_question = st.selectbox(
                "질문별 상세 결과",
                range(len(payload["rows"])),
                format_func=lambda i: payload["rows"][i]["질문"],
                key="report_question",
            )
            with st.container(height=140, border=True):
                st.write(payload["rows"][selected_question]["기존 분석 결과"])
        st.caption("보고서 원문에서 인용 근거와 판단 과정을 확인하세요.")
    appendix = (
        payload.get("appendix", "")
        if archived
        else cost_markdown(cost_rows) + "\n\n## 검토 메모\n" + s.saved_memo
    )
    markdown = payload["markdown"] + appendix
    with full:
        with st.container(height=520, border=True):
            st.markdown(markdown)
    with st.container(key="report_actions"):
        pdf, md, keep = st.columns(3)
        with pdf:
            if st.button("PDF 파일 준비", key="prepare_pdf"):
                from frontend.report_export import make_pdf

                with st.spinner("PDF를 만드는 중…"):
                    s.pdf_document = {
                        "digest": sha256(markdown.encode()).hexdigest(),
                        "data": make_pdf(payload["title"], markdown),
                    }
            ready = s.get("pdf_document")
            if ready and ready["digest"] == sha256(markdown.encode()).hexdigest():
                st.download_button(
                    "PDF 다운로드 ↓",
                    ready["data"],
                    file_name="idealens-report.pdf",
                    mime="application/pdf",
                )
        md.download_button(
            "Markdown 다운로드 ↓",
            markdown,
            file_name="idealens-report.md",
            mime="text/markdown",
        )
        if not archived and keep.button("내 기록에 보관", type="primary"):
            item = deepcopy(payload)
            item["appendix"] = appendix
            item["saved_at"] = datetime.now().astimezone().isoformat(timespec="seconds")
            item["id"] = sha256(markdown.encode()).hexdigest()
            s.records = [item] + [x for x in s.records if x["id"] != item["id"]][:19]
            st.success("현재 세션의 내 기록에 보관했습니다.")


def validate_records(raw):
    """기록은 렌더링용 JSON만 받으며 실행 객체나 API 설정을 복원하지 않는다."""
    if len(raw) > 5_000_000:
        raise ValueError("기록 파일은 5MB 이하로 선택해 주세요.")
    data = json.loads(raw)
    if (
        not isinstance(data, dict)
        or data.get("format") != "idealens-records-v1"
        or not isinstance(data.get("records"), list)
    ):
        raise ValueError("IdeaLens 기록 파일이 아닙니다.")
    records = data["records"]
    if len(records) > 20:
        raise ValueError("기록은 최대 20개입니다.")
    for item in records:
        if not isinstance(item, dict):
            raise ValueError("기록 형식을 확인해 주세요.")
        if "dashboard" in item:
            from frontend.report_overview import Dashboard

            item["dashboard"] = Dashboard.model_validate(item["dashboard"]).model_dump()
        for name in ["title", "raw", "markdown", "appendix", "saved_at", "id"]:
            if not isinstance(item.get(name), str):
                raise ValueError("기록의 필수 항목이 없습니다.")
        if not isinstance(item.get("demo"), bool) or not isinstance(
            item.get("rows"), list
        ):
            raise ValueError("기록의 결과 형식이 올바르지 않습니다.")
        for key in ["patent_count", "market_count"]:
            if type(item.get(key)) is not int or not 0 <= item[key] <= 100000:
                raise ValueError("근거 건수 형식이 올바르지 않습니다.")
        for row in item["rows"]:
            if not isinstance(row, dict) or any(
                not isinstance(row.get(k), str)
                for k in ["질문", "연결 상태", "기존 분석 결과"]
            ):
                raise ValueError("질문 결과 형식이 올바르지 않습니다.")
    return records


def render_history(s):
    st.title("내 조사 기록")
    st.caption(
        "현재 브라우저 세션에서 최대 20개를 보관합니다. 새로고침·연결 종료 시 사라질 수 있으므로 파일로 보관하세요. 계정별 영구 저장은 아직 연결하지 않았습니다."
    )
    controls, detail = st.columns([1, 2.4], gap="large")
    with controls:
        st.download_button(
            "기록 파일로 보관 ↓",
            json.dumps(
                {"format": "idealens-records-v1", "records": s.records},
                ensure_ascii=False,
                indent=2,
            ),
            file_name="idealens-records.json",
            mime="application/json",
        )
        upload = st.file_uploader("기록 파일 불러오기", type=["json"])
        if upload and st.button("선택한 기록 복원"):
            try:
                s.records = validate_records(upload.getvalue())
                st.rerun()
            except (ValueError, UnicodeError):
                st.error(
                    "기록을 읽지 못했습니다. IdeaLens에서 내보낸 5MB 이하 JSON 파일을 선택해 주세요."
                )
        if not s.records:
            st.info("보고서에서 ‘내 기록에 보관’을 눌러 기록을 남겨보세요.")
            return
        selected = st.radio(
            "보관한 조사",
            range(len(s.records)),
            format_func=lambda i: s.records[i]["title"],
        )
        st.caption(s.records[selected]["saved_at"])
    with detail:
        render_report(s, s.records[selected], archived=True)
