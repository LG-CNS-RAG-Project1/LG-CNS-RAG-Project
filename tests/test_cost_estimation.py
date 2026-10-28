import pytest
from pydantic import ValidationError
from src.generation.cost_estimation import calculate_scenarios
from src.schemas import ImplementationCostEstimate, ImplementationCostItem


def test_cost_ranges_and_break_even_are_deterministic():
    estimate = ImplementationCostEstimate(
        status="estimated",
        items=[
            ImplementationCostItem(
                name="개발",
                quantity=2,
                unit="인월",
                low_unit_cost=100,
                base_unit_cost=150,
                high_unit_cost=200,
                basis="외부 견적 필요",
                cost_type="one_time",
            ),
            ImplementationCostItem(
                name="클라우드",
                quantity=1,
                unit="월",
                low_unit_cost=10,
                base_unit_cost=20,
                high_unit_cost=30,
                basis="검증 전 가설",
                cost_type="monthly",
            ),
        ],
        revenue_unit_price=80,
        variable_cost_per_unit=30,
    )
    result = calculate_scenarios(estimate)
    assert (result.initial_low, result.initial_base, result.initial_high) == (
        200,
        300,
        400,
    )
    assert result.recurring_monthly_base == 20
    assert result.break_even_units_base == 7


def test_missing_revenue_inputs_never_invents_break_even():
    result = calculate_scenarios(
        ImplementationCostEstimate(
            status="estimated",
            items=[
                ImplementationCostItem(
                    name="개발",
                    quantity=1,
                    unit="인월",
                    low_unit_cost=1,
                    base_unit_cost=2,
                    high_unit_cost=3,
                    basis="가설",
                )
            ],
        )
    )
    assert result.break_even_units_base is None
    assert "계산하지 않았습니다" in result.calculation_note


def test_cost_range_rejects_inverted_values():
    with pytest.raises(ValidationError):
        ImplementationCostItem(
            name="개발",
            quantity=1,
            unit="인월",
            low_unit_cost=3,
            base_unit_cost=2,
            high_unit_cost=4,
            basis="가설",
        )
