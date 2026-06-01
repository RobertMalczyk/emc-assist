"""Deterministic LLM fallback — preserves M2.6.1 behavior under `--llm none`."""

from __future__ import annotations

from typing import Any

from emc_assistant.llm.assistant import (
    LlmAssistant,
    LlmMode,
    ProblemContext,
    RecommendationDraft,
    RedactedSnippet,
)
from emc_assistant.parasitics.model import ParasiticEstimate
from emc_assistant.recommendations.engine import (
    Recommendation,
    build_baseline_recommendations,
)


def _to_draft(rec: Recommendation) -> RecommendationDraft:
    return RecommendationDraft(
        id=rec.id,
        area=rec.area,
        severity=rec.severity,
        confidence=float(rec.confidence),
        problem=rec.problem,
        evidence=list(rec.evidence),
        proposed_change=dict(rec.proposed_change),
        limitations=list(rec.limitations),
        sources=list(rec.sources),
        citations=[],
        llm_generated=False,
        simulation_required=bool(rec.simulation_required),
        user_action=rec.user_action,
    )


class DeterministicAssistant(LlmAssistant):
    """Wraps the existing rule-based recommendation engine.

    `explain_recommendations()` here calls `build_baseline_recommendations`
    in `replace` mode (the M2.6.1 path) and simply returns drafts of the
    existing recommendations in `augment` mode (since there is no LLM to
    do the augmentation).

    `snippets` and `problem_context` are accepted for interface parity
    but are not consulted — the deterministic engine derives everything
    from `parasitics` + boolean flags.

    `complete()` is unsupported: the deterministic path has no LLM to
    invoke. The orchestrator avoids calling it by checking
    ``assistant.name == "deterministic"`` and routing each agent to its
    fallback method instead.
    """

    name = "deterministic"

    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        purpose: str,
        expected_output_tokens: int = 1500,
    ) -> str:
        raise NotImplementedError(
            "DeterministicAssistant has no LLM backend. Use the agent's "
            "deterministic fallback path instead, or pass --llm openai."
        )

    def explain_recommendations(
        self,
        *,
        problem_context: ProblemContext,
        parasitics: list[ParasiticEstimate],
        sim_metrics: dict[str, float],
        snippets: list[RedactedSnippet],
        mode: LlmMode = "replace",
        baseline_recs: list[Recommendation] | None = None,
    ) -> list[RecommendationDraft]:
        if mode == "augment" and baseline_recs is not None:
            return [_to_draft(r) for r in baseline_recs]
        recs = build_baseline_recommendations(
            parasitics,
            has_layout=problem_context.has_layout,
            has_stackup=problem_context.has_stackup,
        )
        return [_to_draft(r) for r in recs]
