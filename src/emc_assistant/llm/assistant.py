"""Core types for the LLM-assisted recommendation layer."""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Any, Literal

from emc_assistant.parasitics.model import ParasiticEstimate
from emc_assistant.recommendations.engine import Recommendation


LlmMode = Literal["replace", "augment"]
"""How the LLM output relates to the deterministic baseline.

- ``replace``: the LLM writes all recommendations from scratch using the
  retrieved snippets. The deterministic baseline is not run.
- ``augment``: the deterministic baseline runs first; the LLM rewrites
  the prose fields (problem / evidence / limitations / proposed_change
  description) of each baseline recommendation but leaves the structural
  fields (severity, confidence, proposed_change.type, sources) untouched.
"""


@dataclass
class ProblemContext:
    """Compact engineering context handed to the LLM.

    Deliberately small: the user schematic never goes here; only
    structured summaries (topology class, frequency range, available /
    missing data) — see [[feedback_copyright_redaction_for_llm]] and
    `docs/09_security_privacy_licensing.md`.
    """

    project_id: str
    analysis_scope: str
    topology: str = ""
    input_voltage_v: float | None = None
    switching_frequency_hz: float | None = None
    load_current_a: float | None = None
    frequency_range_min_hz: float | None = None
    frequency_range_max_hz: float | None = None
    problem_hypothesis: str = ""
    has_layout: bool = False
    has_stackup: bool = False
    missing_data: list[str] = field(default_factory=list)


@dataclass
class RedactedSnippet:
    """A knowledge-base snippet safe to include in an outbound LLM prompt.

    Built by ``knowledge.retrieve.redact_for_llm`` from a curated rule and
    its source manifest entry. The ``excerpt`` is optional and capped at
    200 characters; it is omitted when the source's ``allowed_use`` does
    not permit verbatim quotation.
    """

    rule_id: str
    source_id: str
    summary: str
    """Our own summary in our own words (drawn from curated `.jsonl`
    fields like ``Default_value_for_agent``, ``Use_when``, etc.).
    Always safe to send."""
    excerpt: str | None = None
    """≤ 200-character verbatim excerpt. Present only when the source's
    ``allowed_use`` permits it."""


@dataclass
class RecommendationDraft:
    """LLM-or-fallback output before schema validation.

    Mirrors `recommendation.schema.json` but is a transport type rather
    than the schema-validated model. ``llm_generated`` is True when the
    text fields came from an LLM call. ``citations`` lists the Source_ID
    or knowledge-pack snippet IDs the LLM said it used (the deterministic
    fallback leaves it empty).
    """

    id: str
    area: str
    severity: str
    confidence: float
    problem: str
    evidence: list[str] = field(default_factory=list)
    proposed_change: dict = field(default_factory=dict)
    limitations: list[str] = field(default_factory=list)
    sources: list[str] = field(default_factory=list)
    citations: list[str] = field(default_factory=list)
    llm_generated: bool = False
    simulation_required: bool = True
    user_action: str = ""

    def to_schema_dict(self) -> dict:
        out: dict = {
            "id": self.id,
            "area": self.area,
            "severity": self.severity,
            "confidence": float(self.confidence),
            "problem": self.problem,
            "evidence": list(self.evidence),
            "proposed_change": dict(self.proposed_change),
            "simulation_required": bool(self.simulation_required),
            "user_action": self.user_action,
            "limitations": list(self.limitations),
            "sources": list(self.sources),
            "llm_generated": bool(self.llm_generated),
            "citations": list(self.citations),
        }
        return out


class LlmAssistant(ABC):
    """Contract every recommendation-writing backend must satisfy."""

    name: str = "abstract"
    """Short identifier used in logs and CLI output."""

    @abstractmethod
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
        """Produce recommendation drafts.

        ``mode='replace'`` ignores ``baseline_recs`` and writes from
        scratch. ``mode='augment'`` requires ``baseline_recs`` and
        returns the same number of drafts with the structural fields
        (id / area / severity / confidence / sources) preserved.
        """

    @abstractmethod
    def complete(
        self,
        *,
        messages: list[dict[str, Any]],
        purpose: str,
        expected_output_tokens: int = 1500,
    ) -> str:
        """Low-level chat completion. Returns the raw response text.

        Each implementation handles its own budget guard and privacy
        log. The M2.9 agent layer calls ``complete()`` per agent rather
        than going through ``explain_recommendations`` so that each
        agent can ship its own prompt and parser.

        ``purpose`` is a short tag like ``"agent.dcdc"`` written to the
        privacy log so the user can audit which call sent which payload.
        """
