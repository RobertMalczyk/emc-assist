"""Power-integrity specialist agent.

Owns rail-impedance reasoning, input-filter ↔ regulator stability,
and how rail noise turns into conducted emissions.
"""

from __future__ import annotations

from emc_assistant.agents.base import (
    Agent,
    AgentContext,
    AgentFinding,
    AgentInputs,
    build_minimal_deterministic_finding,
    select_metrics_by_prefix,
)


class PowerIntegrityAgent(Agent):
    name = "power_integrity"
    area_title = "Power-rail integrity"
    prompt_filename = "power_integrity_agent.md"
    keywords = [
        "rail",
        "impedance",
        "decoupling",
        "input filter",
        "stability",
        "ripple",
        "ringing",
        "loop",
    ]
    metric_prefixes = ["v_meas", "dm_", "cm_", "vpeak", "vrms"]

    def select_relevant(self, ctx: AgentContext) -> AgentInputs:
        return AgentInputs(
            problem_context=ctx.problem_context,
            parasitics=[
                p
                for p in ctx.parasitics
                if p.parasitic_type in {"L", "C"} or p.structure.lower() in {"trace", "via", "cap"}
            ]
            or list(ctx.parasitics),
            sim_metrics=select_metrics_by_prefix(ctx.sim_metrics, self.metric_prefixes),
            snippets=self._select_snippets(ctx),
            baseline_recs=list(ctx.baseline_recs),
            notes=["Focus: rail-impedance shaping and input-filter stability."],
        )

    def deterministic_finding(self, inputs: AgentInputs) -> AgentFinding:
        return build_minimal_deterministic_finding(
            agent_name=self.name,
            area_title=self.area_title,
            inputs=inputs,
            focus=(
                "Rail-impedance peaks in the conducted-EMI band drive emissions; "
                "input-filter–regulator stability margins are the dominant risk."
            ),
            sweep_description=(
                "AC sweep 1 kHz – 30 MHz on the input rail to characterise Z(f) and locate peaks."
            ),
            confidence=0.35,
        )
