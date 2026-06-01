"""AI cost-budget guardrail.

Estimates the cost of an LLM call from input + projected output tokens
and aborts the call when the estimate exceeds the user-supplied budget.

Pricing here is a coarse approximation kept as a small static table —
update it if OpenAI changes its rates. The estimate is intentionally
conservative (uses the high end of the expected output range and a 1.5×
fudge factor on input tokens) so a "false-pass" never bills the user.

The module exposes two granularities:

- ``assert_within_budget(estimate, budget_usd)`` — single-call cap.
  Used by ``OpenAiAssistant.explain_recommendations`` before M2.9.
- ``BudgetTracker(cap_usd)`` — run-level cumulative cap. Threaded into
  the assistant in M2.9 so a 10-agent pipeline run can't blow past the
  user's ``--llm-budget-usd`` by firing each agent independently.
"""

from __future__ import annotations

from dataclasses import dataclass


# Per-million-token pricing in USD. Keep conservative (round up).
_PRICING: dict[str, tuple[float, float]] = {
    # model: (input $/Mtok, output $/Mtok)
    "gpt-5-mini": (0.25, 2.00),
    "gpt-5": (2.00, 10.00),
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (5.00, 15.00),
}

_DEFAULT_OUTPUT_TOKENS = 1500
"""Conservative upper bound on a single-call output length for the
recommendations use case (M2.7). The orchestrator in M2.11 may use a
larger ceiling."""

_INPUT_FUDGE = 1.5
"""Multiplier on token counts derived from char-count approximations to
avoid under-estimating."""


class BudgetExceeded(Exception):
    """Raised when an LLM call's estimated cost exceeds the user budget."""


@dataclass
class CostEstimate:
    model: str
    input_tokens: int
    expected_output_tokens: int
    input_cost_usd: float
    output_cost_usd: float

    @property
    def total_usd(self) -> float:
        return self.input_cost_usd + self.output_cost_usd


def _approx_tokens(text: str) -> int:
    """Rough token estimate: ~4 chars per token, scaled by the fudge factor.

    Good enough for budget guarding. The privacy log records the real
    token counts returned by the API after each call.
    """
    return int(len(text) / 4 * _INPUT_FUDGE)


def estimate_cost_usd(
    prompt_text: str,
    *,
    model: str,
    expected_output_tokens: int = _DEFAULT_OUTPUT_TOKENS,
) -> CostEstimate:
    if model not in _PRICING:
        # Unknown model — assume the most expensive entry so we err on
        # the side of caution.
        in_per_mtok, out_per_mtok = max(_PRICING.values())
    else:
        in_per_mtok, out_per_mtok = _PRICING[model]
    in_tokens = _approx_tokens(prompt_text)
    in_cost = in_tokens / 1_000_000 * in_per_mtok
    out_cost = expected_output_tokens / 1_000_000 * out_per_mtok
    return CostEstimate(
        model=model,
        input_tokens=in_tokens,
        expected_output_tokens=expected_output_tokens,
        input_cost_usd=in_cost,
        output_cost_usd=out_cost,
    )


def assert_within_budget(
    estimate: CostEstimate,
    *,
    budget_usd: float,
) -> None:
    """Raise ``BudgetExceeded`` when the estimated cost is over the budget."""
    if estimate.total_usd > budget_usd:
        raise BudgetExceeded(
            f"Estimated LLM cost ${estimate.total_usd:.4f} exceeds budget "
            f"${budget_usd:.4f} for model {estimate.model} "
            f"(in ≈ {estimate.input_tokens} tok, out ≤ {estimate.expected_output_tokens} tok). "
            f"Pass --llm-budget-usd with a higher amount or --llm none to skip."
        )


@dataclass
class BudgetTracker:
    """Run-level cumulative spend tracker.

    The orchestrator constructs one tracker per ``pipeline run`` and
    passes it to the assistant. Each LLM call checks
    ``assert_can_afford(estimate)`` before firing and ``record(amount)``
    after the call completes.

    The tracker uses *estimated* USD figures, not post-call actuals,
    because the budget gate must fire before the network I/O. Post-call
    usage tokens are still recorded in the privacy log.
    """

    cap_usd: float
    spent_usd: float = 0.0

    def assert_can_afford(self, estimate: CostEstimate) -> None:
        projected = self.spent_usd + estimate.total_usd
        if projected > self.cap_usd:
            raise BudgetExceeded(
                f"Cumulative LLM cost would reach ${projected:.4f} "
                f"(already spent ${self.spent_usd:.4f}, next call ${estimate.total_usd:.4f}) "
                f"exceeding run budget ${self.cap_usd:.4f}. "
                f"Pass --llm-budget-usd with a higher amount or --llm none to skip."
            )

    def record(self, amount_usd: float) -> None:
        self.spent_usd += float(amount_usd)
