"""특허 상세 대화상자와 특허 보고서 화면을 렌더링한다."""

import streamlit as st


def clear_patent_detail():
    """특허 상세 대화상자를 닫을 때 선택 상태와 차트 키를 초기화한다."""
    st.session_state.selected_patent_detail_id = None
    st.session_state.patent_orbit_chart_version = (
        st.session_state.get("patent_orbit_chart_version", 0) + 1
    )


@st.dialog("특허 비교 상세", width="large", on_dismiss=clear_patent_detail)
def patent_detail_dialog(patent, patent_id):
    """선택한 문헌의 검증된 비교와 원문만 표시한다."""
    from src.generation.patent_analysis import kipris_application_search_url
    from src.generation.patent_presentation import highlight_verbatim_excerpt
    from src.generation.report_builder import safe_url
    from frontend.patent_orbit import (
        drawing_image_metadata,
        fetch_first_kipris_drawing,
        kipris_drawing_url,
        tooltip_text,
    )

    review = next(
        (item for item in patent.patent_reviews if item.patent_id == patent_id), None
    )
    evidence_by_id = {
        item.citation_id: item
        for item in patent.evidence
        if item.patent_id == patent_id
    }
    if review is None and not evidence_by_id:
        st.info("선택한 특허의 비교 결과를 찾을 수 없습니다.")
        return
    title = review.title if review else next(iter(evidence_by_id.values())).title
    st.subheader(title)
    st.caption(
        " · ".join(
            value
            for value in (
                f"출원번호 {next((item.application_number for item in evidence_by_id.values() if item.application_number), '미확인')}",
                f"공개번호 {next((item.publication_number for item in evidence_by_id.values() if item.publication_number), '미확인')}",
            )
        )
    )
    drawing_evidence = next(
        (
            item
            for item in evidence_by_id.values()
            if item.representative_thumbnail_url or item.representative_drawing_url
        ),
        None,
    )
    image_bytes = None
    image_status = "missing_url"
    loaded_url = None
    if drawing_evidence:
        image_bytes, image_status, loaded_url = fetch_first_kipris_drawing(
            (
                drawing_evidence.representative_drawing_url,
                drawing_evidence.representative_thumbnail_url,
            )
        )
    full_drawing_url = (
        kipris_drawing_url(
            drawing_evidence.representative_drawing_url
            or drawing_evidence.representative_thumbnail_url
        )
        if drawing_evidence
        else None
    )

    left, right = st.columns([3, 1.15], gap="large", vertical_alignment="top")
    with left:
        if review:
            reason = tooltip_text(review.relevance_reason, "우선 확인 이유 미제공")
            st.info(f"**관련성: {review.relevance}** · {reason}")
            if review.overall_summary:
                st.write(review.overall_summary)
        else:
            st.info("원문은 확보했지만 이 문헌의 비교 분석 결과는 제공되지 않았습니다.")

    with right:
        st.markdown("#### 대표도면")
        if image_bytes:
            try:
                image_width, image_height, _, image_format = drawing_image_metadata(
                    image_bytes
                )
                original_url = kipris_drawing_url(
                    drawing_evidence.representative_drawing_url
                )
                is_original = loaded_url == original_url
                resolution_note = "원본 도면" if is_original else "썸네일 · 저해상도"
                caption = drawing_evidence.representative_drawing_caption or (
                    f"KIPRIS 대표도면 · 출원번호 "
                    f"{drawing_evidence.application_number or patent_id}"
                )
                st.image(image_bytes, caption=caption, width=min(image_width, 240))
                st.caption(
                    f"{resolution_note} · {image_width}×{image_height} px · {image_format}"
                )
                with st.popover("도면 크게 보기"):
                    st.image(image_bytes, caption=caption, width=min(image_width, 1200))
                    st.caption(f"{image_width}×{image_height} px · {image_format}")
                    if full_drawing_url:
                        st.link_button("KIPRIS 대표도면 원문 열기", full_drawing_url)
                st.caption("출처: KIPRIS Plus · 선택한 문헌")
            except Exception:
                st.info(
                    "대표도면 형식을 표시할 수 없습니다. KIPRIS 원문 링크에서 확인해 주세요."
                )
        elif drawing_evidence:
            failure_messages = {
                "invalid_source": "저장된 도면 주소가 KIPRIS 공식 호스트가 아니어서 표시하지 않았습니다.",
                "redirect": "도면 서버가 다른 주소로 안내했습니다. 안전 검증을 위해 자동 이동하지 않았습니다.",
                "http_error": "KIPRIS 도면 서버에서 이미지 파일을 가져오지 못했습니다.",
                "non_image_response": "KIPRIS 도면 서버가 이미지가 아닌 응답을 반환했습니다.",
                "invalid_image": "KIPRIS 응답이 유효한 이미지 파일이 아닙니다.",
                "too_large": "도면 파일이 허용 크기인 8MB를 초과했습니다.",
                "network_error": "KIPRIS 도면 서버에 연결하지 못했습니다.",
                "missing_url": "이미지 경로를 찾을 수 없습니다.",
            }
            st.info(
                "대표도면을 불러오지 못했습니다. "
                + failure_messages.get(
                    image_status, "이미지 응답을 확인할 수 없습니다."
                )
            )
        else:
            st.info("이 문헌에는 대표도면 경로가 없습니다.")
        if full_drawing_url:
            st.link_button("KIPRIS 도면 원문", full_drawing_url)

    st.markdown("#### 아이디어 구성요소별 비교")
    status_labels = {
        "overlap": "유사",
        "partial": "일부 유사",
        "different": "차이",
        "not_found": "근거에서 찾지 못함",
        "uncertain": "불확실",
    }
    comparisons = review.component_comparisons if review else []
    if comparisons:
        for comparison in comparisons:
            st.markdown(
                f"**{comparison.idea_component}** · "
                f"{status_labels.get(comparison.status, '불확실')}"
            )
            if comparison.overlap:
                st.write(f"유사점: {comparison.overlap}")
            if comparison.difference:
                st.write(f"차이점: {comparison.difference}")
            if comparison.uncertainty:
                st.caption(f"확인 한계: {comparison.uncertainty}")
            cited = [
                evidence_by_id[cid]
                for cid in comparison.citation_ids
                if cid in evidence_by_id
            ]
            for evidence in cited:
                claim_label = (
                    f"청구항 {evidence.claim_number}"
                    if evidence.claim_number
                    else evidence.section
                )
                st.caption(f"P:{evidence.citation_id} · {claim_label}")
                matched = comparison.matched_text
                rendered_quote = highlight_verbatim_excerpt(evidence.quote, matched)
                st.markdown(
                    f'<div class="patent-quote">{rendered_quote}</div>',
                    unsafe_allow_html=True,
                )
                source_url = safe_url(evidence.source_url)
                if source_url:
                    st.link_button(
                        f"P:{evidence.citation_id} 원문 출처 열기", source_url
                    )
                if matched and matched not in evidence.quote:
                    st.caption(
                        "강조 문구가 제공된 원문과 일치하지 않아 표시하지 않았습니다."
                    )
    else:
        st.info("확인된 구성요소별 비교가 없습니다.")
    if review and review.unknowns:
        st.markdown("#### 추가 확인")
        for item in review.unknowns:
            st.write(f"- {item}")
    elif not review:
        st.markdown("#### 확보된 원문")
        for evidence in evidence_by_id.values():
            claim_label = (
                f"청구항 {evidence.claim_number}"
                if evidence.claim_number
                else evidence.section
            )
            st.caption(f"P:{evidence.citation_id} · {claim_label}")
            st.write(evidence.quote)

    if review and (review.watchout_findings or review.design_recommendations):
        st.markdown("#### 이 문헌의 주의점과 개선 제안")
        for item in review.watchout_findings:
            linked = [
                evidence_by_id[cid]
                for cid in item.citation_ids
                if cid in evidence_by_id
            ]
            basis = "문헌 근거 연결" if linked else "추가 확인이 필요한 가설"
            st.warning(
                f"**{item.issue} · {basis}**\n\n{item.why_it_matters}\n\n"
                f"다음 확인: {item.next_check}"
            )
            for evidence in linked:
                claim = (
                    f" · 청구항 {evidence.claim_number}"
                    if evidence.claim_number
                    else ""
                )
                st.caption(f"P:{evidence.citation_id}{claim} · {evidence.title}")
                st.text(evidence.quote)
        for item in review.design_recommendations:
            refs = ", ".join(f"P:{cid}" for cid in item.citation_ids)
            basis = "근거 기반" if item.basis == "evidence_based" else "검증 전 가설"
            st.markdown(f"**개선 제안 · {basis}:** {item.recommendation}")
            st.write(item.rationale)
            if item.validation_needed:
                st.caption(f"검증할 내용: {item.validation_needed}")
            if refs:
                st.caption(f"연결 근거: {refs}")

    application_number = next(
        (
            item.application_number
            for item in evidence_by_id.values()
            if item.application_number
        ),
        None,
    )
    kipris_url = kipris_application_search_url(application_number)
    if kipris_url:
        st.link_button("KIPRIS에서 출원번호 검색", kipris_url)
    elif not application_number:
        st.caption("출원번호 미확인 · KIPRIS 검색 링크를 만들 수 없습니다.")


