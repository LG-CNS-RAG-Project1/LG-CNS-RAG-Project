"""가격 성립 조건: 산식·반올림 방향·경계값·누락 보류·입력 오류."""

from decimal import Decimal

import pytest

from src.planner.pricing import compute_price, fixed, parse_decimal


def actual(**values):
    return compute_price({k: v for k, v in values.items()}, mode="actual")


def test_example_matches_research_scenario_and_rounding_direction():
    result = compute_price({}, mode="example")
    assert result.status == "overlap"
    assert result.floor == "5714.285714" and result.floor_display == "5715"
    assert result.ceiling == "6200" and result.ceiling_display == "6200"
    assert result.required_benefit == "3357.142857"
    assert result.required_benefit_display == "3357.5"
    assert result.max_direct_cost == "4340"
    assert result.mode == "example" and result.unit == "만원"


def test_actual_mode_withholds_calculation_when_any_value_is_missing():
    result = actual(C="4000", m="0.3", B="", I="1000", T=None)
    assert result.status == "withheld"
    assert result.missing == ["B", "T"]
    assert result.floor is None and result.ceiling_display is None
    assert result.inputs["B"] is None


def test_single_point_intersection_is_allowed():
    result = actual(C="4200", m="0.30", B="3500", I="1000", T="24")
    assert (result.floor_display, result.ceiling_display) == ("6000", "6000")
    assert result.status == "overlap"


def test_gap_below_one_unit_has_no_tradable_price():
    result = actual(C="4000.1", m="0", B="4000.9", I="0", T="12")
    assert Decimal(result.floor) < Decimal(result.ceiling)
    assert (result.floor_display, result.ceiling_display) == ("4001", "4000")
    assert result.status == "no_overlap"


@pytest.mark.parametrize(
    "values, message",
    [
        ({"m": "1"}, "m:"),
        ({"m": "-0.1"}, "m:"),
        ({"C": "0"}, "C:"),
        ({"I": "-1"}, "I:"),
        ({"T": "0"}, "T:"),
        ({"B": "abc"}, "B:"),
    ],
)
def test_invalid_inputs_return_errors_without_numbers(values, message):
    base = {"C": "4000", "m": "0.3", "B": "3600", "I": "1000", "T": "24"}
    result = actual(**{**base, **values})
    assert result.status == "invalid"
    assert any(error.startswith(message) for error in result.errors)
    assert result.floor is None


def test_non_positive_customer_ceiling_is_reported_not_errored():
    result = actual(C="4000", m="0.3", B="-100", I="1000", T="24")
    assert result.status == "no_positive_price"
    assert result.max_direct_cost is None
    assert result.required_benefit == "3357.142857"


def test_decimal_parsing_rejects_float_and_avoids_exponent_text():
    with pytest.raises(TypeError):
        parse_decimal(4000.0)
    assert parse_decimal("4,000") == Decimal("4000")
    assert fixed(Decimal("6.0E+3")) == "6000"
    assert fixed(Decimal("-0.0000001")) == "0"
