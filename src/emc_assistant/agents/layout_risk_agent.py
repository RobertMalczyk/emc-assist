"""Layout-risk specialist agent.

Enumerates layout-dependent failure modes that the schematic cannot
expose. Always emits a "no layout" missing-data entry — even when the
user later supplies a layout, the M7 extraction is what closes the gap.
"""

from __future__ import annotations

from emc_assistant.agents.base import (
    Agent,
    AgentContext,
    AgentFinding,
    AgentInputs,
    Finding,
    Risk,
    select_metrics_by_prefix,
)
from emc_assistant.recommendations.engine import Recommendation


class LayoutRiskAgent(Agent):
    name = "layout_risk"
    area_title = "Layout-dependent risk"
    prompt_filename = "layout_risk_agent.md"
    keywords = [
        "layout",
        "hot loop",
        "switch node",
        "return path",
        "plane gap",
        "stitching",
        "via",
        "decoupling placement",
        "loop area",
    ]
    metric_prefixes = ["v_meas"]

    def select_relevant(self, ctx: AgentContext) -> AgentInputs:
        return AgentInputs(
            problem_context=ctx.problem_context,
            parasitics=list(ctx.parasitics),
            sim_metrics=select_metrics_by_prefix(ctx.sim_metrics, self.metric_prefixes),
            snippets=self._select_snippets(ctx),
            baseline_recs=list(ctx.baseline_recs),
            notes=[
                "Enumerate layout-dependent failure modes that the schematic "
                "cannot reveal. Confidence is low by design."
            ],
        )

    def deterministic_finding(self, inputs: AgentInputs) -> AgentFinding:
        ctx = inputs.problem_context
        findings = [
            Finding(
                title="Layout review required for confident verdict",
                detail=(
                    "Hot-loop area, switch-node copper, return-path continuity, "
                    "decoupling-cap loop inductance and plane gaps under fast edges "
                    "are all layout-dependent. Without layout data they remain "
                    "hypotheses."
                ),
                severity="info",
            )
        ]
        risks = [
            Risk(
                title="Hot-loop area larger than necessary",
                detail=(
                    "If the input cap is far from the switch-node loop, the loop "
                    "area is large and the radiated + conducted EMI both rise."
                ),
                likelihood="medium",
            ),
            Risk(
                title="Return-path discontinuity under fast edges",
                detail=(
                    "A break in the reference plane under the switch-node trace or "
                    "any fast signal increases CM emissions."
                ),
                likelihood="medium",
            ),
        ]
        recs = [
            Recommendation(
                id="REC-001",
                area=self.name,
                severity="medium",
                confidence=0.35,
                problem=(
                    "Layout data is not part of this run. Layout-dependent claims "
                    "(hot-loop area, return paths, decoupling-cap inductance) are "
                    "hypotheses until extraction or measurement."
                ),
                evidence=[
                    "No Gerber/ODB++/KiCad PCB file in the project input."
                ],
                proposed_change={
                    "type": "layout_review",
                    "description": (
                        "Schedule a layout review (or extraction in M7) focusing "
                        "on hot-loop area, switch-node copper and return-path "
                        "continuity."
                    ),
                },
                simulation_required=False,
                user_action="Supply a layout file for the next iteration.",
                limitations=["Layout review is manual today; extraction comes in M7."],
                sources=["engineering_estimate"],
            )
        ]
        return AgentFinding(
            agent=self.name,
            area=self.area_title,
            confidence=0.3,
            findings=findings,
            risks=risks,
            recommendations=recs,
            missing_data=[
                "Layout file (Gerber, ODB++, or KiCad PCB) not supplied",
            ],
            simulation_requests=[],
            sources=["engineering_estimate"],
            limitations=[
                "Deterministic fallback; no LLM was invoked.",
                "All layout-dependent claims are hypotheses without extraction.",
            ]
            if ctx.has_layout is False
            else ["Deterministic fallback; no LLM was invoked."],
            llm_generated=False,
        )
