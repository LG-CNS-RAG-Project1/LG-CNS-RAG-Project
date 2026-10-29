"""비용 가설 편집과 문서 출력 연결. 외부 견적과 구분한다."""

import streamlit as st


def render_cost_estimate(result):
    final_markdown = result.markdown
    st.subheader("구현비용과 사업성 가설")
    estimate = result.cost_estimate
    if estimate is None:
        st.info(
            "LLM 기반 비용 추정 결과가 없습니다. 특허·시장 분석을 완료한 실제 분석에서 비용 가설을 생성합니다."
        )
    elif estimate.status == "estimated":
        st.caption(
            f"{estimate.region} · {estimate.currency} · 기준일 {estimate.as_of} · 검증 전 추정 가설이며 외부 견적이 아닙니다."
        )
        import pandas as pd

        editable = pd.DataFrame([item.model_dump() for item in estimate.items])
        if not editable.empty:
            edited = st.data_editor(
                editable,
                num_rows="dynamic",
                width="stretch",
                key="llm_cost_estimate_editor",
                column_config={
                    "name": "비용 항목",
                    "quantity": st.column_config.NumberColumn("수량", min_value=0),
                    "unit": "단위",
                    "low_unit_cost": st.column_config.NumberColumn(
                        "낮음 단가", min_value=0
                    ),
                    "base_unit_cost": st.column_config.NumberColumn(
                        "기준 단가", min_value=0
                    ),
                    "high_unit_cost": st.column_config.NumberColumn(
                        "높음 단가", min_value=0
                    ),
                    "basis": "산식·가정",
                    "citation_ids": st.column_config.ListColumn("근거 ID"),
                    "cost_type": "비용 구분",
                },
            )
            try:
                from src.generation.cost_estimation import calculate_scenarios
                from src.schemas import ImplementationCostEstimate

                edited_rows = (
                    edited.to_dict("records") if hasattr(edited, "to_dict") else edited
                )
                estimate_data = estimate.model_dump()
                estimate_data["items"] = edited_rows
                user_estimate = ImplementationCostEstimate.model_validate(estimate_data)
                totals = calculate_scenarios(user_estimate)
                from src.generation.executive_review import (
                    executive_report_markdown,
                )

                final_markdown = executive_report_markdown(
                    result.title,
                    result.executive_review,
                    analyzed_on=result.analyzed_on,
                    cost_estimate=user_estimate,
                    cost_totals=totals,
                )
                c1, c2 = st.columns(2)
                c1.metric(
                    "초기 구축비 · 기준",
                    f"{totals.initial_base:,.0f} {estimate.unit}",
                )
                c2.metric(
                    "월 반복비 · 기준",
                    f"{totals.recurring_monthly_base:,.0f} {estimate.unit}",
                )
                st.caption(totals.calculation_note)
                if totals.break_even_units_base is not None:
                    st.write(
                        f"단순 손익분기 판매량(기준): **{totals.break_even_units_base:,}개**"
                    )
            except Exception as exc:
                st.warning(f"수정한 비용값을 계산하지 못했습니다: {type(exc).__name__}")
        if estimate.assumptions:
            st.markdown("**가정:** " + " · ".join(estimate.assumptions[:4]))
        if estimate.omissions:
            st.markdown("**포함하지 않은 비용:** " + " · ".join(estimate.omissions[:4]))
    else:
        st.warning(
            "비용 산정 보류: "
            + (" · ".join(estimate.unknowns[:3]) or "입력 근거가 부족합니다.")
        )
    return final_markdown