@st.dialog("2. 주의점 및 개선 제안 상세", width="large")
def patent_watchouts_dialog(patent):
    """주의점·공통 설계 권고와 이를 뒷받침하는 특허 근거를 표시한다."""
    precheck = patent.patentability_precheck
    if precheck is None:
        st.info("특허 비교 신호가 없어 상세 내용을 제공할 수 없습니다.")
        return

    evidence_by_id = {item.citation_id: item for item in patent.evidence}
    st.caption(
        "검색 문헌을 바탕으로 한 기술 검토 보조입니다. 출원·신규성·진보성·침해·실시 자유에 대한 법률 의견이 아닙니다."
    )
    if precheck.common_watchouts:
        st.markdown("### 주의 항목 · 문헌 근거 연결 여부 확인")
        for item in precheck.common_watchouts:
            linked = [
                evidence_by_id[cid]
                for cid in item.citation_ids
                if cid in evidence_by_id
            ]
            basis = "문헌 근거 연결" if linked else "추가 확인이 필요한 가설"
            st.warning(
                f"**{item.issue} · {basis}**\n\n{item.why_it_matters}\n\n다음 확인: {item.next_check}"
            )
            if not linked:
                st.caption("연결된 문헌·청구항이 없어 분석 가설로만 표시합니다.")
            for evidence in linked:
                claim = (
                    f" · 청구항 {evidence.claim_number}"
                    if evidence.claim_number
                    else ""
                )
                st.caption(f"P:{evidence.citation_id}{claim} · {evidence.title}")
                st.text(evidence.quote)
    else:
        st.info("문헌 전체에서 근거가 연결된 공통 주의점은 확인되지 않았습니다.")

    if precheck.common_design_recommendations:
        st.markdown("### 공통 개선 제안")
        for item in precheck.common_design_recommendations:
            refs = ", ".join(f"P:{cid}" for cid in item.citation_ids)
            basis = "근거 기반" if item.basis == "evidence_based" else "검증 전 가설"
            st.markdown(
                f"**{item.recommendation}** · {basis}{f' ({refs})' if refs else ''}"
            )
            st.write(item.rationale)
            if item.validation_needed:
                st.caption(f"확인할 사항: {item.validation_needed}")
            for citation_id in item.citation_ids:
                evidence = evidence_by_id.get(citation_id)
                if evidence:
                    claim = (
                        f" · 청구항 {evidence.claim_number}"
                        if evidence.claim_number
                        else ""
                    )
                    st.caption(f"근거 P:{citation_id}{claim} · {evidence.title}")

    if precheck.expert_questions:
        st.markdown("### 전문가 확인 질문")
        for question in precheck.expert_questions:
            st.write(f"- {question}")
    if precheck.limitations:
        st.caption("공통 검토 한계: " + " · ".join(precheck.limitations))


