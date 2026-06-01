"""High-speed-signals specialist agent.

In a pure DC/DC design with no high-speed bus, the agent's job is to
say so and to flag the switch node as the only "fast" net.
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


class HighSpeedAgent(Agent):
    name = "high_speed"
    area_title = "High-speed signal integrity"
    prompt_filename = "high_speed_agent.md"
    keywords = [
        "clock",
        "high speed",
        "high-speed",
        "ethernet",
        "usb",
        "lvds",
        "can",
        "edge rate",
        "termination",
        "return path",
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
                "In a pure DC/DC design the switch node is the only fast edge; "
                "flag dormancy if no other high-speed nets exist."
            ],
        )

    def deterministic_finding(self, inputs: AgentInputs) -> AgentFinding:
        findings = [
            Finding(
                title="No dedicated high-speed bus detected",
                detail=(
                    "The schematic context does not name a clock above 10 MHz or "
                    "a fast serial bus (USB, Ethernet, LVDS, CAN-FD). The DC/DC "
                    "switch node remains the dominant fast edge — covered by the "
                    "dcdc agent."
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
                    "High-speed area is dormant in a DC/DC-only design. Revisit "
                    "if high-speed buses are added."
                ),
                evidence=["No high-speed bus declared in problem context."],
                proposed_change={
                    "type": "investigate",
                    "description": (
                        "If a clock or fast serial bus joins this board, re-run "
                        "with high_speed agent in active mode and supply the line "
                        "parameters."
                    ),
                },
                simulation_required=False,
                user_action="Revisit when high-speed nets are added.",
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
