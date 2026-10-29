"""초기 구축 프로젝트 1건의 가격 성립 조건을 Decimal로 계산한다.

- 공급자 조건 하한 Pmin = C / (1 - m), 고객 회수조건 상한 Pmax = B × T / 12 - I
- 금액 단위는 만원, 거래 단위는 1만원: 하한은 올림, 상한은 내림해 표시 구간을 만든다.
- 값이 하나라도 없으면 계산을 보류한다. 결과는 지불의사·시장가격·판매량·사업 성공의 근거가 아니며,
  구독형 현금흐름은 이 산식에 넣지 않는다.
"""

from decimal import (
    ROUND_CEILING,
    ROUND_FLOOR,
    ROUND_HALF_EVEN,
    Decimal,
    InvalidOperation,
    localcontext,
)

from src.planner.schemas import PriceResult

CALC_VERSION = "price-conditions-v1"
UNIT = "만원"
STEP = Decimal(1)
PRECISION = Decimal("0.000001")
FIELDS = ("C", "m", "B", "I", "T")
LABELS = {
    "C": "프로젝트 직접비(만원)",
    "m": "판매가 대비 목표 이익률(0 이상 1 미만)",
    "B": "고객 연간 추가 순효과(만원/년)",
    "I": "우리 판매가 외 고객 초기비용(만원)",
    "T": "허용 회수기간(개월)",
}
EXAMPLE = {"C": "4000", "m": "0.30", "B": "3600", "I": "1000", "T": "24"}
NOT_EVIDENCE = (
    "입력 가정으로 계산한 조건이며 실제 지불의사·시장가격·판매량·고정비 회수·사업 성공을 "
    "입증하지 않습니다. 구독형 현금흐름은 포함하지 않습니다."
)


def parse_decimal(value) -> Decimal | None:
    """문자열·정수·Decimal을 Decimal로 바꾼다. 빈 값은 None, float는 거부한다."""
    if value is None:
        return None
    if isinstance(value, float):
        raise TypeError("금액 입력에 float를 쓰지 않는다")
    if isinstance(value, Decimal):
        number = value
    else:
        text = str(value).strip().replace(",", "")
        if not text:
            return None
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise ValueError(f"숫자가 아님: {value}") from exc
    if not number.is_finite():
        raise ValueError(f"유한한 숫자가 아님: {value}")
    return number


def fixed(number: Decimal | None) -> str | None:
    """소수 6자리에서 반올림한 고정소수 문자열. 끝의 0과 지수 표기는 쓰지 않는다."""
    if number is None:
        return None
    text = format(number.quantize(PRECISION, rounding=ROUND_HALF_EVEN), "f")
    if "." in text:
        text = text.rstrip("0").rstrip(".")
    return "0" if text in {"-0", ""} else text


def compute_price(
    values: dict, mode: str = "actual", provenance: dict | None = None
) -> PriceResult:
    """가격 조건을 계산한다. mode='example'이면 빈 값을 설명용 예시로 채운다."""
    if mode == "example":
        values = {**EXAMPLE, **{k: v for k, v in values.items() if v not in (None, "")}}
    parsed, missing, errors = {}, [], []
    for field in FIELDS:
        try:
            number = parse_decimal(values.get(field))
        except (ValueError, TypeError) as exc:
            errors.append(f"{field}: {exc}")
            continue
        if number is None:
            missing.append(field)
        else:
            parsed[field] = number
    base = {
        "mode": mode,
        "calc_version": CALC_VERSION,
        "unit": UNIT,
        "inputs": {field: fixed(parsed.get(field)) for field in FIELDS},
        "provenance": provenance or {},
        "missing": missing,
    }
    if errors:
        return PriceResult(status="invalid", errors=errors, **base)
    if missing:
        return PriceResult(status="withheld", **base)

    C, m, B, I, T = (parsed[field] for field in FIELDS)
    if not Decimal(0) <= m < Decimal(1):
        errors.append("m: 0 이상 1 미만이어야 함")
    if C <= 0:
        errors.append("C: 0보다 커야 함")
    if I < 0:
        errors.append("I: 0 이상이어야 함")
    if T <= 0:
        errors.append("T: 0보다 커야 함")
    if errors:
        return PriceResult(status="invalid", errors=errors, **base)

    with localcontext() as ctx:
        ctx.prec = 34
        floor = C / (Decimal(1) - m)
        ceiling = B * T / Decimal(12) - I
        floor_display = floor.quantize(STEP, rounding=ROUND_CEILING)
        ceiling_display = ceiling.quantize(STEP, rounding=ROUND_FLOOR)
        required = (floor + I) * Decimal(12) / T
        required_display = (floor_display + I) * Decimal(12) / T
        max_cost = ceiling * (Decimal(1) - m) if ceiling > 0 else None
        max_cost_display = (
            ceiling_display * (Decimal(1) - m) if ceiling_display > 0 else None
        )
    if ceiling <= 0:
        status = "no_positive_price"
    elif floor_display > ceiling_display:
        status = "no_overlap"
    else:
        status = "overlap"
    return PriceResult(
        status=status,
        floor=fixed(floor),
        ceiling=fixed(ceiling),
        floor_display=fixed(floor_display),
        ceiling_display=fixed(ceiling_display),
        required_benefit=fixed(required),
        required_benefit_display=fixed(required_display),
        max_direct_cost=fixed(max_cost),
        max_direct_cost_display=fixed(max_cost_display),
        **base,
    )