@st.dialog("3. 설계 대안 상세", width="large")
def patent_design_dialog(patent):
    """설계 대안의 구현 내용·근거·검증 계획을 한국어로 표시한다."""
    analysis = patent.design_analysis
    if analysis is None:
        st.info("설계 대안 분석 결과가 없습니다.")
        return

    status_labels = {
        "success": "근거를 바탕으로 대안을 구성했습니다.",
        "partial": "일부 정보가 부족해 제한적으로 제안합니다.",
        "insufficient_evidence": "설계 대안을 뒷받침할 근거가 부족합니다.",
        "failed": "대안 생성이 완료되지 않았습니다.",
    }
    feasibility_labels = {
        "low": "낮음",
        "medium": "보통",
        "high": "높음",
        "unknown": "미확인",
    }
    evidence_labels = {"grounded": "근거 연결", "insufficient_evidence": "근거 부족"}
    evidence_by_id = {item.citation_id: item for item in patent.evidence}
    st.caption(status_labels[analysis.status])
    if analysis.evidence_level == "abstract_only":
        st.warning("청구항 원문이 없어 초록 수준의 근거로만 분석했습니다.")
    for component in analysis.technical_components:
        st.caption(f"{component.id} · {component.name} — {component.description}")

    if not analysis.proposals:
        st.info("표시할 설계 대안이 없습니다.")
    for index, proposal in enumerate(analysis.proposals, 1):
        with st.container(border=True):
            st.markdown(f"### 대안 {index} · {proposal.title}")
            st.markdown(f"**현재 문제**\n\n{proposal.problem}")
            st.markdown(f"**변경 대상**\n\n{', '.join(proposal.target_component_ids)}")
            st.markdown(f"**설계 변경**\n\n{proposal.proposed_change}")
            st.markdown("**구현 방법**")
            for step in proposal.implementation_approach:
                st.markdown(f"- {step}")
            st.markdown(f"**기술적 차이**\n\n{proposal.technical_difference}")
            if proposal.expected_benefits:
                st.markdown(
                    "**기대 효과**\n\n" + " · ".join(proposal.expected_benefits)
                )
            if proposal.limitations:
                st.markdown("**구현상 제약**\n\n" + " · ".join(proposal.limitations))
            st.caption(
                f"기술 구현 가능성: {feasibility_labels[proposal.feasibility]} · "
                f"근거 상태: {evidence_labels[proposal.evidence_status]}"
            )
            for citation_id in proposal.citation_ids:
                source = evidence_by_id.get(citation_id)
                if source:
                    claim = (
                        f" · 청구항 {source.claim_number}"
                        if source.claim_number
                        else ""
                    )
                    st.caption(f"근거 P:{citation_id} · {source.title}{claim}")
                    st.text(source.quote)
            st.markdown(f"**검증 방법**\n\n{proposal.verification_plan.method}")
            if proposal.verification_plan.metrics:
                st.caption(
                    "측정 항목: " + " · ".join(proposal.verification_plan.metrics)
                )
            st.caption("성공 기준: " + proposal.verification_plan.success_criteria)
            st.caption(
                "추가 특허 확인 필요"
                if proposal.patent_verification_required
                else "추가 특허 확인 표시 없음"
            )
    for item in analysis.missing_information:
        st.warning("추가 확인: " + item)
    for item in analysis.limitations:
        st.caption("한계: " + item)
    st.caption("기술 검토용이며 침해·특허성·실시 자유에 대한 법률 의견이 아닙니다.")


