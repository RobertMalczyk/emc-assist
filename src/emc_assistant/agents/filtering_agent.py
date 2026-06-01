"""Filtering specialist agent.

Owns DM/CM filter topology, damping, common-mode chokes, ferrite beads,
and filter–regulator stability. Strong fit for the M2.9 demo since the
buck example already has an input LC filter and a dual-LISN bench.
"""

from __future__ import annotations

from emc_assistant.agents.base import (
    Agent,
    AgentContext,
    AgentFinding,
    AgentInputs,
    Finding,
    Risk,
    SimulationRequest,
    select_metrics_by_prefix,
)
from emc_assistant.recommendations.engine import Recommendation


class FilteringAgent(Agent):
    name = "filtering"
    area_title = "Conducted-EMI filtering"
    prompt_filename = "filtering_agent.md"
    keywords = [
        "filter",
        "lc",
        "pi",
        "damping",
        "ferrite",
        "bead",
        "choke",
        "common mode",
        "differential mode",
        "y-cap",
        "x-cap",
        "cmrr",
        "dm",
        "cm",
    ]
    metric_prefixes = ["dm_", "cm_", "v_meas", "v_meas_band"]

    def select_relevant(self, ctx: AgentContext) -> AgentInputs:
        return AgentInputs(
            problem_context=ctx.problem_context,
            parasitics=list(ctx.parasitics),
            sim_metrics=select_metrics_by_prefix(ctx.sim_metrics, self.metric_prefixes),
            snippets=self._select_snippets(ctx),
            baseline_recs=list(ctx.baseline_recs),
            notes=["Focus: DM/CM filter topology and damping."],
        )

    def deterministic_finding(self, inputs: AgentInputs) -> AgentFinding:
        ctx = inputs.problem_context
        dm = inputs.sim_metrics.get("dm_peak")
        cm = inputs.sim_metrics.get("cm_peak")
        findings: list[Finding] = []
        risks: list[Risk] = []
        if dm is not None and cm is not None:
            if dm > 0 and cm / dm < 0.1:
                findings.append(
                    Finding(
                        title="DM dominates over CM",
                        detail=(
                            f"DM peak {dm:.3g} V vs CM peak {cm:.3g} V "
                            f"(CM/DM ≈ {cm / dm:.2g}). Filter changes should target "
                            "the differential path first."
                        ),
                        severity="info",
                    )
                )
            else:
                findings.append(
                    Finding(
                        title="CM is non-negligible",
                        detail=(
                            f"CM peak {cm:.3g} V vs DM peak {dm:.3g} V — the "
                            "common-mode path is active. A CM choke or Y-caps may "
                            "be warranted."
                        ),
                        severity="info",
                    )
                )
        else:
            findings.append(
                Finding(
                    title="Filtering area reached (deterministic fallback)",
                    detail=(
                        "Without an LLM, this agent emits the DM/CM balance check "
                        "from sim metrics when available, plus a generic damping risk."
                    ),
                    severity="info",
                )
            )
        risks.append(
            Risk(
                title="Undamped LC input filter ↔ regulator instability",
                detail=(
                    "Negative input impedance of the regulator can interact with an "
                    "undamped filter and cause oscillation. Verify the damping factor "
                    "(see SRC-074 SLUA929 if indexed)."
                ),
                likelihood="medium",
            )
        )
        recs = [
            Recommendation(
                id="REC-001",
                area=self.name,
                severity="info",
                confidence=0.4,
                problem=(
                    "Deterministic fallback for the filtering agent. "
                    "DM/CM balance and damping are the priority items; "
                    "--llm openai produces concrete component-value suggestions."
                ),
                evidence=[f"dm_peak={dm}, cm_peak={cm}"],
                proposed_change={
                    "type": "investigate",
                    "description": (
                        "Confirm input-filter damping and DM/CM balance against "
                        "the LISN measurements."
                    ),
                },
                simulation_required=True,
                user_action="Re-run with --llm openai for concrete values.",
                limitations=["Deterministic fallback; no LLM was invoked."],
                sources=["engineering_estimate"],
            )
        ]
        sim_requests = [
            SimulationRequest(
                description=(
                    "Sweep RC-damping (R 0.5–5 Ω, C 100 nF – 1 µF) on the input filter "
                    "and re-measure v_meas_band_peak_dbuv."
                ),
                kind="sweep",
            ),
        ]
        limitations: list[str] = []
        if not ctx.has_layout:
            limitations.append("No layout — filter component placement is a free variable.")
        return AgentFinding(
            agent=self.name,
            area=self.area_title,
            confidence=0.5 if (dm is not None and cm is not None) else 0.3,
            findings=findings,
            risks=risks,
            recommendations=recs,
            missing_data=[],
            simulation_requests=sim_requests,
            sources=["engineering_estimate"],
            limitations=limitations,
            llm_generated=False,
        )
