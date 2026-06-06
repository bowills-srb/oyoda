from __future__ import annotations

from decimal import Decimal, ROUND_HALF_UP

MICRO_USD = Decimal("0.000001")
TOKENS_PER_MILLION = Decimal("1000000")


PRICING: dict[str, dict[str, Decimal]] = {
    "claude-haiku-4-5": {"input": Decimal("1.00"), "output": Decimal("5.00")},
    "claude-haiku-4-5-20251001": {"input": Decimal("1.00"), "output": Decimal("5.00")},
    "claude-sonnet-4-20250514": {"input": Decimal("3.00"), "output": Decimal("15.00")},
    "meta-llama/llama-4-scout-17b-16e-instruct": {
        "input": Decimal("0.59"),
        "output": Decimal("0.79"),
    },
}


def calculate_cost(model_id: str, input_tokens: int, output_tokens: int) -> Decimal:
    pricing = PRICING.get(model_id)
    if pricing is None:
        return Decimal("0.000000")

    input_cost = (Decimal(max(input_tokens, 0)) / TOKENS_PER_MILLION) * pricing["input"]
    output_cost = (Decimal(max(output_tokens, 0)) / TOKENS_PER_MILLION) * pricing["output"]
    return (input_cost + output_cost).quantize(MICRO_USD, rounding=ROUND_HALF_UP)
