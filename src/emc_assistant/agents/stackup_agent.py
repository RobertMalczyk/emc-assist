"""Stack-up specialist agent."""

from __future__ import annotations

from emc_assistant.agents.base import (
    Agent,
    AgentContext,
    AgentFinding,
    AgentInputs,
    build_minimal_deterministic_finding,
    select_metrics_by_prefix,
)


class StackupAgent(Agent):
    name = "stackup"
    area_title = "PCB stack-up"
    prompt_filename = "stackup_agent.md"
    keywords = [
        "stack",
        "stack-up",
        "stackup",
        "layer",
        "plane",
        "dielectric",
        "prepreg",
        "fr-4",
        "microstrip",
        "stripline",
    ]
    metric_prefixes: list[str] = []

    def select_relevant(self, ctx: AgentContext) -> AgentInputs:
        return AgentInputs(
            problem_context=ctx.problem_context,
            parasitics=list(ctx.parasitics),
            sim_metrics=select_metrics_by_prefix(ctx.sim_metrics, ["v_meas"]),
            snippets=self._select_snippets(ctx),
            baseline_recs=list(ctx.baseline_recs),
            notes=["Focus: layer count, plane spacing, return-path implications."],
        )

    def deterministic_finding(self, inputs: AgentInputs) -> AgentFinding:
        return build_minimal_deterministic_finding(
            agent_name=self.name,
            area_title=self.area_title,
            inputs=inputs,
            focus=(
                "Layer count, plane spacing, and plane–plane capacitance set the "
                "high-frequency rail impedance floor; without stack-up data the "
                "trace-inductance bands stay wide."
            ),
            sweep_description=None,
            missing_when_no_stackup=True,
            confidence=0.3,
        )
