"""Decoupling-capacitor specialist agent."""

from __future__ import annotations

from emc_assistant.agents.base import (
    Agent,
    AgentContext,
    AgentFinding,
    AgentInputs,
    build_minimal_deterministic_finding,
    select_metrics_by_prefix,
)


class DecouplingAgent(Agent):
    name = "decoupling"
    area_title = "Decoupling capacitors"
    prompt_filename = "decoupling_agent.md"
    keywords = [
        "decoupling",
        "esr",
        "esl",
        "srf",
        "antiresonance",
        "mlcc",
        "bulk",
        "bypass",
        "via inductance",
        "dc bias",
        "capacitor",
    ]
    metric_prefixes = ["v_meas", "dm_", "cm_"]

    def select_relevant(self, ctx: AgentContext) -> AgentInputs:
        cap_parasitics = [
            p for p in ctx.parasitics if "cap" in p.structure.lower() or p.parasitic_type == "C"
        ]
        return AgentInputs(
            problem_context=ctx.problem_context,
            parasitics=cap_parasitics or list(ctx.parasitics),
            sim_metrics=select_metrics_by_prefix(ctx.sim_metrics, self.metric_prefixes),
            snippets=self._select_snippets(ctx),
            baseline_recs=list(ctx.baseline_recs),
            notes=["Focus: cap ESR/ESL/SRF, antiresonance, DC-bias derating."],
        )

    def deterministic_finding(self, inputs: AgentInputs) -> AgentFinding:
        return build_minimal_deterministic_finding(
            agent_name=self.name,
            area_title=self.area_title,
            inputs=inputs,
            focus=(
                "SRF and ESL of bulk + ceramic caps shape the high-frequency rail "
                "impedance; antiresonance peaks between two cap types are the typical risk."
            ),
            sweep_description=(
                "Sweep mounted-cap ESL across 0.5–3 nH band and observe the SRF shift in V(MEAS) FFT."
            ),
            confidence=0.35,
        )