def render_patent_report(patent, *, widget_suffix="", preview=False):
    """최대 8개 특허를 궤도에 배치하고 호버 요약과 종합 근거를 제공한다."""
    import math
    from frontend.patent_orbit import (
        dense_similarity_text,
        patent_dense_similarity,
        patent_orbit_position,
        patent_semantic_similarity,
        semantic_similarity_text,
        tooltip_text,
    )

    from src.generation.patent_presentation import (
        PATENT_ORBIT_COLORS,
        PATENT_ORBIT_LABELS,
        patent_orbit_category,
        patent_review_priority,
    )

    if patent.status == "error":
        st.error("특허 비교 보고서를 완성하지 못했습니다.")
        if "LIMITED_NUMBER_OF_SERVICE_REQUESTS_EXCEEDS_ERROR" in (
            patent.error_message or ""
        ):
            st.warning(
                "로컬 특허 색인에서 관련 후보를 확인하지 못했고, KIPRIS 요청 한도 초과로 보충 검색이 중단됐습니다. "
                "따라서 현재 결과는 ‘특허 없음’이 아니라 ‘검색 미완료’입니다. KIPRIS 이용 한도를 확인한 뒤 다시 조사해 주세요."
            )
        if patent.evidence:
            st.info(
                f"비교 생성은 실패했지만 원문 근거 {len(patent.evidence)}건은 보존했습니다."
            )
        st.caption(
            "원인과 조치 방법을 확인한 뒤 다시 분석해 주세요. 재시도는 API 비용이 발생할 수 있습니다."
        )
        if patent.error_message:
            from src.pipeline import redact

            with st.expander("오류 상세"):
                st.code(redact(patent.error_message))
    elif patent.status == "partial":
        st.warning("특허 원문은 확보했지만 비교 분석을 완료하지 못했습니다.")
        st.info(f"원문 근거 {len(patent.evidence)}건을 보존했습니다.")
        st.caption(
            "아래 문헌과 원문은 확인할 수 있지만, 구성요소별 비교와 설계 대안은 미완료입니다."
        )
        if patent.error_message:
            from src.pipeline import redact

            with st.expander("비교 생성 오류 상세"):
                st.code(redact(patent.error_message))
    elif patent.status == "no_results":
        st.warning(
            "검색 범위에서 특허 근거를 찾지 못했습니다. 위험이 없다는 뜻은 아닙니다."
        )
        st.caption(f"검색 범위: {patent.search_scope}")
        if patent.unknowns:
            st.caption(f"검색 상태: {patent.unknowns[0]}")

    precheck = patent.patentability_precheck
    evidence_by_id = {item.citation_id: item for item in patent.evidence}
    reviews_by_patent = {item.patent_id: item for item in patent.patent_reviews}
    design_analysis = patent.design_analysis
    related_stats = getattr(patent, "related_statistics", None)

    st.subheader("1. 특허 비교 궤도")
    st.caption(
        "검색된 문헌과 청구항을 아이디어 구성요소에 대조한 기술 예비 검토입니다."
    )
    with st.container(border=True):
        documents = []
        for evidence in patent.evidence:
            if evidence.patent_id not in {item["patent_id"] for item in documents}:
                documents.append(
                    {
                        "patent_id": evidence.patent_id,
                        "title": evidence.title,
                        "evidence": [],
                    }
                )
            next(item for item in documents if item["patent_id"] == evidence.patent_id)[
                "evidence"
            ].append(evidence)
        documents = documents[:8]
        if documents:
            candidate_count = related_stats.total_patents if related_stats else None
            if candidate_count is not None:
                st.caption(
                    f"관련 검색 후보 {candidate_count}건 중 최종 비교 {len(documents)}건 · 목표 5~8건"
                )
            else:
                st.caption(f"최종 비교 문헌 {len(documents)}건 · 목표 5~8건")
            if len(documents) < 5:
                st.warning(
                    f"관련 특허를 {len(documents)}건만 확인했습니다. 검색 범위에서 근거가 있는 문헌만 보여주며, 수를 맞추기 위해 관련성이 낮은 특허를 추가하지 않았습니다."
                )
            orbit_reviews = []
            for document in documents:
                review = reviews_by_patent.get(document["patent_id"])
                if review is None:
                    from src.schemas import PatentDocumentReview

                    review = PatentDocumentReview(
                        patent_id=document["patent_id"],
                        title=document["title"],
                        citation_ids=[
                            item.citation_id for item in document["evidence"]
                        ],
                        relevance="insufficient",
                    )
                orbit_reviews.append((review, document["evidence"]))
            orbit_reviews.sort(
                key=lambda pair: (
                    ("red", "yellow", "green", "blue").index(
                        patent_orbit_category(pair[0], evidence_by_id)
                    ),
                    patent_review_priority(pair[0]),
                )
            )
            count = len(orbit_reviews)
            points = []
            for index, (review, document_evidence) in enumerate(orbit_reviews):
                category = patent_orbit_category(review, evidence_by_id)
                reason = tooltip_text(review.relevance_reason, "우선 확인 이유 미제공")
                dense_similarity = patent_dense_similarity(document_evidence)
                semantic_similarity = patent_semantic_similarity(document_evidence)
                x, y = patent_orbit_position(index, count, semantic_similarity)
                points.append(
                    {
                        "patent_id": review.patent_id,
                        "title": review.title,
                        "number": f"P{index + 1}",
                        "priority_reason_display": reason[:180],
                        "dense_score_display": dense_similarity_text(dense_similarity),
                        "semantic_similarity_display": semantic_similarity_text(
                            semantic_similarity
                        ),
                        "category": category,
                        "color": PATENT_ORBIT_COLORS[category],
                        "x": x,
                        "y": y,
                    }
                )

            st.subheader("특허 비교 궤도")
            from src.llm_client import load_llm_settings

            model_name = patent.semantic_similarity_model
            if model_name:
                provider = load_llm_settings()
                if provider == "ollama":
                    call_note = (
                        f"선택한 Ollama 임베딩 모델 {model_name}로 로컬 처리합니다."
                    )
                else:
                    call_note = f"OpenAI {model_name} 임베딩 API 호출로 비용이 발생할 수 있습니다."
            else:
                call_note = "이번 결과에서는 의미 유사도를 계산하지 않았습니다."
            st.caption(
                "의미 유사도는 아이디어 기술 내용과 특허 제목·초록·확보 청구항의 "
                "cosine 유사도(0~1, 음수는 0으로 제한)입니다. "
                f"{call_note} Dense 검색 점수와 다른 지표이며 관련성 확률이 아닙니다. "
                "궤도는 의미 유사도가 높을수록 중심에 가깝고, 점수가 없으면 외곽 배치합니다. "
                "색상은 구성 비교 근거에 따른 검토 우선순위이며 법률상 위험 등급이 아닙니다."
            )
            legend = st.columns(4)
            for column, category in zip(legend, ("red", "yellow", "green", "blue")):
                column.markdown(
                    f'<span style="color:{PATENT_ORBIT_COLORS[category]}">●</span> '
                    f"{PATENT_ORBIT_LABELS[category]}",
                    unsafe_allow_html=True,
                )

            selected_patent = None
            try:
                import altair as alt

                orbit_values = []
                for ring, (radius_x, radius_y) in enumerate(
                    ((2.7, 2.1), (1.85, 1.44), (1.05, 0.82))
                ):
                    orbit_values.extend(
                        {
                            "order": index,
                            "ring": ring,
                            "x": radius_x * math.cos(2 * math.pi * index / 120),
                            "y": radius_y * math.sin(2 * math.pi * index / 120),
                        }
                        for index in range(121)
                    )
                hover = alt.selection_point(
                    name=f"patent_hover{widget_suffix}",
                    fields=["patent_id"],
                    on="pointerover",
                    clear="pointerout",
                    nearest=True,
                )
                click = None
                if not preview:
                    click = alt.selection_point(
                        name=f"patent_click{widget_suffix}",
                        fields=["patent_id"],
                        on="click",
                        clear="dblclick",
                        empty=False,
                    )
                orbit = (
                    alt.Chart(alt.Data(values=orbit_values))
                    .mark_line(
                        color="#97aaa0",
                        strokeDash=[3, 6],
                        strokeWidth=1.15,
                        opacity=0.62,
                    )
                    .encode(
                        x=alt.X("x:Q", axis=None, scale=alt.Scale(domain=[-3.5, 3.5])),
                        y=alt.Y("y:Q", axis=None, scale=alt.Scale(domain=[-2.8, 2.8])),
                        order="order:Q",
                        detail="ring:N",
                    )
                )
                center_data = alt.Data(values=[{"x": 0, "y": 0, "label": "아이디어"}])
                center = (
                    alt.Chart(center_data)
                    .mark_circle(
                        size=1900, color="#214c45", stroke="#d5b96a", strokeWidth=2
                    )
                    .encode(x="x:Q", y="y:Q", tooltip="label:N")
                )
                center_label = (
                    alt.Chart(center_data)
                    .mark_text(color="white", fontSize=15, fontWeight="bold")
                    .encode(x="x:Q", y="y:Q", text="label:N")
                )
                points_chart = (
                    alt.Chart(alt.Data(values=points))
                    .mark_circle(
                        size=1120,
                        stroke="#fffdf5",
                        strokeWidth=3,
                        cursor="help" if preview else "pointer",
                    )
                    .encode(
                        x="x:Q",
                        y="y:Q",
                        color=alt.Color(
                            "color:N", scale=None, legend=None, title="검토 우선순위"
                        ),
                        tooltip=[
                            alt.Tooltip("title:N", title="문헌"),
                            alt.Tooltip(
                                "semantic_similarity_display:N",
                                title="의미 유사도 (0~1)",
                            ),
                            alt.Tooltip(
                                "dense_score_display:N",
                                title="Dense 검색 점수",
                            ),
                            alt.Tooltip(
                                "priority_reason_display:N",
                                title="우선 확인 이유",
                            ),
                        ],
                        opacity=alt.condition(hover, alt.value(1), alt.value(0.88)),
                    )
                    .add_params(*([hover, click] if click is not None else [hover]))
                )
                point_labels = (
                    alt.Chart(alt.Data(values=points))
                    .mark_text(color="white", fontSize=15, fontWeight="bold")
                    .encode(x="x:Q", y="y:Q", text="number:N")
                )
                chart = (
                    (orbit + center + center_label + points_chart + point_labels)
                    .properties(
                        height=380,
                        padding={"top": 12, "right": 12, "bottom": 12, "left": 12},
                    )
                    .configure_view(stroke=None)
                )
                chart_state = st.altair_chart(
                    chart,
                    key=(
                        f"patent_orbit_v4{widget_suffix}"
                        if preview
                        else f"patent_orbit_v4{widget_suffix}_{st.session_state.patent_orbit_chart_version}"
                    ),
                    on_select="ignore" if preview else "rerun",
                    selection_mode=None if preview else click.name,
                    width="stretch",
                    alt="중앙 아이디어를 둘러싼 특허 검토 우선순위 궤도 시각화",
                )
                if not preview:
                    selected_rows = chart_state.selection.get(click.name, [])
                    if selected_rows:
                        selected_patent = selected_rows[-1].get("patent_id")
                        if selected_patent in {item["patent_id"] for item in documents}:
                            st.session_state.selected_patent_detail_id = selected_patent
            except Exception as exc:
                st.warning(
                    f"궤도 차트를 표시하지 못했습니다 ({type(exc).__name__}). 페이지를 새로고침하거나 다른 브라우저에서 다시 열어 주세요."
                )

            selected_patent = (
                st.session_state.get("selected_patent_detail_id") or selected_patent
            )
            if not preview and selected_patent in {
                item["patent_id"] for item in documents
            }:
                patent_detail_dialog(patent, selected_patent)

        else:
            if patent.status in {"error", "partial"}:
                st.info("검색이 완료되지 않아 특허 부재 여부를 판단할 수 없습니다.")
            else:
                st.info(
                    "표시할 특허 문헌이 없습니다. 검색 결과가 없다는 뜻이 특허 위험이 없다는 의미는 아닙니다."
                )

    st.subheader("2. 주의점 및 개선 제안")
    if precheck:
        st.caption(
            "특허 문헌 비교를 위한 기술 검토 보조입니다. 특허성·침해·실시 자유에 대한 법률 판단이 아닙니다."
        )
        precheck_labels = {
            "overlap_concern": "유사 구성에 주의",
            "potentially_distinct": "차이 가능성 확인",
            "insufficient_evidence": "근거 부족 · 판단 보류",
        }
        st.info(f"{precheck_labels[precheck.status]} · {precheck.summary}")
        for item in precheck.common_watchouts[:2]:
            refs = ", ".join(f"P:{cid}" for cid in item.citation_ids)
            linked = any(cid in evidence_by_id for cid in item.citation_ids)
            basis = "문헌 근거" if linked else "확인 필요 가설"
            st.markdown(
                f"- **주의 · {basis}:** {item.issue} — {item.why_it_matters}"
                + (f" · 다음 확인: {item.next_check}" if item.next_check else "")
                + (f" · {refs}" if refs else "")
            )
        for item in precheck.common_design_recommendations[:2]:
            refs = ", ".join(f"P:{cid}" for cid in item.citation_ids)
            basis = "근거 기반" if item.basis == "evidence_based" else "검증 전 가설"
            st.markdown(
                f"- **개선 · {basis}:** {item.recommendation}"
                + (f" — {item.rationale}" if item.rationale else "")
                + (f" · {refs}" if refs else "")
            )
            if item.validation_needed:
                st.caption(f"확인할 사항: {item.validation_needed}")
        if not precheck.common_watchouts and not precheck.common_design_recommendations:
            st.caption("문헌 공통 주의점·개선 제안은 확인되지 않았습니다.")
        if not preview and st.button(
            "2 상세 보기", key=f"patent_watchouts_{widget_suffix}"
        ):
            patent_watchouts_dialog(patent)
    else:
        st.info(
            "특허 비교 신호가 제공되지 않아 주의점과 개선 제안을 판단하지 않았습니다."
        )

    st.subheader("3. 설계 대안")
    if design_analysis:
        design_status_labels = {
            "success": "근거 기반 제안",
            "partial": "제한적 제안",
            "insufficient_evidence": "근거 부족",
            "failed": "생성 실패",
        }
        st.caption(design_status_labels[design_analysis.status])
        for index, proposal in enumerate(design_analysis.proposals, 1):
            refs = ", ".join(f"P:{cid}" for cid in proposal.citation_ids)
            st.markdown(
                f"- **대안 {index} · {proposal.title}:** {proposal.proposed_change}"
                + (f" · 근거 {refs}" if refs else " · 검증 전 제안")
            )
        if not design_analysis.proposals:
            st.caption("표시할 설계 대안이 없습니다.")
        if not preview and st.button(
            "3 상세 보기", key=f"patent_design_{widget_suffix}"
        ):
            patent_design_dialog(patent)
    else:
        st.info("설계 대안 분석 결과가 없습니다.")
    if patent.unknowns:
        with st.expander(f"특허 검색 미확인 사항 ({len(patent.unknowns)}건)"):
            for item in patent.unknowns:
                st.write(f"- {item}")
    if not patent.patent_reviews and patent.comparisons:
        with st.expander("특허별 비교 및 원문"):
            for comparison in patent.comparisons[:10]:
                evidence = next(
                    (
                        item
                        for item in patent.evidence
                        if item.citation_id == comparison.citation_id
                    ),
                    None,
                )
                st.write(
                    f"P:{comparison.citation_id} · {comparison.similarity} · 차이: {comparison.difference}"
                )
                if evidence:
                    st.text(evidence.quote)
