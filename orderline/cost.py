"""Running cost per 1,000 orders: an estimate, and the measured number once you run the eval.

Prices are the first-party Claude API rates per million tokens (they also apply to Claude on
Microsoft Foundry, billed through the Microsoft Marketplace). Check current prices before you
quote them; they change.

Token counts here are estimates:
* an image costs roughly width x height / 750 tokens, capped by the model's maximum image size;
* text costs roughly one token per four characters;
* thinking is billed as output, so the output estimate includes headroom for it.

``python evals/run_eval.py --yes`` replaces every estimate with measured ``usage`` from real calls on the sample set.
"""

from __future__ import annotations

from dataclasses import dataclass

PRICES_PER_MTOK = {  # input, output (USD), first-party API, cached 2026-10-06
    "claude-opus-5-5": (4.00, 20.00),
    "claude-sonnet-5-5": (2.00, 10.00),
    "claude-haiku-5-5": (0.10, 0.50),
}
IMAGE_TOKEN_CAP = 4784  # largest images on current models
SYSTEM_AND_SCHEMA_TOKENS = 2_200  # system prompt plus the output schema, estimated


@dataclass
class CostEstimate:
    model: str
    input_tokens_per_order: int
    output_tokens_per_order: int
    usd_per_order: float

    @property
    def usd_per_1000(self) -> float:
        return self.usd_per_order * 1000


def image_tokens(width: int, height: int) -> int:
    return min(IMAGE_TOKEN_CAP, round(width * height / 750))


def estimate(
    model: str = "claude-opus-5-5",
    text_pages: int = 1,
    image_pages: int = 1,
    image_size: tuple[int, int] = (1545, 2000),  # a letter page rendered at 150 dpi, long edge capped at 2000
    chars_per_text_page: int = 3_000,
    lines_per_order: int = 6,
    thinking_headroom: float = 1.0,  # extra output for adaptive thinking, as a multiple of the answer
) -> CostEstimate:
    if model not in PRICES_PER_MTOK:
        raise ValueError(f"no price on file for {model}; add it to PRICES_PER_MTOK")
    price_in, price_out = PRICES_PER_MTOK[model]
    input_tokens = (
        SYSTEM_AND_SCHEMA_TOKENS
        + text_pages * (chars_per_text_page // 4)
        + image_pages * image_tokens(*image_size)
        + 120  # page labels and instructions
    )
    answer_tokens = 450 + 160 * lines_per_order
    output_tokens = round(answer_tokens * (1 + thinking_headroom))
    usd = input_tokens * price_in / 1e6 + output_tokens * price_out / 1e6
    return CostEstimate(model, input_tokens, output_tokens, round(usd, 5))


def measured_cost(model: str, input_tokens: int, output_tokens: int, orders: int) -> float:
    price_in, price_out = PRICES_PER_MTOK[model]
    total = input_tokens * price_in / 1e6 + output_tokens * price_out / 1e6
    return total / max(orders, 1) * 1000
