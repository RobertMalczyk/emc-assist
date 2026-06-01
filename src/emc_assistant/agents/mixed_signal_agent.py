"""Mixed-signal specialist agent.

Comments on analog/digital separation, ADC/DAC references, and the
AGND/DGND return-path question. Dormant for a DC/DC-only schematic.
"""

from __future__ import annotations

from emc_assistant.agents.base import (
    Agent,
    AgentContext,
    AgentFinding,
    AgentInputs,
    Finding,
    select_metrics_by_prefix,
)
from emc_assistant.recommendations.engine import Recommendation


class MixedSignalAgent(Agent):
    name = "mixed_signal"
    area_title = "Mixed-signal design"
    prompt_filename = "mixed_signal_agent.md"
    keywords = [
        "analog",
        "digital",
        "agnd",
        "dgnd",
        "adc",
        "dac",
        "reference",
        "sensor",
        "op-amp",
        "front-end",
    ]
    metric_prefixes: list[str] = []

    def select_relevant(self, ctx: AgentContext) -> AgentInputs:
        return AgentInputs(
            problem_context=ctx.problem_context,
            parasitics=list(ctx.parasitics),
            sim_metrics=select_metrics_by_prefix(ctx.sim_metrics, ["v_meas"]),
            snippets=self._select_snippets(ctx),
            baseline_recs=list(ctx.baseline_recs),
            notes=[
                "Mixed-signal area is dormant for a DC/DC-only schematic; the "
                "right answer is a single continuous reference plane, never a "
                "split ground."
            ],
        )

    def deterministic_finding(self, inputs: AgentInputs) -> AgentFinding:
        findings = [
            Finding(
                title="No analog-sensitive front-end detected",
                detail=(
                    "The schematic context does not name an ADC/DAC reference, "
                    "op-amp front-end, or sensor amplifier. Revisit if analog "
                    "blocks are added downstream of the converter."
                ),
                severity="info",
            )
        ]
        recs = [
            Recommendation(
                id="REC-001",
                area=self.name,
                severity="info",
                confidence=0.4,
                problem=(
                    "Mixed-signal area is dormant in a DC/DC-only design. The "
                    "DC/DC switching noise is what couples into analog rails "
                    "downstream; treat that path with the filtering and "
                    "decoupling agents."
                ),
                evidence=["No analog-sensitive block declared in problem context."],
                proposed_change={
                    "type": "investigate",
                    "description": (
                        "When an ADC/DAC or sensor amp is added, run a low-pass "
                        "LC + ferrite on the analog supply and keep one continuous "
                        "reference plane."
                    ),
                },
                simulation_required=False,
                user_action="Revisit when analog blocks are added.",
                limitations=["Dormant area for the buck demo."],
                sources=["engineering_estimate"],
            )
        ]
        return AgentFinding(
            agent=self.name,
            area=self.area_title,
            confidence=0.4,
            findings=findings,
            risks=[],
            recommendations=recs,
            missing_data=[],
            simulation_requests=[],
            sources=["engineering_estimate"],
            limitations=["Deterministic fallback; no LLM was invoked."],
            llm_generated=False,
        )
