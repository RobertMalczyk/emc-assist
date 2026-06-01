"""DC/DC specialist agent.

Owns the converter stage: hot loop, switch node, snubbers, input/output
filters, sources of conducted EMI. Used as the per-area template for
the other M2.9 agents.
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


class DcDcAgent(Agent):
    """Specialist for the DC/DC converter stage."""

    name = "dcdc"
    area_title = "DC/DC switching stage"
    prompt_filename = "dcdc_agent.md"
    keywords = [
        "buck",
        "boost",
        "dcdc",
        "switch",
        "switching",
        "ripple",
        "snubber",
        "hot loop",
        "input filter",
        "output filter",
        "conducted",
        "emi",
    ]
    metric_prefixes = [
        "v_meas",
        "dm_",
        "cm_",
        "vpeak",
        "vrms",
        "vp2p",
        "v_meas_band",
    ]

    def select_relevant(self, ctx: AgentContext) -> AgentInputs:
        notes: list[str] = []
        if ctx.problem_context.topology:
            notes.append(f"Reported topology: {ctx.problem_context.topology}")
        if ctx.problem_context.switching_frequency_hz:
            f_sw = ctx.problem_context.switching_frequency_hz
            notes.append(f"Switching frequency: {f_sw / 1000:.0f} kHz")
        return AgentInputs(
            problem_context=ctx.problem_context,
            parasitics=list(ctx.parasitics),
            sim_metrics=select_metrics_by_prefix(ctx.sim_metrics, self.metric_prefixes),
            snippets=self._select_snippets(ctx),
            baseline_recs=list(ctx.baseline_recs),
            notes=notes,
        )

    def deterministic_finding(self, inputs: AgentInputs) -> AgentFinding:
        ctx = inputs.problem_context
        findings: list[Finding] = []
        risks: list[Risk] = []
        recs: list[Recommendation] = []
        missing_data: list[str] = []
        sim_requests: list[SimulationRequest] = []
        sources: list[str] = []
        limitations: list[str] = []

        topo = ctx.topology or "(unspecified)"
        findings.append(
            Finding(
                title="DC/DC switching stage identified",
                detail=(
                    f"Topology: {topo}. Switching frequency: "
                    f"{ctx.switching_frequency_hz or 'unspecified'} Hz. "
                    "Switch-node dv/dt and the hot-loop current path are the "
                    "primary conducted-EMI drivers."
                ),
                severity="info",
            )
        )

        v_meas_peak = inputs.sim_metrics.get("v_meas_peak")
        dm_peak = inputs.sim_metrics.get("dm_peak")
        cm_peak = inputs.sim_metrics.get("cm_peak")
        band_peak = inputs.sim_metrics.get("v_meas_band_peak_dbuv_150000_30000000")

        if v_meas_peak is not None:
            findings.append(
                Finding(
                    title="LISN-port peak observed",
                    detail=(
                        f"V(MEAS) peak = {v_meas_peak:.3g} V at the dual-LISN measurement port. "
                        "This is the headline conducted-emission proxy for the DC/DC stage."
                    ),
                    severity="info",
                )
            )
        else:
            missing_data.append("V(MEAS) peak from LTspice (run `pipeline run --mode local-run`).")

        if band_peak is not None:
            findings.append(
                Finding(
                    title="Conducted-band peak (150 kHz–30 MHz)",
                    detail=(
                        f"FFT band peak = {band_peak:.1f} dBµV. Compare against the relevant "
                        "CISPR class limit when one is on hand — this is engineering data, "
                        "not a compliance verdict."
                    ),
                    severity="info",
                )
            )

        if dm_peak is not None and cm_peak is not None:
            ratio = (cm_peak / dm_peak) if dm_peak > 0 else float("inf")
            if ratio < 0.1:
                detail = (
                    f"DM peak {dm_peak:.3g} V dominates CM peak {cm_peak:.3g} V "
                    f"(ratio CM/DM ≈ {ratio:.2g}). Filter changes should target the "
                    "differential path first."
                )
            else:
                detail = (
                    f"CM ({cm_peak:.3g} V) is comparable to DM ({dm_peak:.3g} V); "
                    "the common-mode path is active and the filtering / stack-up "
                    "agents will see correlated issues."
                )
            findings.append(
                Finding(title="DM vs CM balance", detail=detail, severity="info")
            )

        risks.append(
            Risk(
                title="Input-filter resonance in the conducted band",
                detail=(
                    "An undamped LC input filter near the converter has a resonant "
                    "peak that, if it lands inside 150 kHz–30 MHz, raises conducted "
                    "emissions. Verify damping and stability against the regulator's "
                    "negative input impedance."
                ),
                likelihood="medium",
            )
        )

        sim_requests.append(
            SimulationRequest(
                description=(
                    "Sweep input-filter inductor and bulk-cap ESR over realistic "
                    "manufacturing tolerance to locate the worst-case resonance."
                ),
                kind="sweep",
                parameters={"variable": "Ldm,Cin_esr", "axis": "tolerance"},
            )
        )

        recs.append(
            Recommendation(
                id="REC-001",
                area="dcdc",
                severity="info",
                confidence=0.5,
                problem=(
                    "Deterministic fallback for the DC/DC agent. Without an LLM, "
                    "we surface the observed simulation metrics and a generic input-filter "
                    "stability hypothesis; --llm openai produces topology-aware analysis."
                ),
                evidence=[
                    f"Observed v_meas_peak={v_meas_peak}, dm_peak={dm_peak}, "
                    f"cm_peak={cm_peak}, band_peak_dBuV={band_peak}.",
                ],
                proposed_change={
                    "type": "investigate",
                    "description": (
                        "Confirm input-filter damping and that the LC corner sits "
                        "well below the converter bandwidth."
                    ),
                },
                simulation_required=True,
                user_action="Re-run with --llm openai for richer analysis.",
                limitations=["Deterministic fallback; no LLM was invoked."],
                sources=["engineering_estimate"],
            )
        )
        sources.extend(rec.sources[0] for rec in recs if rec.sources)

        if not ctx.has_layout:
            limitations.append("No layout supplied — hot-loop area is an assumption.")
        if not ctx.has_stackup:
            limitations.append("No stack-up supplied — trace-inductance bands are wide.")

        return AgentFinding(
            agent=self.name,
            area=self.area_title,
            confidence=0.45 if (v_meas_peak is not None) else 0.25,
            findings=findings,
            risks=risks,
            recommendations=recs,
            missing_data=missing_data,
            simulation_requests=sim_requests,
            sources=list(dict.fromkeys(sources)),
            limitations=limitations,
            llm_generated=False,
        )
